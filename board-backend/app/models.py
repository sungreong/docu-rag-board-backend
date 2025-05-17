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
    # 태그 관계 추가
    user_tags = relationship("UserTag", back_populates="user", cascade="all, delete-orphan")
    tag_quota = relationship(
        "UserTagQuota",
        back_populates="user",
        foreign_keys="UserTagQuota.user_id",
        uselist=False,
        cascade="all, delete-orphan",
    )


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

    # 추가 필드
    vectorize_requested = Column(Boolean, default=False)  # 벡터화 요청 상태
    vectorize_requested_at = Column(DateTime, nullable=True)  # 벡터화 요청 일시
    vectorize_requested_by = Column(UUID(as_uuid=True), nullable=True)  # 벡터화 요청한 사용자

    vector_delete_requested = Column(Boolean, default=False)  # 벡터 삭제 요청 상태
    vector_delete_requested_at = Column(DateTime, nullable=True)  # 벡터 삭제 요청 일시
    vector_delete_requested_by = Column(UUID(as_uuid=True), nullable=True)  # 벡터 삭제 요청한 사용자

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


# 태그 관련 모델 추가
class Tag(Base):
    """시스템에서 관리하는 전체 태그 목록"""

    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(String, nullable=True)
    is_system = Column(Boolean, default=False)  # 시스템 제공 태그 여부
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # 태그 생성자 (관리자)

    # 사용자 태그와의 관계
    user_tags = relationship("UserTag", back_populates="tag", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_tag_name", name),  # 태그 이름으로 검색 가속
        Index("idx_tag_system", is_system),  # 시스템 태그 필터링 가속
    )

    def __repr__(self):
        return f"<Tag(id={self.id}, name='{self.name}', is_system={self.is_system})>"


class UserTag(Base):
    """사용자별 개인 태그 관계 모델"""

    __tablename__ = "user_tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계 설정
    user = relationship("User", back_populates="user_tags")
    tag = relationship("Tag", back_populates="user_tags")

    __table_args__ = (
        Index("idx_user_tag_user", user_id),  # 사용자별 태그 검색 가속
        Index("idx_user_tag_combined", user_id, tag_id, unique=True),  # 사용자-태그 조합 유일성 보장
    )

    def __repr__(self):
        return f"<UserTag(user_id={self.user_id}, tag_id={self.tag_id})>"


class UserTagQuota(Base):
    """사용자별 태그 할당량 모델"""

    __tablename__ = "user_tag_quotas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    max_tags = Column(Integer, default=20)  # 기본 최대 20개 태그 할당
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # 관계 설정
    user = relationship("User", back_populates="tag_quota", foreign_keys=[user_id])
    updated_by_user = relationship("User", foreign_keys=[updated_by])  # 이름 변경 및 back_populates 제거

    def __repr__(self):
        return f"<UserTagQuota(user_id={self.user_id}, max_tags={self.max_tags})>"


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
