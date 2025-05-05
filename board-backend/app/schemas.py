from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from uuid import UUID


# 기본 사용자 스키마
class UserBase(BaseModel):
    email: EmailStr
    role: Optional[str] = "user"
    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    is_approved: Optional[bool] = None


# 응답용 사용자 스키마
class User(UserBase):
    id: UUID
    is_active: bool
    is_approved: bool
    created_at: datetime

    class Config:
        orm_mode = True


# 토큰 스키마
class Token(BaseModel):
    access_token: str
    token_type: str
    user: User


class TokenData(BaseModel):
    user_id: Optional[str] = None


# 지원되는 파일 형식 스키마
class SupportedFileType(BaseModel):
    extension: str
    description: str
    max_size_mb: int


class SupportedFileTypes(BaseModel):
    file_types: List[SupportedFileType]


# 문서 파일 스키마
class DocumentFileBase(BaseModel):
    file_path: str
    original_filename: str
    file_type: str
    file_size: int
    content_type: Optional[str] = None
    processing_status: str = "pending"


class DocumentFile(DocumentFileBase):
    id: UUID
    document_id: UUID
    created_at: datetime
    file_metadata: Dict = {}

    class Config:
        orm_mode = True


# 기본 문서 스키마
class DocumentBase(BaseModel):
    title: str
    summary: Optional[str] = None
    tags: Optional[List[str]] = []
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_public: Optional[bool] = False


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_public: Optional[bool] = None


# 응답용 문서 스키마
class Document(DocumentBase):
    id: UUID
    status: str
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    view_count: int
    download_count: int
    vectorized: bool
    file_metadata: Optional[Dict[str, Any]] = None
    file_names: Optional[List[str]] = None
    file_paths: Optional[List[str]] = None
    file_types: Optional[List[str]] = None

    class Config:
        orm_mode = True


# 상세 문서 스키마 (청크 정보 포함)
class DocumentDetail(Document):
    user: Optional[User] = None
    files: List[DocumentFile] = []

    class Config:
        orm_mode = True


# 문서 상태 업데이트 스키마
class DocumentStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None


# 검색 결과 스키마
class SearchResult(BaseModel):
    document: Document
    relevance_score: Optional[float] = None
    highlights: Optional[List[str]] = None

    class Config:
        orm_mode = True


# 청크 생성 요청 스키마
class ChunkCreate(BaseModel):
    document_id: UUID


# 파일 스키마
class FileInfo(BaseModel):
    id: UUID
    original_filename: str
    file_path: str
    file_type: str
    file_size: int
    content_type: Optional[str] = None
    created_at: datetime
    file_metadata: Optional[Dict[str, Any]] = {}
    processing_status: str

    class Config:
        orm_mode = True


# 검색 관련 스키마
class SearchQuery(BaseModel):
    query: str
    filters: Optional[Dict[str, Any]] = None
    limit: Optional[int] = 10
