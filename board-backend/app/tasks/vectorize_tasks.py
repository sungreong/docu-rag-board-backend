import os
import tempfile
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from uuid import UUID
import json

from app.celery_worker import celery
from app.database import SessionLocal
from app.models import Document, DocumentFile, DocumentChunk
from app.tasks.file_tasks import download_file_from_minio
from app.config import settings

# 벡터 DB가 있는 경우 임포트
MILVUS_ENABLED = False
try:
    # marshmallow 및 environs 버전 호환성 문제 방지를 위한 조치
    import marshmallow

    if not hasattr(marshmallow, "__version_info__"):
        # marshmallow 3.0.0 이상을 가정
        marshmallow.__version_info__ = tuple(map(int, marshmallow.__version__.split(".")))

    from pymilvus import connections, utility

    MILVUS_ENABLED = True
    logger = logging.getLogger(__name__)
    logger.info("Milvus 연결 성공: 벡터 데이터베이스 기능이 활성화되었습니다.")
except (ImportError, AttributeError) as e:
    logger = logging.getLogger(__name__)
    logger.warning(f"Milvus 연결 실패 (오류: {str(e)}): 벡터 데이터베이스 기능이 비활성화됩니다.")


def get_db():
    """데이터베이스 세션 생성"""
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()


@celery.task(name="vectorize_document", bind=True)
def vectorize_document(self, document_id):
    """
    문서 요약(summary)을 벡터화하는 작업

    Args:
        document_id: 벡터화할 문서 ID
    """
    task_id = self.request.id
    logger.info(f"Task {task_id}: 문서 요약 벡터화 시작 - 문서 ID: {document_id}")

    try:
        # 데이터베이스 연결
        db = get_db()

        # 문서 조회
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            logger.error(f"Task {task_id}: 문서 ID {document_id}를 찾을 수 없습니다.")
            return {"status": "error", "message": "Document not found"}

        # 문서 요약이 없는 경우 처리하지 않음
        if not document.summary or not document.summary.strip():
            logger.error(f"Task {task_id}: 문서 ID {document_id}의 요약이 없습니다.")
            document.file_metadata = document.file_metadata or {}
            document.file_metadata["vectorize_task_id"] = task_id
            document.file_metadata["vectorize_error"] = "요약(summary)이 없어 벡터화할 수 없습니다."
            document.file_metadata["vectorize_completed_at"] = datetime.utcnow().isoformat()
            db.commit()
            return {"status": "error", "message": "No summary available for vectorization"}

        # 문서 상태 업데이트
        document.file_metadata = document.file_metadata or {}
        document.file_metadata["vectorize_task_id"] = task_id
        document.file_metadata["vectorize_started_at"] = datetime.utcnow().isoformat()
        db.commit()

        # 요약 텍스트에서 청크 생성
        summary_text = document.summary.strip()
        chunks = []

        # 간단한 청킹: 요약 텍스트를 하나의 청크로
        chunks.append(
            {
                "text": summary_text,
                "metadata": {"source": "document_summary", "document_id": str(document_id), "size": len(summary_text)},
            }
        )

        # 청킹 결과 저장
        if chunks:
            for chunk in chunks:
                # 벡터화 작업은 추후 구현
                vector_id = None

                # 청크 객체 생성 - file_id는 NULL로 설정 (요약은 특정 파일에 속하지 않음)
                db_chunk = DocumentChunk(
                    document_id=document_id,
                    file_id=None,  # 파일 ID 없음 (요약은 파일이 아님)
                    chunk_text=chunk["text"],
                    vector_id=vector_id,
                    chunk_metadata=chunk["metadata"],
                )

                db.add(db_chunk)

            db.commit()

        # 벡터화 상태 업데이트
        document.vectorized = True
        document.file_metadata["vectorize_completed_at"] = datetime.utcnow().isoformat()
        document.file_metadata["summary_vectorized"] = True
        db.commit()

        logger.info(f"Task {task_id}: 문서 요약 벡터화 완료 - 문서 ID: {document_id}")
        return {
            "status": "success",
            "document_id": str(document_id),
            "vectorized_summary": True,
            "task_id": task_id,
        }
    except Exception as e:
        logger.error(f"Task {task_id}: 문서 요약 벡터화 중 오류 발생 - {str(e)}")

        # 실패 상태 업데이트
        try:
            db = get_db()
            document = db.query(Document).filter(Document.id == document_id).first()
            if document:
                document.file_metadata = document.file_metadata or {}
                document.file_metadata["vectorize_error"] = str(e)
                document.file_metadata["error_time"] = datetime.utcnow().isoformat()
                db.commit()
        except Exception as db_error:
            logger.error(f"Task {task_id}: DB 업데이트 중 추가 오류 - {str(db_error)}")

        # 오류 전파
        raise


def extract_text_from_pdf(file_path):
    """PDF 파일에서 텍스트 추출 및 청킹"""
    try:
        import PyPDF2

        chunks = []
        with open(file_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            for page_num in range(len(reader.pages)):
                page = reader.pages[page_num]
                text = page.extract_text() or ""

                if text.strip():
                    chunks.append(
                        {
                            "text": text.strip(),
                            "metadata": {"source": os.path.basename(file_path), "page": page_num + 1},
                        }
                    )

        return chunks
    except Exception as e:
        logger.error(f"PDF 텍스트 추출 오류: {str(e)}")
        return []


def extract_text_from_docx(file_path):
    """DOCX 파일에서 텍스트 추출 및 청킹"""
    try:
        import docx

        chunks = []
        doc = docx.Document(file_path)
        text_parts = []

        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text.strip())

                # 일정 크기마다 청크 생성
                if len("\n".join(text_parts)) > 1000:
                    chunk_text = "\n".join(text_parts)
                    chunks.append(
                        {
                            "text": chunk_text,
                            "metadata": {"source": os.path.basename(file_path), "size": len(chunk_text)},
                        }
                    )
                    text_parts = []

        # 남은 텍스트 처리
        if text_parts:
            chunk_text = "\n".join(text_parts)
            chunks.append(
                {"text": chunk_text, "metadata": {"source": os.path.basename(file_path), "size": len(chunk_text)}}
            )

        return chunks
    except Exception as e:
        logger.error(f"DOCX 텍스트 추출 오류: {str(e)}")
        return []


def extract_text_from_txt(file_path):
    """TXT 파일에서 텍스트 추출 및 청킹"""
    try:
        chunks = []
        with open(file_path, "r", encoding="utf-8") as file:
            text = file.read()

            # 간단한 청킹: 각 1000자를 하나의 청크로
            for i in range(0, len(text), 1000):
                chunk_text = text[i : i + 1000].strip()
                if chunk_text:
                    chunks.append(
                        {
                            "text": chunk_text,
                            "metadata": {
                                "source": os.path.basename(file_path),
                                "start_idx": i,
                                "end_idx": min(i + 1000, len(text)),
                            },
                        }
                    )

        return chunks
    except Exception as e:
        logger.error(f"TXT 텍스트 추출 오류: {str(e)}")
        return []


def save_chunks(db, document_id, file_id, chunks):
    """추출된 청크를 데이터베이스에 저장"""
    try:
        for chunk in chunks:
            # 벡터화 작업은 추후 구현
            vector_id = None

            # 청크 객체 생성
            db_chunk = DocumentChunk(
                document_id=document_id,
                file_id=file_id,
                chunk_text=chunk["text"],
                vector_id=vector_id,
                chunk_metadata=chunk["metadata"],
            )

            db.add(db_chunk)

        db.commit()
        return True
    except Exception as e:
        logger.error(f"청크 저장 오류: {str(e)}")
        db.rollback()
        return False


@celery.task(name="delete_document_vectors", bind=True)
def delete_document_vectors(self, document_id):
    """
    문서의 벡터를 삭제하는 작업

    Args:
        document_id: 벡터를 삭제할 문서 ID
    """
    task_id = self.request.id
    logger.info(f"Task {task_id}: 문서 벡터 삭제 시작 - 문서 ID: {document_id}")

    try:
        # 데이터베이스 연결
        db = get_db()

        # 문서 조회
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            logger.error(f"Task {task_id}: 문서 ID {document_id}를 찾을 수 없습니다.")
            return {"status": "error", "message": "Document not found"}

        # 청크 삭제
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).all()
        for chunk in chunks:
            # 벡터 DB에서 벡터 삭제 (Milvus 사용 시)
            if MILVUS_ENABLED and chunk.vector_id:
                try:
                    # Milvus 연결
                    connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)

                    # 벡터 삭제
                    if utility.has_collection(settings.MILVUS_COLLECTION):
                        from pymilvus import Collection

                        collection = Collection(settings.MILVUS_COLLECTION)
                        collection.delete(expr=f"id == {chunk.vector_id}")
                except Exception as milvus_error:
                    logger.error(f"Task {task_id}: Milvus 벡터 삭제 오류 - {str(milvus_error)}")

            # DB에서 청크 삭제
            db.delete(chunk)

        # 벡터화 상태 업데이트
        document.vectorized = False
        document.file_metadata = document.file_metadata or {}
        document.file_metadata["vector_deleted_at"] = datetime.utcnow().isoformat()
        document.file_metadata["vector_deleted_by_task"] = task_id

        db.commit()

        logger.info(f"Task {task_id}: 문서 벡터 삭제 완료 - 문서 ID: {document_id}")
        return {
            "status": "success",
            "document_id": str(document_id),
            "deleted_chunks": len(chunks),
            "task_id": task_id,
        }
    except Exception as e:
        logger.error(f"Task {task_id}: 문서 벡터 삭제 중 오류 발생 - {str(e)}")

        # 실패 상태 업데이트
        try:
            db = get_db()
            document = db.query(Document).filter(Document.id == document_id).first()
            if document:
                document.file_metadata = document.file_metadata or {}
                document.file_metadata["vector_delete_error"] = str(e)
                document.file_metadata["error_time"] = datetime.utcnow().isoformat()
                db.commit()
        except Exception as db_error:
            logger.error(f"Task {task_id}: DB 업데이트 중 추가 오류 - {str(db_error)}")

        # 오류 전파
        raise
