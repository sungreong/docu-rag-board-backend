import os
import json
from typing import List, Optional, Dict
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, Body, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, desc, asc, func
from uuid import UUID
import logging
from fastapi.responses import StreamingResponse, RedirectResponse
from pydantic import BaseModel
import uuid
import urllib.parse

from app.database import get_db
from app.auth import get_current_active_user, get_current_admin_user
from app.storage import upload_multiple_files, get_multiple_download_urls, delete_multiple_files
from app.schemas import (
    Document,
    DocumentCreate,
    DocumentDetail,
    DocumentStatusUpdate,
    SupportedFileTypes,
    SupportedFileType,
    DocumentUpdate,
)
from app.models import Document as DocumentModel, User, DocumentFile, DocumentChunk
from app.config import settings

router = APIRouter(prefix="/documents", tags=["documents"])

# 지원되는 파일 형식 정의
SUPPORTED_FILE_TYPES = [
    SupportedFileType(extension=".pdf", description="PDF 문서", max_size_mb=50),
    SupportedFileType(extension=".docx", description="Microsoft Word 문서", max_size_mb=30),
    SupportedFileType(extension=".txt", description="텍스트 파일", max_size_mb=10),
    SupportedFileType(extension=".xlsx", description="Microsoft Excel 문서", max_size_mb=30),
    SupportedFileType(extension=".pptx", description="Microsoft PowerPoint 문서", max_size_mb=50),
]

# 허용되는 파일 확장자 목록
ALLOWED_EXTENSIONS = [file_type.extension for file_type in SUPPORTED_FILE_TYPES]


# 문서 업로드 응답 모델 (Celery 작업 ID 포함)
class DocumentUploadResponse(BaseModel):
    id: UUID
    title: str
    summary: Optional[str] = None
    tags: List[str] = []
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    user_id: UUID
    file_names: List[str] = []
    file_paths: List[str] = []
    file_types: List[str] = []
    task_id: Optional[str] = None
    vectorized: bool = False
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    view_count: Optional[int] = 0
    download_count: Optional[int] = 0
    file_metadata: Optional[Dict] = None
    is_public: bool


# 지원되는 파일 형식 API
@router.get("/supported-types", response_model=SupportedFileTypes)
def get_supported_file_types():
    """지원되는 파일 형식 목록을 반환합니다."""
    return SupportedFileTypes(file_types=SUPPORTED_FILE_TYPES)


# 멀티파일 문서 업로드 API
@router.post("/upload", response_model=DocumentUploadResponse)
async def create_document(
    request: Request,
    title: str = Form(...),
    summary: str = Form(default=""),
    tags: str = Form(default="[]"),  # JSON 문자열로 전달됨
    startDate: Optional[str] = Form(None),  # 프론트엔드 필드명과 일치
    endDate: Optional[str] = Form(None),  # 프론트엔드 필드명과 일치
    is_public: bool = Form(True),  # 공개/비공개 설정
    async_processing: bool = Form(True),  # 기본값을 True로 변경하여 항상 비동기 처리
    files: List[UploadFile] = File([]),  # 멀티파일 지원으로 수정
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    여러 파일을 업로드하여 새 문서를 생성합니다.
    파일은 MinIO에 저장되고, 메타데이터는 데이터베이스에 저장됩니다.
    비동기 처리 옵션을 사용하면 파일 업로드와 처리가 백그라운드에서 진행됩니다.
    작업 ID가 응답에 포함되어 작업 진행 상황을 조회할 수 있습니다.
    """
    # 폼 데이터에서 파일 추출 (모든 UploadFile 타입 찾기)
    upload_files = []
    form = await request.form()

    # 디버깅 정보 출력
    print(f"Form keys: {form.keys()}")
    print(f"명시적 파일 파라미터: {files}")

    # 명시적 파일 파라미터 처리
    if files:
        print(f"명시적 파일 추가: {files[0].filename}")
        upload_files.extend(files)

    # 파일 추출 방법 개선: 다양한 파일 필드 이름 처리
    for key in form.keys():
        value = form[key]
        print(f"Key: {key}, Type: {type(value)}")
        if isinstance(value, UploadFile):
            print(f"Found file from form: {value.filename}")
            upload_files.append(value)

    # 일괄 처리된 'files' 필드 처리 (멀티파일 필드)
    if "files" in form:
        files_value = form["files"]
        # 단일 파일인 경우
        if isinstance(files_value, UploadFile):
            print(f"Found single file in 'files' field: {files_value.filename}")
            upload_files.append(files_value)
        # 다중 파일인 경우
        elif isinstance(files_value, list):
            print(f"Found files array with {len(files_value)} items")
            for file in files_value:
                if isinstance(file, UploadFile):
                    print(f"Found file in array: {file.filename}")
                    upload_files.append(file)

    # file로 시작하는 인덱스 처리 (file0, file1, ...)
    file_keys = [key for key in form.keys() if key.startswith("file") and key != "files"]
    for key in file_keys:
        value = form[key]
        if isinstance(value, UploadFile):
            print(f"Found indexed file {key}: {value.filename}")
            upload_files.append(value)

    # 중복 파일 제거 (filename 기준)
    seen_filenames = set()
    unique_files = []
    for file in upload_files:
        if file.filename not in seen_filenames:
            seen_filenames.add(file.filename)
            unique_files.append(file)

    upload_files = unique_files
    print(f"총 업로드할 파일 수: {len(upload_files)}")

    # 파일이 있는지 확인
    if not upload_files or len(upload_files) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided",
        )

    # 파일 타입 검증
    for file in upload_files:
        file_extension = os.path.splitext(file.filename)[1].lower()
        if file_extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed for file '{file.filename}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
            )

    # 태그 처리 (JSON 문자열에서 Python 리스트로 변환)
    try:
        tag_list = json.loads(tags) if tags else []
    except json.JSONDecodeError:
        tag_list = [tag.strip() for tag in tags.split(",")] if tags else []

    # 날짜 처리
    doc_start_date = None
    doc_end_date = None

    if startDate:  # startDate 파라미터 사용
        try:
            # Z 또는 timezone 정보가 있으면 처리, 없으면 기본 형식 사용
            if "Z" in startDate:
                doc_start_date = datetime.fromisoformat(startDate.replace("Z", "+00:00"))
            elif "T" in startDate:
                doc_start_date = datetime.fromisoformat(startDate)
            else:
                # 날짜만 있는 경우 (YYYY-MM-DD)
                doc_start_date = datetime.strptime(startDate, "%Y-%m-%d")
        except ValueError as e:
            print(f"시작일 파싱 오류: {e}, 입력값: {startDate}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid startDate format: {startDate}. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)",
            )

    if endDate:  # endDate 파라미터 사용
        try:
            # Z 또는 timezone 정보가 있으면 처리, 없으면 기본 형식 사용
            if "Z" in endDate:
                doc_end_date = datetime.fromisoformat(endDate.replace("Z", "+00:00"))
            elif "T" in endDate:
                doc_end_date = datetime.fromisoformat(endDate)
            else:
                # 날짜만 있는 경우 (YYYY-MM-DD)
                doc_end_date = datetime.strptime(endDate, "%Y-%m-%d")
        except ValueError as e:
            print(f"종료일 파싱 오류: {e}, 입력값: {endDate}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid endDate format: {endDate}. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)",
            )

    try:
        # 트랜잭션 시작 - 중요: 문서 생성 및 커밋 먼저 수행
        # 문서 객체 생성 (파일 정보 없이)
        db_document = DocumentModel(
            title=title,
            summary=summary,
            tags=tag_list,
            user_id=current_user.id,
            start_date=doc_start_date,
            end_date=doc_end_date,
            is_public=is_public,  # 공개/비공개 상태 추가
        )

        # 데이터베이스에 저장하고 즉시 커밋 - 파일 업로드 전에 문서 ID 확보
        db.add(db_document)
        db.commit()
        db.refresh(db_document)

        # 문서 ID 확보 후 파일 업로드 진행
        print(f"Document created with ID: {db_document.id}")

        # 다중 파일 업로드 (비동기 처리 옵션 전달)
        print(f"upload_files: {upload_files}")
        file_infos = await upload_multiple_files(
            upload_files, str(current_user.id), str(db_document.id), async_processing
        )

        # 파일 정보 DB 저장 (storage.py 내에서 이미 처리됨)
        # 작업 ID 추적을 위한 변수
        main_task_id = None
        print(f"file_infos: {file_infos}")

        # 작업 ID 추출
        for file_info in file_infos:
            # 작업 ID 저장 (첫 번째 파일의 작업 ID를 대표 작업 ID로 사용)
            if async_processing and "task_id" in file_info and not main_task_id:
                main_task_id = file_info["task_id"]

        # 문서에 작업 ID 저장 (필요한 경우)
        if main_task_id:
            file_metadata = db_document.file_metadata or {}
            file_metadata["main_task_id"] = main_task_id
            db_document.file_metadata = file_metadata
            db.commit()

        # 응답 준비 (Celery 작업 ID 포함)
        response = {
            "id": db_document.id,
            "title": db_document.title,
            "summary": db_document.summary,
            "tags": db_document.tags,
            "status": db_document.status,
            "created_at": db_document.created_at,
            "updated_at": db_document.updated_at,
            "user_id": db_document.user_id,
            "start_date": db_document.start_date,
            "end_date": db_document.end_date,
            "view_count": db_document.view_count,
            "download_count": db_document.download_count,
            "vectorized": db_document.vectorized,
            "file_metadata": db_document.file_metadata,
            "is_public": db_document.is_public,  # 응답에 is_public 추가
            "task_id": main_task_id,  # 작업 ID 추가
            # 파일 정보는 응답 스키마에 따라 채움
            "file_names": [file_info["original_name"] for file_info in file_infos] if file_infos else [],
            "file_paths": [file_info["path"] for file_info in file_infos] if file_infos else [],
            "file_types": [file_info["type"] for file_info in file_infos] if file_infos else [],
        }

        return response

    except Exception as e:
        # 오류 발생 시 롤백
        db.rollback()
        print(f"문서 생성 중 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create document: {str(e)}"
        )


# 문서 목록 조회 API
@router.get("", response_model=List[Document])
def get_documents(
    skip: int = 0,
    limit: int = 100,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    status: Optional[str] = None,
    tag: Optional[List[str]] = Query(None),
    view_type: str = "all",  # 'all', 'my', 'public' 옵션 추가
    uploader_id: Optional[UUID] = None,  # 특정 업로더의 문서만 조회
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    문서 목록을 조회합니다.

    - view_type:
      - 'all': 모든 문서 (관리자만 가능)
      - 'my': 내가 올린 문서
      - 'public': 공개된 문서
    """
    # 기본 쿼리 구성
    query = db.query(DocumentModel).options(selectinload(DocumentModel.files), selectinload(DocumentModel.user))

    # 1. 보기 유형에 따른 필터링
    if view_type == "my":
        # 내가 올린 문서만 조회
        query = query.filter(DocumentModel.user_id == current_user.id)
    elif view_type == "public":
        # 공개 문서만 조회 (승인된 문서 중)
        query = query.filter(DocumentModel.is_public == True, DocumentModel.status == "승인완료")
    elif view_type == "all":
        # 관리자가 아니면 전체 조회 불가능
        if current_user.role != "admin":
            # 일반 사용자는 자신의 문서 + 공개된 문서만 볼 수 있음
            query = query.filter(
                (DocumentModel.user_id == current_user.id)
                | ((DocumentModel.is_public == True) & (DocumentModel.status == "승인완료"))
            )

    # 2. 특정 업로더의 문서만 조회 (관리자 기능)
    if uploader_id and current_user.role == "admin":
        query = query.filter(DocumentModel.user_id == uploader_id)

    # 3. 상태 필터링
    if status:
        query = query.filter(DocumentModel.status == status)

    # 4. 태그 필터링
    if tag:
        for t in tag:
            query = query.filter(DocumentModel.tags.any(t))

    # 5. 정렬 설정
    if sort_order.lower() == "asc":
        order_func = getattr(getattr(DocumentModel, sort_by), "asc")
    else:
        order_func = getattr(getattr(DocumentModel, sort_by), "desc")

    # 정렬 및 페이지네이션 적용
    documents = query.order_by(order_func()).offset(skip).limit(limit).all()

    # 응답 구성
    result = []
    for doc in documents:
        doc_dict = {
            "id": doc.id,
            "title": doc.title,
            "summary": doc.summary,
            "tags": doc.tags,
            "status": doc.status,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
            "user_id": doc.user_id,
            "start_date": doc.start_date,
            "end_date": doc.end_date,
            "view_count": doc.view_count,
            "download_count": doc.download_count,
            "vectorized": doc.vectorized,
            "file_metadata": doc.file_metadata,
            "is_public": doc.is_public,
            "uploader_name": doc.user.name if doc.user else None,
            "uploader_email": doc.user.email if doc.user else None,
        }

        # 파일 정보 추가
        file_names = []
        file_paths = []
        file_types = []

        if doc.files:
            for file in doc.files:
                file_names.append(file.original_filename)
                file_paths.append(file.file_path)
                file_types.append(file.file_type)

        doc_dict["file_names"] = file_names
        doc_dict["file_paths"] = file_paths
        doc_dict["file_types"] = file_types

        result.append(doc_dict)

    return result


# 문서 상세 조회 API
@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    document = (
        db.query(DocumentModel)
        .options(selectinload(DocumentModel.files), selectinload(DocumentModel.user))
        .filter(DocumentModel.id == document_id)
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 접근 권한 확인
    if document.user_id != current_user.id and current_user.role != "admin":
        # 공개 문서이고 승인된 상태인지 확인
        if not (document.is_public and document.status == "승인완료"):
            raise HTTPException(status_code=403, detail="You don't have permission to access this document")

    # 조회수 증가
    document.view_count += 1
    db.commit()

    # 파일 정보 추가
    file_names = []
    file_paths = []
    file_types = []

    if document.files:
        for file in document.files:
            file_names.append(file.original_filename)
            file_paths.append(file.file_path)
            file_types.append(file.file_type)

    document.file_names = file_names
    document.file_paths = file_paths
    document.file_types = file_types

    return document


# 문서 생성 API
@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
def create_document(
    document: DocumentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    db_document = DocumentModel(**document.dict(), user_id=current_user.id)
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    return db_document


# 문서 수정 API
@router.put("/{document_id}", response_model=Document)
def update_document(
    document_id: UUID,
    document_update: DocumentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    db_document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not db_document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 사용자 본인 또는 관리자만 수정 가능
    if db_document.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to update this document")

    # 업데이트할 필드 유효성 검사
    update_data = document_update.dict(exclude_unset=True)

    # 일반 사용자가 수정하면 승인대기 상태로 변경 (관리자는 상태 유지)
    if current_user.role != "admin" and "status" not in update_data:
        update_data["status"] = "승인대기"

    # 필드 업데이트
    for key, value in update_data.items():
        setattr(db_document, key, value)

    db.commit()
    db.refresh(db_document)
    return db_document


# 문서 삭제 API
@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    db_document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not db_document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 사용자 본인 또는 관리자만 삭제 가능
    if db_document.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to delete this document")

    # 문서 관련 파일 및 벡터 데이터 삭제 로직 (파일 시스템 또는 MinIO에서 삭제)
    # TODO: 연결된 파일 정리 로직 구현

    # DB에서 문서 삭제
    db.delete(db_document)
    db.commit()

    return {"message": "Document deleted successfully"}


# 공개 상태 변경 API
@router.post("/{document_id}/toggle-public", response_model=Document)
def toggle_public_status(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    db_document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not db_document:
        raise HTTPException(status_code=404, detail="Document not found")

    # 문서 소유자나 관리자만 공개 상태 변경 가능
    if db_document.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to change document visibility")

    # 승인된 문서만 공개로 전환 가능
    if not db_document.is_public and db_document.status != "승인완료" and current_user.role != "admin":
        raise HTTPException(status_code=400, detail="Only approved documents can be made public")

    # 공개 상태 전환
    db_document.is_public = not db_document.is_public

    # 일반 사용자가 비공개에서 공개로 변경하는 경우, 관리자 승인이 필요
    if db_document.is_public and current_user.role != "admin":
        # 이미 승인된 상태가 아니면 승인 대기로 변경
        if db_document.status != "승인완료":
            db_document.status = "승인대기"

    db.commit()
    db.refresh(db_document)
    return db_document


# 문서 다운로드 URL 생성 API
@router.get("/{document_id}/download")
def download_document(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    """특정 문서에 속한 파일들의 다운로드 URL을 생성합니다."""
    try:
        # 문서와 파일을 함께 조회 (필요한 필드만 로드)
        document = (
            db.query(DocumentModel)
            .options(
                selectinload(DocumentModel.files).load_only(
                    DocumentFile.file_path,
                    DocumentFile.original_filename,
                    DocumentFile.processing_status,  # 처리 상태 추가
                    DocumentFile.file_metadata,  # 메타데이터 추가
                )
            )
            .filter(DocumentModel.id == document_id)
            .first()
        )

        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        # 문서 소유자 또는 관리자만 접근 가능
        if document.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

        # 파일이 없는 경우
        if not document.files:
            return {"download_urls": [], "download_info": [], "warning": "No files found in this document"}

        # 파일 경로 및 상태 추출
        available_files = []
        unavailable_files = []

        for file in document.files:
            # 완료된 파일만 포함
            if file.processing_status == "completed":
                available_files.append(file)
            else:
                # 처리 중이거나 실패한 파일은 별도 목록에 추가
                unavailable_files.append(
                    {
                        "filename": file.original_filename,
                        "status": file.processing_status,
                        "error": file.file_metadata.get("upload_error", None) if file.file_metadata else None,
                    }
                )

        # 다운로드 가능한 파일이 없는 경우
        if not available_files:
            warning_message = "No files are ready for download."
            if unavailable_files:
                details = ", ".join([f"{f['filename']} ({f['status']})" for f in unavailable_files])
                warning_message += f" Files still processing or failed: {details}"

            return {
                "download_urls": [],
                "download_info": [],
                "warning": warning_message,
                "unavailable_files": unavailable_files,
            }

        # 다운로드 URL 생성 (완료된 파일만)
        file_paths = [file.file_path for file in available_files]
        file_names = [file.original_filename for file in available_files]

        try:
            # 다운로드 URL 생성
            download_urls_result = get_multiple_download_urls(file_paths)

            # 다운로드 URL과 파일명 함께 반환
            download_info = []
            download_urls = []

            for i, url_info in enumerate(download_urls_result):
                if url_info and "url" in url_info:  # URL 생성에 실패한 경우는 건너뜀
                    download_urls.append(url_info["url"])
                    download_info.append({"filename": file_names[i], "url": url_info["url"]})

            # 다운로드 횟수 증가
            document.download_count += 1
            db.commit()

            # 사용할 수 없는 파일이 있는 경우 경고 추가
            if unavailable_files:
                return {
                    "download_urls": download_urls,
                    "download_info": download_info,
                    "warning": "Some files are not available for download",
                    "unavailable_files": unavailable_files,
                }

            return {"download_urls": download_urls, "download_info": download_info}

        except Exception as e:
            print(f"다운로드 URL 생성 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to generate download URLs: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"다운로드 URL 생성 오류: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# 직접 다운로드 핸들러 함수
async def direct_download_handler(
    file_path: str,
    file_name: str,
    content_type: str,
    document_id: UUID,
    db: Session,
):
    """
    MinIO에서 파일을 직접 스트리밍하여 다운로드 제공
    서명된 URL이 작동하지 않을 때 대체 방법으로 사용
    """
    try:
        from app.storage import get_file_stream
        from app.models import Document as DocumentModel

        # 문서 다운로드 횟수 증가
        document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if document:
            document.download_count += 1
            db.commit()

        # 파일 스트림 가져오기
        stream, size, actual_content_type = get_file_stream(file_path)

        # 실제 컨텐츠 타입이 없으면 전달된 것 사용
        if not actual_content_type or actual_content_type == "application/octet-stream":
            actual_content_type = content_type or "application/octet-stream"

        # 파일명 인코딩 처리 (한글 등 특수문자 지원)
        encoded_filename = urllib.parse.quote(file_name)

        # 응답 헤더 설정
        headers = {
            "Content-Disposition": f'attachment; filename="{encoded_filename}"',
            "Content-Type": actual_content_type,
            "Content-Length": str(size),
        }

        # 스트리밍 응답 생성
        return StreamingResponse(stream, headers=headers, media_type=actual_content_type)
    except Exception as e:
        print(f"직접 다운로드 처리 오류: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"파일 다운로드 실패: {str(e)}")


# 특정 파일 직접 다운로드 API
@router.get("/{document_id}/download/{file_name}")
async def download_document_file(
    document_id: UUID,
    file_name: str,
    direct: bool = Query(True, description="직접 스트리밍 방식 사용 여부 (기본값: True)"),
    chunk_size: int = Query(4 * 1024 * 1024, description="청크 크기 (바이트)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """특정 문서에서 지정된 파일을 직접 다운로드합니다."""
    try:
        # 문서와 파일을 함께 조회 (필요한 필드만 로드)
        document = (
            db.query(DocumentModel)
            .options(
                selectinload(DocumentModel.files).load_only(
                    DocumentFile.file_path,
                    DocumentFile.original_filename,
                    DocumentFile.content_type,
                    DocumentFile.processing_status,  # 파일 처리 상태 추가
                    DocumentFile.file_metadata,  # 파일 메타데이터 추가
                )
            )
            .filter(DocumentModel.id == document_id)
            .first()
        )

        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        # 문서 소유자 또는 관리자만 접근 가능 (승인된 문서는 모든 사용자가 접근 가능으로 변경 가능)
        if document.user_id != current_user.id and current_user.role != "admin" and document.status != "승인완료":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

        # 파일이 없는 경우
        if not document.files:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No files found in this document")

        # 요청된 파일명에 해당하는 파일 찾기
        file_info = None
        for file in document.files:
            if file.original_filename == file_name:
                file_info = file
                break

        if not file_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"File {file_name} not found in document"
            )

        # 파일 처리 상태 확인
        if file_info.processing_status != "completed":
            # 파일이 아직 처리 중인 경우
            if file_info.processing_status == "processing":
                # 작업 ID가 있는지 확인하여 상태 업데이트
                task_id = None
                if file_info.file_metadata and "task_id" in file_info.file_metadata:
                    task_id = file_info.file_metadata["task_id"]

                    # Celery 작업 상태 확인
                    try:
                        from app.celery_worker import celery
                        from celery.result import AsyncResult

                        task_result = AsyncResult(task_id, app=celery)

                        # 작업이 완료된 경우 파일 상태 업데이트
                        if task_result.status == "SUCCESS":
                            file_info.processing_status = "completed"
                            db.commit()
                        elif task_result.status == "FAILURE":
                            # 실패한 작업이면 실패로 상태 변경
                            file_info.processing_status = "failed"
                            file_metadata = file_info.file_metadata or {}
                            file_metadata["upload_error"] = str(task_result.result)
                            file_info.file_metadata = file_metadata
                            db.commit()

                            # 실패 메시지 반환
                            raise HTTPException(
                                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=f"File upload failed: {str(task_result.result)}",
                            )
                        else:
                            # 아직 처리 중
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail=f"File is still being processed (task: {task_id}, status: {task_result.status}). Please try again later.",
                            )
                    except ImportError:
                        # Celery 모듈 임포트 실패
                        pass

                # 작업 ID가 없거나 상태 확인에 실패한 경우
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="File is still being processed. Please try again later.",
                )
            # 파일 처리 실패한 경우
            elif file_info.processing_status == "failed":
                error_message = "File processing failed"
                if file_info.file_metadata and "upload_error" in file_info.file_metadata:
                    error_message += f": {file_info.file_metadata['upload_error']}"
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_message)

        # 파일 존재 여부 확인 (NoSuchKey 오류 방지)
        try:
            from app.storage import check_file_exists

            if not check_file_exists(file_info.file_path):
                # 파일을 찾을 수 없는 경우 메타데이터 업데이트
                file_info.processing_status = "failed"
                metadata = file_info.file_metadata or {}
                metadata["minio_error"] = "File marked as completed but not found in storage"
                metadata["error_time"] = datetime.utcnow().isoformat()
                file_info.file_metadata = metadata
                db.commit()

                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"File not found in storage. It may have been deleted.",
                )
        except Exception as err:
            print(f"MinIO 파일 확인 오류 ({file_info.file_path}): {str(err)}")

        # 다운로드 횟수 증가
        document.download_count += 1
        db.commit()

        # 항상 직접 스트리밍 방식 사용 (서명 검증 문제 방지)
        print(f"직접 스트리밍 방식으로 다운로드: {file_info.file_path}")
        content_type = file_info.content_type or "application/octet-stream"

        # 파일 스트림 가져오기 (새로 추가된 코드)
        from app.storage import get_file_stream

        try:
            # 파일 스트림 생성
            stream, size, actual_content_type = get_file_stream(file_info.file_path)

            # 실제 컨텐츠 타입 적용
            if actual_content_type and actual_content_type != "application/octet-stream":
                content_type = actual_content_type

            # 파일명 인코딩 처리 (한글 등 특수문자 지원)
            encoded_filename = urllib.parse.quote(file_name)

            # 응답 헤더 설정
            headers = {
                "Content-Disposition": f'attachment; filename="{encoded_filename}"',
                "Content-Type": content_type,
                "Content-Length": str(size),
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            }

            # 스트리밍 응답 생성 (타임아웃 없음)
            response = StreamingResponse(
                stream,
                headers=headers,
                media_type=content_type,
            )

            # 응답 반환
            return response

        except Exception as stream_err:
            print(f"스트리밍 오류: {str(stream_err)}")

            # 예전 방식으로 대체 시도 (필요할 경우에만)
            if not direct:
                from app.storage import get_download_url

                # 서명된 URL 생성 시도
                signed_url = get_download_url(file_info.file_path, expires=1800)
                if signed_url:
                    print(f"서명된 URL 생성 성공 (예비 방식): {signed_url}")
                    return RedirectResponse(url=signed_url)

            # 모든 방식 실패
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"파일 다운로드 실패: {str(stream_err)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"파일 다운로드 처리 오류: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# 일반 사용자용 문서 승인 API
@router.post("/{document_id}/approve", response_model=Document)
def approve_document_user(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    """사용자가 문서를 승인합니다."""
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # 관리자가 아닌 경우 권한 확인
    if current_user.role != "admin":
        # 승인 권한이 있는지 확인 (같은 조직 또는 부서 등의 조건)
        # 여기서는 간단히 모든 사용자에게 승인 권한을 주고 로그만 남김
        logging.info(f"User {current_user.id} approved document {document_id}")

    # 문서 상태 변경
    document.status = "승인완료"

    # 승인 메타데이터 추가
    metadata = document.file_metadata or {}
    metadata["approved_by"] = str(current_user.id)
    metadata["approved_at"] = datetime.utcnow().isoformat()
    document.file_metadata = metadata

    db.commit()
    db.refresh(document)

    return document


# 일반 사용자용 문서 거부 API
@router.post("/{document_id}/reject", response_model=Document)
def reject_document_user(
    document_id: UUID,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """사용자가 문서를 거부합니다."""
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # 관리자가 아닌 경우 권한 확인
    if current_user.role != "admin":
        # 거부 권한이 있는지 확인 (같은 조직 또는 부서 등의 조건)
        # 여기서는 간단히 모든 사용자에게 거부 권한을 주고 로그만 남김
        logging.info(f"User {current_user.id} rejected document {document_id}")

    # 문서 상태 변경
    document.status = "승인대기"  # 또는 "거부됨" 등 별도 상태로 설정 가능

    # 거부 이유가 있으면 메타데이터에 추가
    if reason:
        metadata = document.file_metadata or {}
        metadata["reject_reason"] = reason
        metadata["rejected_by"] = str(current_user.id)
        metadata["rejected_at"] = datetime.utcnow().isoformat()
        document.file_metadata = metadata

    db.commit()
    db.refresh(document)

    return document


# 파일 상태 응답 모델
class FileStatusResponse(BaseModel):
    file_id: UUID
    original_filename: str
    file_path: str
    file_type: str
    processing_status: str
    exists_in_storage: bool
    file_metadata: Optional[Dict] = None
    error_message: Optional[str] = None
    is_public: Optional[bool] = None  # 파일별 공개/비공개 상태 추가


# 파일 공개 상태 변경 요청 모델
class FileVisibilityRequest(BaseModel):
    is_public: bool


# 파일 상태 확인 API
@router.get("/{document_id}/files/status", response_model=List[FileStatusResponse])
def check_document_files_status(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    """문서에 속한 모든 파일의 상태를 조회합니다."""
    try:
        # 문서와 파일 정보 조회
        document = (
            db.query(DocumentModel)
            .options(
                selectinload(DocumentModel.files).load_only(
                    DocumentFile.id,
                    DocumentFile.file_path,
                    DocumentFile.original_filename,
                    DocumentFile.file_type,
                    DocumentFile.processing_status,
                    DocumentFile.file_metadata,
                    DocumentFile.error_message,
                )
            )
            .filter(DocumentModel.id == document_id)
            .first()
        )

        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        # 권한 확인: 소유자나 관리자만 접근 가능
        if document.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

        # 파일이 없는 경우
        if not document.files:
            return []

        # 파일 상태 확인
        from app.storage import check_multiple_files_exist

        # 모든 파일 경로 추출
        file_paths = [file.file_path for file in document.files]

        # 파일 존재 여부 일괄 확인
        files_exist = check_multiple_files_exist(file_paths)

        # 파일별 상태 정보 구성
        file_statuses = []
        for file in document.files:
            # MinIO에 파일 존재 여부
            exists_in_storage = files_exist.get(file.file_path, False)

            # 파일별 공개/비공개 상태 확인
            is_public = True  # 기본값
            if file.file_metadata and "is_public" in file.file_metadata:
                is_public = file.file_metadata["is_public"]

            # 상태 정보 수집
            file_status = {
                "file_id": file.id,
                "original_filename": file.original_filename,
                "file_path": file.file_path,
                "file_type": file.file_type,
                "processing_status": file.processing_status,
                "exists_in_storage": exists_in_storage,
                "file_metadata": file.file_metadata,
                "error_message": file.error_message,
                "is_public": is_public,
            }

            # 상태와 실제 존재 여부가 일치하지 않는 경우 메타데이터 업데이트
            if file.processing_status == "completed" and not exists_in_storage:
                file.processing_status = "failed"
                metadata = file.file_metadata or {}
                metadata["minio_error"] = "File marked as completed but not found in storage"
                metadata["error_time"] = datetime.utcnow().isoformat()
                file.file_metadata = metadata
                file.error_message = "File not found in storage"
                db.commit()

                # 업데이트된 정보 반영
                file_status["processing_status"] = "failed"
                file_status["file_metadata"] = metadata
                file_status["error_message"] = "File not found in storage"

            file_statuses.append(file_status)

        return file_statuses
    except Exception as e:
        print(f"파일 상태 확인 오류: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# 파일 재업로드 응답 모델
class FileReuploadResponse(BaseModel):
    file_id: UUID
    original_filename: str
    task_id: Optional[str] = None
    status: str


# 파일 재업로드 API
@router.post("/{document_id}/files/{file_id}/reupload", response_model=FileReuploadResponse)
async def reupload_document_file(
    document_id: UUID,
    file_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),  # 관리자만 접근 가능
):
    """
    (관리자 전용) 손상되거나 누락된 파일을 재업로드합니다.
    기존 파일과 동일한 이름으로 업로드해야 합니다.
    """
    try:
        # 문서 및 파일 정보 조회
        document_file = (
            db.query(DocumentFile).filter(DocumentFile.id == file_id, DocumentFile.document_id == document_id).first()
        )

        if not document_file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File with ID {file_id} not found in document {document_id}",
            )

        # 파일명 확인
        if document_file.original_filename != file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Filename mismatch. Expected: {document_file.original_filename}, Got: {file.filename}",
            )

        # 임시 파일로 저장
        temp_file_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
        with open(temp_file_path, "wb") as buffer:
            file_content = await file.read()
            buffer.write(file_content)

        # Celery 작업 실행 (비동기 처리)
        from app.tasks.file_tasks import upload_file_to_minio

        # 파일 크기 업데이트
        document_file.file_size = os.path.getsize(temp_file_path)

        # 작업 상태 초기화
        document_file.processing_status = "processing"
        document_file.error_message = None

        # 메타데이터 업데이트
        metadata = document_file.file_metadata or {}
        metadata["reuploaded_by"] = str(current_user.id)
        metadata["reuploaded_at"] = datetime.utcnow().isoformat()
        metadata["original_error"] = metadata.get("minio_error", "Unknown error")
        document_file.file_metadata = metadata

        # DB 업데이트
        db.commit()

        # 비동기 작업 실행
        task = upload_file_to_minio.delay(temp_file_path, document_file.file_path, str(document_id), str(file_id))

        # 작업 ID 저장
        metadata = document_file.file_metadata or {}
        metadata["reupload_task_id"] = task.id
        document_file.file_metadata = metadata
        db.commit()

        return {
            "file_id": document_file.id,
            "original_filename": document_file.original_filename,
            "task_id": task.id,
            "status": "processing",
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"파일 재업로드 오류: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# 파일 삭제 API 엔드포인트 추가
@router.delete("/{document_id}/files/{file_name}")
async def delete_document_file(
    document_id: UUID,
    file_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """문서에서 특정 파일을 삭제합니다."""
    try:
        # 문서 조회
        document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        # 권한 확인 (소유자 또는 관리자만 삭제 가능)
        if document.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this file")

        # 파일 조회
        db_file = (
            db.query(DocumentFile)
            .filter(DocumentFile.document_id == document_id, DocumentFile.original_filename == file_name)
            .first()
        )

        if not db_file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"File {file_name} not found in document"
            )

        # MinIO에서 파일 삭제
        from app.storage import delete_file

        try:
            delete_file(db_file.file_path)
        except Exception as e:
            print(f"MinIO 파일 삭제 오류: {str(e)}")
            # 파일 시스템 오류는 무시하고 데이터베이스에서 삭제 진행

        # 문서 청크 삭제 (벡터 DB와 연결된 청크)
        db.query(DocumentChunk).filter(DocumentChunk.file_id == db_file.id).delete()

        # 데이터베이스에서 파일 정보 삭제
        db.delete(db_file)
        db.commit()

        # 문서가 벡터화되었고, 파일이 삭제되면 벡터화 상태 업데이트
        if document.vectorized:
            remaining_files = db.query(DocumentFile).filter(DocumentFile.document_id == document_id).count()
            if remaining_files == 0:
                document.vectorized = False
                db.commit()

        return {"message": f"File {file_name} has been deleted from document"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"파일 삭제 오류: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# 파일 공개/비공개 상태 변경 API 엔드포인트 추가
@router.post("/{document_id}/files/{file_name}/visibility")
async def toggle_file_visibility(
    document_id: UUID,
    file_name: str,
    visibility: FileVisibilityRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """문서 내 특정 파일의 공개/비공개 상태를 변경합니다."""
    try:
        # 문서 조회
        document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        # 권한 확인 (소유자 또는 관리자만 수정 가능)
        if document.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to change this file visibility"
            )

        # 파일 조회
        db_file = (
            db.query(DocumentFile)
            .filter(DocumentFile.document_id == document_id, DocumentFile.original_filename == file_name)
            .first()
        )

        if not db_file:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"File {file_name} not found in document"
            )

        # 메타데이터에 공개 상태 저장
        metadata = db_file.file_metadata or {}
        metadata["is_public"] = visibility.is_public
        metadata["visibility_updated_at"] = datetime.utcnow().isoformat()
        metadata["visibility_updated_by"] = str(current_user.id)

        db_file.file_metadata = metadata
        db.commit()

        return {
            "file_id": db_file.id,
            "original_filename": db_file.original_filename,
            "is_public": visibility.is_public,
            "message": f"File visibility has been set to {'public' if visibility.is_public else 'private'}",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"파일 공개 상태 변경 오류: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# 추가 파일 업로드 응답 모델
class AdditionalFileUploadResponse(BaseModel):
    document_id: UUID
    uploaded_files: List[Dict]
    message: str


# 추가 파일 업로드 API
@router.post("/{document_id}/files/upload", response_model=AdditionalFileUploadResponse)
async def upload_additional_files(
    document_id: UUID,
    files: List[UploadFile] = File([]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """문서에 추가 파일을 업로드합니다."""
    try:
        # 문서 존재 여부 확인
        document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        # 권한 확인 (소유자 또는 관리자만 파일 추가 가능)
        if document.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to upload files to this document"
            )

        # 파일 업로드
        if not files or len(files) == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

        # 파일 타입 검증
        for file in files:
            file_extension = os.path.splitext(file.filename)[1].lower()
            if file_extension not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File type not allowed for file '{file.filename}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
                )

        # 다중 파일 업로드 (비동기 처리)
        file_infos = await upload_multiple_files(files, str(current_user.id), str(document_id), True)

        # 문서 상태를 '승인대기'로 변경
        document.status = "승인대기"
        document.updated_at = datetime.utcnow()
        db.commit()

        # 응답 생성
        return {
            "document_id": document_id,
            "uploaded_files": file_infos,
            "message": f"{len(file_infos)} files uploaded successfully. Document status changed to '승인대기'.",
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"추가 파일 업로드 오류: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
