import os
import tempfile
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from uuid import UUID
import time

from app.celery_worker import celery
from app.database import SessionLocal
from app.models import Document, DocumentFile
from app.storage import minio_client, ensure_bucket_exists
from app.config import settings

logger = logging.getLogger(__name__)


def get_db():
    """데이터베이스 세션 생성"""
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()


@celery.task(name="upload_file_to_minio", bind=True, max_retries=3)
def upload_file_to_minio(self, file_path, target_path, document_id, file_id=None):
    """
    로컬 파일을 MinIO에 업로드하는 작업

    Args:
        file_path: 로컬 파일 경로
        target_path: MinIO 대상 경로
        document_id: 관련 문서 ID
        file_id: 파일 ID (기존 파일이 있는 경우)
    """
    task_id = self.request.id
    logger.info(f"Task {task_id}: 파일 업로드 시작 - {os.path.basename(file_path)}")

    # 버킷 존재 확인
    ensure_bucket_exists()

    try:
        # 파일 존재 확인
        if not os.path.exists(file_path):
            error_msg = f"업로드할 파일을 찾을 수 없음: {file_path}"
            logger.error(f"Task {task_id}: {error_msg}")

            # 재시도 가능한 경우 재시도
            if self.request.retries < self.max_retries:
                logger.info(f"Task {task_id}: 파일 업로드 재시도 ({self.request.retries + 1}/{self.max_retries})")
                self.retry(countdown=5)

            raise FileNotFoundError(error_msg)

        # 파일 크기 확인
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            error_msg = f"파일 크기가 0: {file_path}"
            logger.error(f"Task {task_id}: {error_msg}")
            raise ValueError(error_msg)

        logger.info(f"Task {task_id}: 파일 크기 - {file_size} 바이트")

        # 파일 내용 검증
        try:
            with open(file_path, "rb") as f:
                # 파일의 첫 100바이트 읽기 (파일이 손상되지 않았는지 확인)
                first_bytes = f.read(min(100, file_size))
                if not first_bytes:
                    error_msg = f"파일 내용을 읽을 수 없음: {file_path}"
                    logger.error(f"Task {task_id}: {error_msg}")
                    raise ValueError(error_msg)
        except Exception as read_err:
            logger.error(f"Task {task_id}: 파일 읽기 오류 - {str(read_err)}")
            raise

        # 파일 타입 추출
        _, file_ext = os.path.splitext(file_path)
        if file_ext.lower() in [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"]:
            content_type = (
                f"application/{file_ext[1:]}x"
                if file_ext in [".doc", ".xls", ".ppt"]
                else f"application/{file_ext[1:]}"
            )
        elif file_ext.lower() in [".jpg", ".jpeg", ".png", ".gif"]:
            content_type = f"image/{file_ext[1:]}"
        else:
            content_type = "application/octet-stream"

        # MinIO에 파일 업로드 - 새 클라이언트 인스턴스 사용 (인증 문제 방지)
        from minio import Minio

        # 새 Minio 클라이언트 인스턴스 생성
        fresh_minio_client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )

        # 업로드 전 버킷 확인
        if not fresh_minio_client.bucket_exists(settings.MINIO_BUCKET_NAME):
            logger.warning(f"Task {task_id}: 버킷이 존재하지 않습니다. 새로 생성합니다.")
            fresh_minio_client.make_bucket(settings.MINIO_BUCKET_NAME)

        # 같은 경로에 이미 파일이 있는지 확인
        try:
            existing_stat = fresh_minio_client.stat_object(settings.MINIO_BUCKET_NAME, target_path)
            logger.warning(
                f"Task {task_id}: 이미 존재하는 파일을 덮어씁니다 - {target_path} (크기: {existing_stat.size})"
            )
            # 기존 파일 삭제 (선택적)
            # fresh_minio_client.remove_object(settings.MINIO_BUCKET_NAME, target_path)
        except:
            pass  # 파일이 없으면 정상으로 진행

        logger.info(f"Task {task_id}: MinIO 업로드 시작 - {target_path}")

        # 파일 업로드 - 실패 시 최대 3번 재시도
        upload_success = False
        upload_attempts = 0
        max_attempts = 3
        last_error = None

        while not upload_success and upload_attempts < max_attempts:
            upload_attempts += 1
            try:
                # 파일 업로드
                fresh_minio_client.fput_object(
                    settings.MINIO_BUCKET_NAME, target_path, file_path, content_type=content_type
                )
                upload_success = True
                logger.info(
                    f"Task {task_id}: MinIO 업로드 성공 (시도 {upload_attempts}/{max_attempts}) - {target_path}"
                )
            except Exception as upload_err:
                last_error = upload_err
                logger.error(
                    f"Task {task_id}: MinIO 업로드 실패 (시도 {upload_attempts}/{max_attempts}) - {str(upload_err)}"
                )
                if upload_attempts < max_attempts:
                    time.sleep(2)  # 재시도 전 대기

        if not upload_success:
            raise Exception(f"파일 업로드 실패 (최대 시도 횟수 초과): {str(last_error)}")

        # 업로드 후 파일 존재 검증
        validation_attempts = 0
        max_validation_attempts = 3
        validation_success = False

        while not validation_success and validation_attempts < max_validation_attempts:
            validation_attempts += 1
            try:
                # 파일 존재 확인
                stat_result = fresh_minio_client.stat_object(settings.MINIO_BUCKET_NAME, target_path)

                # 파일 크기 확인
                if stat_result.size != file_size:
                    logger.warning(f"Task {task_id}: 파일 크기 불일치 - 로컬: {file_size}, MinIO: {stat_result.size}")
                    if validation_attempts < max_validation_attempts:
                        time.sleep(1)  # 다음 검증 전 대기
                        continue
                    else:
                        raise Exception(f"파일 크기 불일치 - 로컬: {file_size}, MinIO: {stat_result.size}")

                validation_success = True
                logger.info(
                    f"Task {task_id}: 파일 업로드 검증 성공 (시도 {validation_attempts}/{max_validation_attempts}) - {target_path}, 크기: {stat_result.size}"
                )
            except Exception as verify_err:
                logger.error(
                    f"Task {task_id}: 파일 업로드 검증 실패 (시도 {validation_attempts}/{max_validation_attempts}) - {str(verify_err)}"
                )
                if validation_attempts < max_validation_attempts:
                    time.sleep(2)  # 재시도 전 대기
                else:
                    raise Exception(f"파일 업로드 검증 실패: {str(verify_err)}")

        # 데이터베이스 업데이트
        db = get_db()

        # 문서 조회
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            logger.error(f"Task {task_id}: 문서 ID {document_id}를 찾을 수 없습니다.")
            return {"status": "error", "message": "Document not found"}

        # 파일 ID가 제공된 경우 해당 파일 업데이트
        if file_id:
            try:
                file = db.query(DocumentFile).filter(DocumentFile.id == file_id).first()
                if file:
                    file.file_path = target_path
                    file.processing_status = "completed"
                    file.updated_at = datetime.utcnow()

                    # 파일 메타데이터 업데이트
                    file_metadata = file.file_metadata or {}
                    file_metadata["upload_completed_at"] = datetime.utcnow().isoformat()
                    file_metadata["upload_task_id"] = task_id
                    file_metadata["file_size"] = file_size
                    file_metadata["content_type"] = content_type
                    file_metadata["upload_validation_success"] = True
                    file_metadata["upload_attempts"] = upload_attempts
                    file_metadata["validation_attempts"] = validation_attempts
                    file.file_metadata = file_metadata

                    db.commit()
                    logger.info(f"Task {task_id}: 파일 {file_id} 업데이트 완료")
                else:
                    logger.error(f"Task {task_id}: 파일 ID {file_id}를 찾을 수 없습니다.")
            except Exception as db_error:
                logger.error(f"Task {task_id}: 파일 메타데이터 업데이트 오류 - {str(db_error)}")
                # 오류를 발생시키지 않고 계속 진행

        # 임시 파일 정리
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Task {task_id}: 임시 파일 삭제 완료 - {file_path}")
        except Exception as cleanup_error:
            logger.warning(f"Task {task_id}: 임시 파일 삭제 실패 - {str(cleanup_error)}")

        # 작업 완료
        return {
            "status": "success",
            "document_id": str(document_id),
            "path": target_path,
            "task_id": task_id,
            "file_size": file_size,
            "content_type": content_type,
            "upload_attempts": upload_attempts,
            "validation_attempts": validation_attempts,
        }
    except Exception as e:
        logger.error(f"Task {task_id}: 파일 업로드 중 오류 발생 - {str(e)}")
        # 작업 실패 상태 업데이트
        try:
            if file_id:
                db = get_db()
                file = db.query(DocumentFile).filter(DocumentFile.id == file_id).first()
                if file:
                    file.processing_status = "failed"
                    file_metadata = file.file_metadata or {}
                    file_metadata["upload_error"] = str(e)
                    file_metadata["error_time"] = datetime.utcnow().isoformat()
                    file.file_metadata = file_metadata
                    db.commit()
        except Exception as db_error:
            logger.error(f"Task {task_id}: DB 업데이트 중 추가 오류 - {str(db_error)}")

        # 오류 전파
        raise


@celery.task(name="download_file_from_minio", bind=True)
def download_file_from_minio(self, minio_path, local_target_path=None):
    """
    MinIO에서 파일을 다운로드하는 작업

    Args:
        minio_path: MinIO에서의 파일 경로
        local_target_path: 로컬에 저장할 경로 (지정하지 않으면 임시 파일 생성)
    """
    task_id = self.request.id
    logger.info(f"Task {task_id}: 파일 다운로드 시작 - {minio_path}")

    # 임시 파일 경로 생성 (target_path가 제공되지 않은 경우)
    if not local_target_path:
        file_ext = os.path.splitext(minio_path)[1]
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_ext)
        local_target_path = temp_file.name
        temp_file.close()

    try:
        # MinIO에서 파일 다운로드
        minio_client.fget_object(settings.MINIO_BUCKET_NAME, minio_path, local_target_path)

        logger.info(f"Task {task_id}: 파일 다운로드 완료 - {minio_path} -> {local_target_path}")
        return {"status": "success", "minio_path": minio_path, "local_path": local_target_path, "task_id": task_id}
    except Exception as e:
        logger.error(f"Task {task_id}: 파일 다운로드 중 오류 발생 - {str(e)}")
        # 임시 파일 삭제
        if os.path.exists(local_target_path):
            os.remove(local_target_path)
        # 오류 전파
        raise


@celery.task(name="upload_file_content_to_minio", bind=True)
def upload_file_content_to_minio(
    self, file_content_str, target_path, document_id, content_type="application/octet-stream", file_id=None
):
    """
    파일 내용을 직접 MinIO에 업로드하는 작업 (임시 파일 저장 없이)

    Args:
        file_content_str: 파일 내용 (바이너리 데이터가 문자열로 인코딩됨)
        target_path: MinIO 대상 경로
        document_id: 관련 문서 ID
        content_type: 파일 MIME 타입
        file_id: 파일 ID (기존 파일이 있는 경우)
    """
    task_id = self.request.id
    logger.info(f"Task {task_id}: 파일 직접 업로드 시작 - {target_path}")

    # 버킷 존재 확인
    ensure_bucket_exists()

    try:
        # 문자열로 인코딩된 바이너리 데이터를 다시 바이너리로 변환
        file_content = file_content_str.encode("latin1")
        file_size = len(file_content)

        # MinIO에 직접 업로드
        import io

        minio_client.put_object(
            settings.MINIO_BUCKET_NAME, target_path, io.BytesIO(file_content), file_size, content_type=content_type
        )

        # 데이터베이스 업데이트
        db = get_db()

        # 문서 조회
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            logger.error(f"Task {task_id}: 문서 ID {document_id}를 찾을 수 없습니다.")
            return {"status": "error", "message": "Document not found"}

        # 파일 ID가 제공된 경우 해당 파일 업데이트
        if file_id:
            file = db.query(DocumentFile).filter(DocumentFile.id == file_id).first()
            if file:
                file.file_path = target_path
                file.processing_status = "completed"
                file.updated_at = datetime.utcnow()

                # 파일 메타데이터 업데이트
                file_metadata = file.file_metadata or {}
                file_metadata["upload_completed_at"] = datetime.utcnow().isoformat()
                file_metadata["upload_task_id"] = task_id
                file_metadata["file_size"] = file_size
                file_metadata["content_type"] = content_type
                file.file_metadata = file_metadata

                db.commit()
                logger.info(f"Task {task_id}: 파일 {file_id} 업데이트 완료")
            else:
                logger.error(f"Task {task_id}: 파일 ID {file_id}를 찾을 수 없습니다.")

        # 작업 완료
        return {"status": "success", "document_id": str(document_id), "path": target_path, "task_id": task_id}
    except Exception as e:
        logger.error(f"Task {task_id}: 파일 업로드 중 오류 발생 - {str(e)}")
        # 작업 실패 상태 업데이트
        try:
            if file_id:
                db = get_db()
                file = db.query(DocumentFile).filter(DocumentFile.id == file_id).first()
                if file:
                    file.processing_status = "failed"
                    file_metadata = file.file_metadata or {}
                    file_metadata["upload_error"] = str(e)
                    file_metadata["error_time"] = datetime.utcnow().isoformat()
                    file.file_metadata = file_metadata
                    db.commit()
        except Exception as db_error:
            logger.error(f"Task {task_id}: DB 업데이트 중 추가 오류 - {str(db_error)}")

        # 오류 전파
        raise
