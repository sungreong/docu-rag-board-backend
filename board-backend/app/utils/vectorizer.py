import os
import uuid
import tempfile
from datetime import datetime
from typing import List, Dict, Any
import requests
import pypdf
from docx import Document as DocxDocument
from sqlalchemy.orm import Session

from app.models import Document, DocumentFile, DocumentChunk
from app.storage import get_download_url


def extract_text_from_file(file_path: str, file_type: str) -> str:
    """파일에서 텍스트를 추출하는 함수"""
    try:
        # MinIO에서 파일 다운로드
        download_url = get_download_url(file_path)

        # 임시 파일 생성
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file_path = temp_file.name

        # 파일 다운로드
        response = requests.get(download_url)
        with open(temp_file_path, "wb") as f:
            f.write(response.content)

        # 파일 타입별 텍스트 추출
        text = ""
        if file_type.lower() == "pdf":
            with open(temp_file_path, "rb") as f:
                pdf_reader = pypdf.PdfReader(f)
                for page_num in range(len(pdf_reader.pages)):
                    page_text = pdf_reader.pages[page_num].extract_text() or ""
                    text += page_text + "\n\n"  # 페이지 간 분리를 위해 두 개의 줄바꿈 추가

        elif file_type.lower() == "docx":
            doc = DocxDocument(temp_file_path)
            for para in doc.paragraphs:
                if para.text:
                    text += para.text + "\n"

        elif file_type.lower() == "txt":
            with open(temp_file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()

        else:
            raise ValueError(f"Unsupported file type: {file_type}")

        return text

    except Exception as e:
        raise Exception(f"텍스트 추출 오류: {str(e)}")

    finally:
        # 임시 파일 삭제
        if "temp_file_path" in locals() and os.path.exists(temp_file_path):
            os.remove(temp_file_path)


def create_chunks(text: str, chunk_size: int = 512, overlap: int = 50) -> List[str]:
    """텍스트를 청크로 분할하는 함수

    Args:
        text: 분할할 텍스트
        chunk_size: 각 청크의 최대 토큰 수 (기본값: 512)
        overlap: 청크 간 중복되는 토큰 수 (기본값: 50)

    Returns:
        문자열 청크 리스트
    """
    # 간단한 토큰화 (공백 기준)
    tokens = text.split()

    if not tokens:
        return []

    chunks = []
    i = 0

    while i < len(tokens):
        # 현재 청크의 끝 인덱스 계산
        end = min(i + chunk_size, len(tokens))

        # 청크 생성
        chunk = " ".join(tokens[i:end])
        chunks.append(chunk)

        # 다음 시작 위치로 이동 (오버랩 고려)
        i += chunk_size - overlap

        # 마지막 토큰에 도달했으면 종료
        if i >= len(tokens):
            break

    return chunks


def chunk_document(document: Document, file: DocumentFile, db: Session) -> List[DocumentChunk]:
    """문서를 청크로 분할하고 데이터베이스에 저장

    Args:
        document: 문서 모델 객체
        file: 문서 파일 모델 객체
        db: 데이터베이스 세션

    Returns:
        생성된 DocumentChunk 객체 리스트
    """
    # 파일에서 텍스트 추출
    file_text = extract_text_from_file(file.file_path, file.file_type)

    # 텍스트 청크로 분할
    text_chunks = create_chunks(file_text)

    if not text_chunks:
        return []

    # 청크를 데이터베이스에 저장
    db_chunks = []

    for i, chunk_text in enumerate(text_chunks):
        # 청크 메타데이터 생성
        chunk_metadata = {
            "file_id": str(file.id),
            "file_name": file.original_filename,
            "file_type": file.file_type,
            "chunk_index": i,
            "total_chunks": len(text_chunks),
            "document_title": document.title,
            "document_tags": document.tags,
            "created_at": datetime.utcnow().isoformat(),
            "document_created_at": document.created_at.isoformat() if document.created_at else None,
            "document_start_date": document.start_date.isoformat() if document.start_date else None,
            "document_end_date": document.end_date.isoformat() if document.end_date else None,
        }

        # 벡터 ID 생성 (실제 임베딩은 나중에 구현)
        vector_id = str(uuid.uuid4())

        # 청크 객체 생성
        db_chunk = DocumentChunk(
            document_id=document.id,
            file_id=file.id,
            chunk_text=chunk_text,
            chunk_index=i,
            vector_id=vector_id,
            embedding_model="placeholder",  # 실제 모델 정보로 대체 예정
            embedding_version="0.1",  # 실제 버전 정보로 대체 예정
            chunk_metadata=chunk_metadata,
        )

        db.add(db_chunk)
        db_chunks.append(db_chunk)

    # 변경사항 커밋은 호출자가 수행
    return db_chunks


def simple_chunk_document(document: Document, db: Session) -> List[DocumentChunk]:
    """문서의 요약(summary)만 청크로 분할하고 데이터베이스에 저장

    Args:
        document: 문서 모델 객체
        db: 데이터베이스 세션

    Returns:
        생성된 DocumentChunk 객체 리스트
    """
    # 문서에 요약이 없으면 빈 리스트 반환
    if not document.summary:
        return []

    # 요약 텍스트 청크로 분할
    text_chunks = create_chunks(document.summary)

    if not text_chunks:
        return []

    # 청크를 데이터베이스에 저장
    db_chunks = []

    for i, chunk_text in enumerate(text_chunks):
        # 청크 메타데이터 생성
        chunk_metadata = {
            "chunk_index": i,
            "total_chunks": len(text_chunks),
            "document_title": document.title,
            "document_tags": document.tags,
            "created_at": datetime.utcnow().isoformat(),
            "document_created_at": document.created_at.isoformat() if document.created_at else None,
            "document_start_date": document.start_date.isoformat() if document.start_date else None,
            "document_end_date": document.end_date.isoformat() if document.end_date else None,
            "is_summary": True,
        }

        # 벡터 ID 생성 (실제 임베딩은 나중에 구현)
        vector_id = str(uuid.uuid4())

        # 청크 객체 생성
        db_chunk = DocumentChunk(
            document_id=document.id,
            chunk_text=chunk_text,
            chunk_index=i,
            vector_id=vector_id,
            embedding_model="placeholder",  # 실제 모델 정보로 대체 예정
            embedding_version="0.1",  # 실제 버전 정보로 대체 예정
            chunk_metadata=chunk_metadata,
        )

        db.add(db_chunk)
        db_chunks.append(db_chunk)

    # 변경사항 커밋은 호출자가 수행
    return db_chunks
