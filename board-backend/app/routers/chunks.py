from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
import os
import uuid
import pypdf
from docx import Document as DocxDocument
from typing import List

from app.database import get_db
from app.auth import get_current_admin_user
from app.schemas import ChunkCreate
from app.models import Document, DocumentChunk, User
from app.storage import get_download_url
from app.config import settings

router = APIRouter(prefix="/chunks", tags=["chunks"])

# 기본 청크 사이즈 (문자 수)
DEFAULT_CHUNK_SIZE = 1000


# 문서 청킹 유틸리티 함수
def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[str]:
    """텍스트를 청크로 분할하는 함수"""
    chunks = []

    # 청크 사이즈 단위로 분할
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        # 문장 단위로 분할되도록 조정
        if i + chunk_size < len(text) and text[i + chunk_size] not in [".", "!", "?", "\n"]:
            # 문장 끝 찾기
            end_pos = chunk.rfind(".")
            if end_pos == -1:
                end_pos = chunk.rfind("!")
            if end_pos == -1:
                end_pos = chunk.rfind("?")
            if end_pos == -1:
                end_pos = chunk.rfind("\n")

            if end_pos != -1 and end_pos > chunk_size // 2:
                chunk = chunk[: end_pos + 1]

        chunks.append(chunk)

    return chunks


# 문서에서 텍스트 추출 함수
async def extract_text(file_path: str, file_type: str) -> str:
    """문서 파일에서 텍스트를 추출하는 함수"""
    # MinIO에서 파일 다운로드
    download_url = get_download_url(file_path)

    # 임시 파일로 저장
    temp_file_path = f"/tmp/{uuid.uuid4()}.{file_type}"

    try:
        # 파일 다운로드 (간단한 구현, 실제로는 더 복잡할 수 있음)
        import requests

        response = requests.get(download_url)
        with open(temp_file_path, "wb") as f:
            f.write(response.content)

        # 파일 타입에 따라 텍스트 추출
        if file_type == "pdf":
            text = ""
            with open(temp_file_path, "rb") as f:
                pdf_reader = pypdf.PdfReader(f)
                for page_num in range(len(pdf_reader.pages)):
                    text += pdf_reader.pages[page_num].extract_text() + "\n"
            return text

        elif file_type == "docx":
            doc = DocxDocument(temp_file_path)
            text = ""
            for para in doc.paragraphs:
                text += para.text + "\n"
            return text

        elif file_type == "txt":
            with open(temp_file_path, "r", encoding="utf-8") as f:
                return f.read()

        else:
            return ""

    finally:
        # 임시 파일 삭제
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


# Milvus 벡터 저장 함수 (실제 구현은 향후 개발)
def store_vectors(chunks: List[str], document_id: str) -> List[str]:
    """텍스트 청크를 벡터로 변환하여 Milvus에 저장하는 함수"""
    # 실제 Milvus 연동은 향후 구현
    # 지금은 임시 벡터 ID 반환
    vector_ids = [str(uuid.uuid4()) for _ in chunks]
    return vector_ids


# 문서 청킹 API
@router.post("/{document_id}", status_code=status.HTTP_201_CREATED)
async def create_chunks(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)
):
    # 문서 존재 확인
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # 이미 청킹된 문서인지 확인
    existing_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).count()
    if existing_chunks > 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document already chunked")

    # 문서에서 텍스트 추출
    text = await extract_text(document.file_path, document.file_type)

    # 텍스트 청킹
    text_chunks = chunk_text(text)

    # Milvus에 벡터 저장 (향후 실제 구현)
    vector_ids = store_vectors(text_chunks, str(document_id))

    # 청크를 데이터베이스에 저장
    db_chunks = []
    for i, (chunk_text, vector_id) in enumerate(zip(text_chunks, vector_ids)):
        db_chunk = DocumentChunk(
            document_id=document_id,
            chunk_text=chunk_text,
            chunk_index=i,
            vector_id=vector_id,
            chunk_metadata={"page": i // 5},  # 임시로 청크 5개당 1페이지로 가정
        )
        db.add(db_chunk)
        db_chunks.append(db_chunk)

    db.commit()

    return {"message": f"Created {len(db_chunks)} chunks for document {document_id}"}


# 문서의 청크 목록 조회 API
@router.get("/{document_id}")
def get_document_chunks(
    document_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    # 문서 존재 확인
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # 문서의 청크 조회
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {"chunks": chunks, "total": len(chunks)}
