import os
import uuid
import json
import tempfile
from minio import Minio
from minio.error import S3Error
from fastapi import UploadFile
from typing import List, Dict, Tuple, Optional, BinaryIO
from datetime import timedelta
import io
import logging
import time
import urllib.parse

from app.config import settings

# MinIO 클라이언트 설정
minio_client = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE,
)

# MinIO 외부 엔드포인트 - 환경 변수에서 가져오거나 기본값 사용
# 기본값: http://localhost:9000 (개발 환경용)
MINIO_EXTERNAL_ENDPOINT = os.environ.get("MINIO_EXTERNAL_ENDPOINT", "localhost:9000")


# 내부 URL을 외부 URL로 변환하는 함수
def convert_internal_url_to_external(url: str) -> str:
    """내부 MinIO URL을 외부에서 접근 가능한 URL로 변환합니다."""
    if not url:
        return url

    # 디버깅 정보
    print(f"변환 전 URL: {url}")

    # 도커 컨테이너 내부 주소를 외부 주소로 변경
    if "minio:9000" in url:
        # HTTPS 사용 여부에 따라 프로토콜 설정
        protocol = "https://" if settings.MINIO_SECURE else "http://"
        url = url.replace("http://minio:9000", f"{protocol}{MINIO_EXTERNAL_ENDPOINT}")

    # 파라미터가 두 번 인코딩되는 문제 방지
    try:
        # URL 파싱
        parsed_url = urllib.parse.urlparse(url)

        # 쿼리 파라미터 파싱 후 다시 인코딩
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # 파라미터 재구성
        new_query = urllib.parse.urlencode(query_params, doseq=True)

        # URL 재구성
        url_parts = list(parsed_url)
        url_parts[4] = new_query  # 인덱스 4는 쿼리 문자열

        # 최종 URL
        url = urllib.parse.urlunparse(url_parts)
    except Exception as parse_err:
        print(f"URL 파싱 오류 (무시됨): {str(parse_err)}")

    # 디버깅 정보 로깅
    print(f"변환 후 URL: {url}")

    return url


# 버킷 존재 여부 확인 및 생성 함수
def ensure_bucket_exists():
    try:
        if not minio_client.bucket_exists(settings.MINIO_BUCKET_NAME):
            minio_client.make_bucket(settings.MINIO_BUCKET_NAME)
            print(f"Bucket '{settings.MINIO_BUCKET_NAME}' created successfully")
        return True
    except S3Error as err:
        print(f"Error occurred: {err}")
        return False


# 파일 업로드 함수 (단일 파일) - 동기 처리
async def upload_file(file: UploadFile, user_id: str) -> str:
    # 버킷 존재 여부 확인
    ensure_bucket_exists()

    # 파일 확장자 추출
    filename = file.filename
    extension = os.path.splitext(filename)[1]

    # 고유한 파일 이름 생성
    unique_filename = f"{user_id}/{uuid.uuid4()}{extension}"

    # 임시 파일로 저장
    temp_file_path = f"/tmp/{unique_filename.replace('/', '_')}"
    with open(temp_file_path, "wb") as buffer:
        file_content = await file.read()
        buffer.write(file_content)

    # MinIO에 업로드
    try:
        minio_client.fput_object(settings.MINIO_BUCKET_NAME, unique_filename, temp_file_path)

        # 임시 파일 삭제
        os.remove(temp_file_path)

        return unique_filename
    except S3Error as err:
        print(f"Error occurred during upload: {err}")
        # 임시 파일 삭제
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise


# 다중 파일 업로드 함수 - 비동기 처리 지원
async def upload_multiple_files(
    files: List[UploadFile], user_id: str, document_id: str = None, async_processing: bool = False
) -> List[Dict[str, str]]:
    """
    여러 파일을 MinIO에 업로드하는 함수

    Args:
        files: 업로드할 파일 리스트
        user_id: 사용자 ID
        document_id: 문서 ID (비동기 처리시 필요)
        async_processing: 비동기 처리 여부

    Returns:
        업로드 결과 목록 (파일 정보 포함)
    """
    # 버킷 존재 여부 확인
    ensure_bucket_exists()

    uploaded_files = []
    tasks = []

    # DocumentFile 모델을 사용하기 위한 DB 세션
    # (지연 임포트로 순환 참조 방지)
    from app.database import SessionLocal
    from app.models import DocumentFile, Document
    from uuid import UUID

    # DB 세션 생성
    db = SessionLocal()

    try:
        # 1. 문서 ID 유효성 확인 (document_id가 제공된 경우)
        if document_id:
            try:
                # 문자열을 UUID로 변환하여 유효한 형식인지 먼저 확인
                document_uuid = UUID(document_id)

                # 해당 ID의 문서가 실제로 존재하는지 확인
                document = db.query(Document).filter(Document.id == document_uuid).first()
                if not document:
                    raise ValueError(f"문서 ID {document_id}가 데이터베이스에 존재하지 않습니다.")

                # 확인이 완료된 실제 document_id 사용
                validated_document_id = document.id

            except (ValueError, TypeError) as e:
                # UUID 변환 실패 또는 문서가 존재하지 않는 경우
                logger = logging.getLogger(__name__)
                logger.error(f"문서 ID 검증 실패: {str(e)}")

                # document_id가 필요한 비동기 처리에서는 오류 발생
                if async_processing:
                    raise ValueError(f"유효하지 않은 문서 ID: {document_id}")

                # 동기 처리에서는 None으로 설정하고 계속 진행
                validated_document_id = None
                document_id = None
        else:
            validated_document_id = None

        for file in files:
            # 파일 확장자 추출
            original_filename = file.filename
            extension = os.path.splitext(original_filename)[1].lower()

            # 고유한 파일 이름 생성 - 사용자 ID 폴더 제거하고 플랫 구조 사용
            file_uuid = uuid.uuid4()
            unique_filename = f"{file_uuid}{extension}"

            # 파일 콘텐츠 읽기
            file_content = await file.read()
            file_size = len(file_content)
            content_type = file.content_type or "application/octet-stream"

            # 파일 메타데이터 저장
            file_info = {
                "original_name": original_filename,
                "path": unique_filename,  # 플랫 구조의 경로
                "type": extension[1:],  # .pdf -> pdf
                "size": file_size,
                "user_id": user_id,  # 사용자 ID는 메타데이터로 저장
            }

            # DB에 파일 정보 저장 (document_id가 있고 유효한 경우에만)
            db_file = None
            if validated_document_id is not None:
                # 임시 파일 레코드 생성
                db_file = DocumentFile(
                    document_id=validated_document_id,
                    original_filename=original_filename,
                    file_path=unique_filename,  # 플랫 구조의 경로 저장
                    file_type=extension[1:],
                    file_size=file_size,
                    content_type=content_type,
                    processing_status="processing",
                    file_metadata={
                        "upload_type": "async" if async_processing else "sync",
                        "uploaded_by": user_id,  # 사용자 ID는 메타데이터로 저장
                    },
                )
                db.add(db_file)

                # 즉시 flush해서 ID 생성 - 커밋은 아래에서 진행
                try:
                    db.flush()
                    # ID를 파일 정보에 추가
                    file_info["file_id"] = str(db_file.id)
                except Exception as flush_error:
                    db.rollback()  # 오류 발생 시 롤백
                    logger = logging.getLogger(__name__)
                    logger.error(f"DB flush 오류: {str(flush_error)}")
                    raise ValueError(f"파일 정보 저장 실패: {str(flush_error)}")

            if async_processing and validated_document_id is not None:
                # 비동기 처리를 위해 임시 파일로 저장 - 공유 디렉토리 사용
                # Docker 볼륨이 공유되는 디렉토리 사용
                shared_tmp_dir = "/app/shared_tmp"
                os.makedirs(shared_tmp_dir, exist_ok=True)

                # 고유한 임시 파일 경로 생성
                temp_file_id = uuid.uuid4()
                temp_file_path = f"{shared_tmp_dir}/{temp_file_id}{extension}"

                # 임시 파일에 콘텐츠 저장
                with open(temp_file_path, "wb") as buffer:
                    buffer.write(file_content)

                # Celery 태스크로 비동기 처리
                from app.tasks.file_tasks import upload_file_to_minio

                # 파일 경로와 file_id를 전달하여 비동기 작업 등록
                file_id = db_file.id if db_file else None
                task = upload_file_to_minio.delay(
                    temp_file_path,
                    unique_filename,  # 플랫 구조의 경로
                    str(validated_document_id),
                    str(file_id) if file_id else None,
                )

                # 작업 ID 저장
                file_info["task_id"] = task.id
                file_info["status"] = "processing"
                tasks.append(task)

                # 메타데이터 업데이트
                if db_file:
                    file_metadata = db_file.file_metadata or {}
                    file_metadata["task_id"] = task.id
                    db_file.file_metadata = file_metadata
            else:
                # 동기식 처리 - 메모리에서 직접 업로드
                try:
                    # BytesIO 객체로 변환하여 스트리밍 업로드
                    minio_client.put_object(
                        settings.MINIO_BUCKET_NAME,
                        unique_filename,  # 플랫 구조의 경로
                        io.BytesIO(file_content),
                        file_size,
                        content_type=content_type,
                    )
                    file_info["status"] = "completed"

                    # 파일 상태 업데이트
                    if db_file:
                        db_file.processing_status = "completed"
                except S3Error as err:
                    print(f"Error occurred during upload: {err}")
                    file_info["status"] = "failed"
                    file_info["error"] = str(err)

                    # 파일 상태 업데이트
                    if db_file:
                        db_file.processing_status = "failed"
                        file_metadata = db_file.file_metadata or {}
                        file_metadata["upload_error"] = str(err)
                        db_file.file_metadata = file_metadata

            uploaded_files.append(file_info)

        # 모든 변경사항 커밋
        if validated_document_id is not None:
            try:
                db.commit()
                print(f"파일 {len(uploaded_files)}개 업로드 정보 커밋 완료")
            except Exception as commit_error:
                db.rollback()
                print(f"커밋 오류: {str(commit_error)}")
                # 오류는 발생시키지 않고 로그만 남김 (이미 파일 업로드는 진행됨)

        return uploaded_files

    except Exception as e:
        print(f"파일 업로드 중 오류 발생: {str(e)}")
        try:
            db.rollback()
        except:
            pass  # 롤백 실패는 무시
        raise
    finally:
        db.close()


# 파일 다운로드 링크 생성 함수
def get_download_url(file_path: str, expires=3600) -> str:
    """
    MinIO에서 파일의 다운로드 URL을 생성합니다.

    Args:
        file_path: MinIO에 저장된 파일 경로
        expires: URL 만료 시간(초)

    Returns:
        다운로드 URL 또는 None (파일이 존재하지 않는 경우)
    """
    try:
        # 파일 존재 여부 확인 (타임아웃 적용)
        file_exists = False
        attempts = 0
        max_attempts = 3

        while attempts < max_attempts and not file_exists:
            attempts += 1
            try:
                # 새 MinIO 클라이언트 인스턴스 생성 (인증 문제 방지)
                temp_client = Minio(
                    settings.MINIO_ENDPOINT,
                    access_key=settings.MINIO_ACCESS_KEY,
                    secret_key=settings.MINIO_SECRET_KEY,
                    secure=settings.MINIO_SECURE,
                    region="us-east-1",  # S3 기본 리전 설정 (중요: AWS 호환성)
                )

                # 파일 존재 확인
                stat_result = temp_client.stat_object(settings.MINIO_BUCKET_NAME, file_path)

                # 파일 크기 검증
                if stat_result.size == 0:
                    print(f"Warning: 파일 크기가 0입니다 - {file_path}")
                else:
                    file_exists = True
                    print(f"파일 존재 확인: {file_path} (크기: {stat_result.size})")
            except Exception as err:
                if attempts < max_attempts:
                    print(f"파일 존재 확인 재시도 ({attempts}/{max_attempts}): {file_path}")
                    time.sleep(1)  # 재시도 전 잠시 대기
                else:
                    print(f"파일 존재 확인 실패 (최대 재시도 횟수 초과): {str(err)}")
                    return None

        if not file_exists:
            print(f"Warning: 파일이 MinIO에 존재하지 않습니다 - {file_path}")
            return None

        # URL 생성 방식 선택: Docker 환경에서는 직접 URL 생성, 그 외에는 서명된 URL 사용
        protocol = "https" if settings.MINIO_SECURE else "http"

        # Docker 환경 감지: MINIO_ENDPOINT에 "minio" 또는 도커 컨테이너 이름 포함 여부 확인
        is_docker_env = "minio" in settings.MINIO_ENDPOINT or ":" in settings.MINIO_ENDPOINT
        print(f"환경 감지: Docker={is_docker_env}, MinIO 엔드포인트={settings.MINIO_ENDPOINT}")

        if is_docker_env:
            # -------- 방법 1: 직접 API URL 생성 (Docker 환경) --------
            # URL을 직접 구성하여 문서 다운로드 API를 통해 처리
            # 이 방식은 서명 검증을 우회하고 백엔드 API를 통한 검증을 사용합니다
            file_uuid = os.path.basename(file_path)  # 파일 경로에서 UUID.확장자 추출

            # 현재 서버의 기본 URL 추출 (settings에서 설정 가능)
            base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")

            # 문서 ID는 로그에 기록되므로 없는 경우 사용
            document_id = "direct-download"

            # 참고: 직접 사용할 수 있는 API가 아니라, 백엔드를 통한 API를 사용합니다
            # /api/download/{file_uuid} 형태의 API가 있는 경우 이를 사용
            # 없는 경우 문서별 다운로드 API를 사용해야 합니다
            download_url = f"{base_url}/api/download/{file_uuid}?expires={expires}"

            print(f"직접 다운로드 URL 생성: {download_url}")
            return download_url
        else:
            # -------- 방법 2: 서명된 URL 생성 (비 Docker 환경) --------
            try:
                # 정수 초를 timedelta 객체로 변환
                expires_delta = timedelta(seconds=expires)

                # URL 생성용 새 MinIO 클라이언트 생성
                url_client = Minio(
                    settings.MINIO_ENDPOINT,
                    access_key=settings.MINIO_ACCESS_KEY,
                    secret_key=settings.MINIO_SECRET_KEY,
                    secure=settings.MINIO_SECURE,
                    region="us-east-1",  # S3 기본 리전 설정 (중요: AWS 호환성)
                )

                # 서명된 URL 생성
                signed_url = url_client.presigned_get_object(
                    settings.MINIO_BUCKET_NAME, file_path, expires=expires_delta
                )

                print(f"서명된 URL 생성: {signed_url}")

                # URL에 'localhost'가 포함된 경우 MINIO_EXTERNAL_ENDPOINT로 변환
                if "localhost" in signed_url or "127.0.0.1" in signed_url:
                    parsed_url = urllib.parse.urlparse(signed_url)
                    query = parsed_url.query

                    # 새 URL 생성 (localhost를 외부 엔드포인트로 변경)
                    external_hostname = MINIO_EXTERNAL_ENDPOINT
                    external_url = f"{protocol}://{external_hostname}/{settings.MINIO_BUCKET_NAME}/{urllib.parse.quote(file_path)}?{query}"

                    print(f"변환된 URL: {external_url}")
                    return external_url

                return signed_url
            except Exception as url_err:
                print(f"서명된 URL 생성 실패: {str(url_err)}")
                return None

    except Exception as err:
        print(f"MinIO URL 생성 오류: {str(err)}")
        return None


# 다중 파일 다운로드 링크 생성 함수
def get_multiple_download_urls(file_path: List[str], expires=3600) -> List[Dict[str, str]]:
    download_urls = []

    # 정수 초를 timedelta 객체로 변환
    expires_delta = timedelta(seconds=expires)

    for path in file_path:
        try:
            url = minio_client.presigned_get_object(settings.MINIO_BUCKET_NAME, path, expires=expires_delta)

            # 내부 URL을 외부 URL로 변환
            external_url = convert_internal_url_to_external(url)

            # 원본 파일명을 파일 경로에서 추출 (저장된 메타데이터에서 얻을 수도 있음)
            file_name = os.path.basename(path)
            download_urls.append({"path": path, "url": external_url, "filename": file_name})
        except S3Error as err:
            print(f"Error occurred: {err}")
            # 개별 파일 오류는 건너뛰기
            continue

    return download_urls


# 파일 스트리밍 함수 - 큰 파일 지원
def get_file_stream(file_path: str) -> Tuple[BinaryIO, int, str]:
    """
    MinIO에서 파일을 스트리밍하기 위한 함수 - 대용량 파일 지원 버전

    Args:
        file_path: MinIO에 저장된 파일 경로

    Returns:
        (file_stream, file_size, content_type): 파일 스트림, 파일 크기, 컨텐츠 타입
    """
    attempts = 0
    max_attempts = 3
    last_error = None

    while attempts < max_attempts:
        attempts += 1
        try:
            # 스트리밍 전용 클라이언트 생성 (인증 문제 방지)
            stream_client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
                region="us-east-1",  # S3 호환성 개선
            )

            # 파일 정보 조회
            stat = stream_client.stat_object(settings.MINIO_BUCKET_NAME, file_path)
            file_size = stat.size
            content_type = stat.content_type or "application/octet-stream"

            # 파일 크기가 0이면 문제 있음
            if file_size == 0:
                print(f"Warning: 파일 크기가 0입니다 - {file_path}")
                if attempts < max_attempts:
                    time.sleep(1)
                    continue

            # 파일 스트림 생성 (버퍼 크기 지정)
            # response_content_type 파라미터 추가로 타입 제어
            data = stream_client.get_object(
                settings.MINIO_BUCKET_NAME,
                file_path,
                request_headers={"Accept-Encoding": "identity"},  # 압축 해제 방지
            )

            # 청크 기반 스트리밍을 위한 제너레이터 함수
            def generate_chunks():
                buffer_size = 4 * 1024 * 1024  # 4MB 버퍼 크기
                try:
                    # 청크 단위로 파일 데이터 스트리밍
                    chunk = data.read(buffer_size)
                    while chunk:
                        yield chunk
                        chunk = data.read(buffer_size)
                except Exception as e:
                    print(f"청크 스트리밍 오류: {str(e)}")
                finally:
                    # 스트림 종료 후 리소스 정리
                    try:
                        data.close()
                        data.release_conn()
                    except:
                        pass

            print(f"파일 스트림 생성 성공 (청크 방식): {file_path} (크기: {file_size}, 타입: {content_type})")

            # 제너레이터 객체와 메타데이터 반환
            return generate_chunks(), file_size, content_type

        except Exception as err:
            last_error = err
            print(f"스트리밍 오류 (시도 {attempts}/{max_attempts}): {str(err)}")

            if "NoSuchKey" in str(err):
                # 파일이 없는 경우 더 이상 시도하지 않음
                break

            if attempts < max_attempts:
                time.sleep(1)  # 재시도 전 잠시 대기

    # 모든 시도 실패
    print(f"파일 스트리밍 최대 재시도 횟수 초과: {file_path}")
    raise last_error or Exception(f"파일 스트리밍 실패: {file_path}")


# 파일 삭제 함수
def delete_file(file_path: str) -> bool:
    try:
        minio_client.remove_object(settings.MINIO_BUCKET_NAME, file_path)
        return True
    except S3Error as err:
        print(f"Error occurred: {err}")
        return False


# 다중 파일 삭제 함수
def delete_multiple_files(file_path: List[str]) -> Tuple[bool, List[str]]:
    successful_deletes = []
    failed_deletes = []

    for path in file_path:
        try:
            minio_client.remove_object(settings.MINIO_BUCKET_NAME, path)
            successful_deletes.append(path)
        except S3Error as err:
            print(f"Error occurred when deleting {path}: {err}")
            failed_deletes.append(path)

    return len(failed_deletes) == 0, failed_deletes


# 파일 존재 여부 확인하는 강화된 함수
def check_file_exists(file_path: str, max_attempts: int = 3) -> bool:
    """
    MinIO에 파일이 존재하는지 확인하는 강화된 함수

    Args:
        file_path: MinIO에 저장된 파일 경로
        max_attempts: 최대 시도 횟수

    Returns:
        True: 파일이 존재함
        False: 파일이 존재하지 않음
    """
    for attempt in range(max_attempts):
        try:
            # MinIO 클라이언트 재설정 (인증 문제 방지)
            global minio_client
            minio_client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )

            # 파일 존재 확인
            stat_result = minio_client.stat_object(settings.MINIO_BUCKET_NAME, file_path)

            # 파일 크기 검증
            if stat_result.size == 0:
                print(f"Warning: 파일이 존재하지만 크기가 0입니다 - {file_path}")
                if attempt < max_attempts - 1:
                    time.sleep(1)  # 다음 시도 전 대기
                    continue
                return False

            print(f"파일이 존재합니다: {file_path} (크기: {stat_result.size}, 타입: {stat_result.content_type})")
            return True

        except Exception as err:
            if "NoSuchKey" in str(err):
                # 파일이 없는 경우 추가 시도 불필요
                print(f"파일이 존재하지 않음: {file_path}")
                return False

            print(f"MinIO 파일 존재 확인 재시도 ({attempt+1}/{max_attempts}): {str(err)}")
            if attempt < max_attempts - 1:
                time.sleep(1)  # 다음 시도 전 대기

    print(f"MinIO 파일 존재 확인 최대 재시도 횟수 초과: {file_path}")
    return False


# 여러 파일의 존재 여부 일괄 확인 함수
def check_multiple_files_exist(file_paths: List[str]) -> Dict[str, bool]:
    """
    여러 파일의 존재 여부를 일괄 확인하는 함수

    Args:
        file_paths: MinIO에 저장된 파일 경로 리스트

    Returns:
        {파일경로: 존재여부} 형태의 딕셔너리
    """
    results = {}
    for path in file_paths:
        results[path] = check_file_exists(path)
    return results
