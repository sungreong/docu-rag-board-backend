import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Boolean, Text, ARRAY, JSON, Index, Float, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, index=True)
    name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    hashed_password = Column(String)
    role = Column(String, default="user")  # user, admin
    is_active = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=False)  # 관리자 승인 필요
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계 설정
    documents = relationship("Document", back_populates="user")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False, index=True)
    summary = Column(Text, nullable=True)
    tags = Column(ARRAY(String), nullable=True)
    status = Column(String, default="승인대기")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    view_count = Column(Integer, default=0)
    download_count = Column(Integer, default=0)
    vectorized = Column(Boolean, default=False)
    file_metadata = Column(JSONB, nullable=True)
    is_public = Column(Boolean, default=False)  # 전체 공유 여부 (True: 공개, False: 비공개)

    # 사용자와의 관계
    user = relationship("User", back_populates="documents")

    # 문서 파일과의 관계
    files = relationship("DocumentFile", back_populates="document", cascade="all, delete-orphan")

    # 청크와의 관계 추가
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Document(id={self.id}, title='{self.title}', status='{self.status}')>"

    # 인덱스 생성
    __table_args__ = (
        Index("idx_document_status", status),  # 상태별 필터링 가속
        Index("idx_document_created_at", created_at),  # 생성일 기준 정렬 가속
        Index("idx_document_tags", tags, postgresql_using="gin"),  # 태그 검색 가속 (GIN 인덱스)
        Index("idx_document_user_status", user_id, status),  # 사용자별 상태 필터링 가속
        Index("idx_document_dates", start_date, end_date),  # 날짜 범위 검색 가속
        Index("idx_document_public", is_public),  # 공개 문서 필터링 가속
    )


class DocumentFile(Base):
    """문서와 파일 간의 관계를 관리하는 모델"""

    __tablename__ = "document_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_path = Column(String, nullable=False)  # MinIO 내 파일 경로
    original_filename = Column(String, nullable=False)  # 원본 파일명
    file_type = Column(String, nullable=False)  # 파일 유형
    file_size = Column(Integer, default=0)  # 파일 크기 (바이트)
    content_type = Column(String, nullable=True)  # 파일 MIME 타입
    created_at = Column(DateTime, default=datetime.utcnow)

    # 추가 메타데이터 (페이지 수, 해시값 등)
    file_metadata = Column(JSONB, default={})

    # 처리 상태 (processed, processing, error)
    processing_status = Column(String, default="pending")
    error_message = Column(String, nullable=True)

    # 외래 키
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"))

    # 관계 설정
    document = relationship("Document", back_populates="files")

    # 인덱스 생성
    __table_args__ = (
        Index("idx_document_file_doc_id", document_id),  # 문서 ID로 파일 조회 가속
        Index("idx_document_file_type", file_type),  # 파일 타입별 필터링 가속
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_text = Column(Text)
    chunk_index = Column(Integer)
    vector_id = Column(String)  # Milvus 벡터 ID
    chunk_metadata = Column(JSONB, default={})  # 추가 메타데이터 (페이지 번호, 색인 정보 등)
    created_at = Column(DateTime, default=datetime.utcnow)
    file_id = Column(UUID(as_uuid=True), ForeignKey("document_files.id"), nullable=True)  # 특정 파일과 연결
    embedding_model = Column(String, nullable=True)  # 임베딩 모델 정보
    embedding_version = Column(String, nullable=True)  # 임베딩 모델 버전

    # 외래 키
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"))

    # 관계 설정
    document = relationship("Document", back_populates="chunks")
    file = relationship("DocumentFile", backref="chunks", foreign_keys=[file_id])

    # 인덱스 생성
    __table_args__ = (
        Index("idx_chunk_document_id", document_id),  # 문서별 청크 검색 가속
        Index("idx_chunk_file_id", file_id),  # 파일별 청크 검색 가속
    )
