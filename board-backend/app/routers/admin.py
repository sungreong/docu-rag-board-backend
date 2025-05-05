from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func
from uuid import UUID
from datetime import datetime
import logging

from app.database import get_db
from app.auth import get_current_admin_user
from app.schemas import Document, DocumentStatusUpdate, DocumentDetail, User as UserSchema
from app.models import Document as DocumentModel, User, DocumentFile, DocumentChunk
from app.utils.vectorizer import chunk_document, simple_chunk_document

router = APIRouter(prefix="/admin", tags=["admin"])


# 관리자 통계 API
@router.get("/stats")
def get_admin_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 시스템 통계 정보를 제공합니다."""
    try:
        # 승인 대기 중인 문서 수
        pending_approval_count = (
            db.query(func.count(DocumentModel.id)).filter(DocumentModel.status == "승인대기").scalar()
        )

        # 승인된 문서 수
        approved_count = db.query(func.count(DocumentModel.id)).filter(DocumentModel.status == "승인완료").scalar()

        # 전체 문서 수
        total_documents = db.query(func.count(DocumentModel.id)).scalar()

        # 전체 사용자 수
        total_users = db.query(func.count(User.id)).scalar()

        # 승인 대기 중인 사용자 수
        pending_user_approval = (
            db.query(func.count(User.id)).filter(User.is_approved == False, User.is_active == True).scalar()
        )

        # 총 문서 파일 수
        total_files = db.query(func.count(DocumentFile.id)).scalar()

        # 벡터화된 문서 수
        vectorized_docs = db.query(func.count(DocumentModel.id)).filter(DocumentModel.vectorized == True).scalar()

        # 총 청크 수
        total_chunks = db.query(func.count(DocumentChunk.id)).scalar()

        # 태그별 문서 수 (상위 10개)
        tag_counts = []
        documents = db.query(DocumentModel.tags).all()
        tag_dict = {}

        for doc in documents:
            if doc.tags:
                for tag in doc.tags:
                    if tag in tag_dict:
                        tag_dict[tag] += 1
                    else:
                        tag_dict[tag] = 1

        # 상위 10개 태그만 추출
        tag_counts = [
            {"tag": tag, "count": count}
            for tag, count in sorted(tag_dict.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        # 통계 결과 반환
        stats = {
            "pending_approval": pending_approval_count,
            "approved_documents": approved_count,
            "total_documents": total_documents,
            "total_users": total_users,
            "pending_user_approval": pending_user_approval,
            "total_files": total_files,
            "vectorized_documents": vectorized_docs,
            "total_chunks": total_chunks,
            "top_tags": tag_counts,
            "timestamp": datetime.now().isoformat(),
        }

        return stats

    except Exception as e:
        logging.error(f"관리자 통계 조회 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"통계 정보 생성 중 오류가 발생했습니다: {str(e)}",
        )


# 모든 사용자 목록 조회 (관리자용)
@router.get("/users", response_model=List[UserSchema])
def get_all_users(
    skip: int = 0,
    limit: int = 100,
    is_approved: Optional[bool] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 모든 사용자 목록을 조회합니다."""
    query = db.query(User)

    # 승인 상태로 필터링
    if is_approved is not None:
        query = query.filter(User.is_approved == is_approved)

    # 활성화 상태로 필터링
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    # 페이지네이션 적용
    users = query.offset(skip).limit(limit).all()

    return users


# 사용자 승인 API (관리자용)
@router.post("/users/{user_id}/approve", response_model=UserSchema)
def approve_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 사용자 계정을 승인합니다."""
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 이미 승인된 사용자인 경우
    if user.is_approved:
        return user

    user.is_approved = True
    db.commit()
    db.refresh(user)

    return user


# 사용자 비활성화 API (관리자용)
@router.post("/users/{user_id}/deactivate", response_model=UserSchema)
def deactivate_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 사용자 계정을 비활성화합니다."""
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 관리자는 비활성화할 수 없음
    if user.role == "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate admin user")

    user.is_active = False
    db.commit()
    db.refresh(user)

    return user


# 사용자 활성화 API (관리자용)
@router.post("/users/{user_id}/activate", response_model=UserSchema)
def activate_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 비활성화된 사용자 계정을 다시 활성화합니다."""
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 이미 활성화된 사용자인 경우
    if user.is_active:
        return user

    user.is_active = True
    db.commit()
    db.refresh(user)

    return user


# 전체 문서 목록 조회 API (관리자용)
@router.get("/documents", response_model=List[Document])
def get_all_documents(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    tag: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    try:
        # 문서와 파일 조인 쿼리 최적화
        query = db.query(DocumentModel).options(
            selectinload(DocumentModel.files).load_only(
                DocumentFile.original_filename, DocumentFile.file_path, DocumentFile.file_type
            )
        )

        # 상태별 필터링
        if status:
            query = query.filter(DocumentModel.status == status)

        # 태그 필터링
        if tag:
            for t in tag:
                query = query.filter(DocumentModel.tags.any(t))

        # 정렬 설정
        if sort_order.lower() == "asc":
            order_func = getattr(getattr(DocumentModel, sort_by), "asc")
        else:
            order_func = getattr(getattr(DocumentModel, sort_by), "desc")

        # 정렬 및 페이지네이션 적용
        documents = query.order_by(order_func()).offset(skip).limit(limit).all()

        # 파일 정보 포함하여 응답 준비
        result = []
        for doc in documents:
            # 문서 기본 정보 직접 매핑 (SQLAlchemy 객체에서 필요한 필드만 추출)
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
        print(result)
        return result
    except Exception as e:
        # 디버깅을 위한 오류 로깅
        print(f"관리자 문서 목록 조회 오류: {str(e)}")
        raise


# 문서 승인 API (관리자용)
@router.post("/documents/{document_id}/approve", response_model=Document)
def approve_document(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)
):
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

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


# 문서 거부 API (관리자용)
@router.post("/documents/{document_id}/reject", response_model=Document)
def reject_document(
    document_id: UUID,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # 문서 상태 변경
    document.status = "승인대기"

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


# 문서 삭제 API (관리자용)
@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)
):
    """
    문서와 관련된 모든 데이터를 삭제합니다:
    1. 문서 청크 및 벡터 데이터
    2. MinIO에 저장된 파일
    3. 문서 파일 레코드
    4. 문서 자체
    """
    # 관리자 권한 확인
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다")

    # 문서 존재 확인
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        # 트랜잭션 시작 - 삭제 작업을 하나의 트랜잭션으로 처리

        # 1. 문서 청크 및 벡터 데이터 삭제
        chunk_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
        logging.info(f"Deleted {chunk_count} chunks for document {document_id}")

        # 2. MinIO에서 파일 삭제 (먼저 파일 경로 수집)
        # 문서와 연결된 모든 파일 정보 조회
        document_files = db.query(DocumentFile).filter(DocumentFile.document_id == document_id).all()

        # 파일 경로 리스트 생성
        file_paths = [file.file_path for file in document_files]

        # MinIO에서 파일 삭제
        if file_paths:
            try:
                # storage.py 모듈의 delete_multiple_files 함수 사용
                from app.storage import delete_multiple_files

                # 파일 삭제 실행 및 결과 로깅
                success, failed_files = delete_multiple_files(file_paths)

                if not success:
                    # 일부 파일 삭제 실패 시 경고 로그
                    logging.warning(f"Failed to delete some files: {failed_files}")

                logging.info(f"Deleted {len(file_paths)} files from MinIO for document {document_id}")
            except Exception as file_error:
                # 파일 삭제 실패해도 계속 진행
                logging.error(f"Failed to delete files for document {document_id}: {str(file_error)}")

        # 3. 데이터베이스에서 문서 관련 파일 레코드 삭제
        file_count = db.query(DocumentFile).filter(DocumentFile.document_id == document_id).delete()
        logging.info(f"Deleted {file_count} file records for document {document_id}")

        # 4. 데이터베이스에서 문서 삭제
        db.delete(document)

        # 모든 변경사항 커밋
        db.commit()
        logging.info(f"Successfully deleted document {document_id} and all related data")

        return {"message": "Document and all related data deleted successfully"}
    except Exception as e:
        # 오류 발생 시 롤백
        db.rollback()
        logging.error(f"Error during document deletion: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete document: {str(e)}"
        )


# 문서 일괄 승인 API
@router.post("/documents/batch/approve", response_model=List[Document])
def approve_documents_batch(
    document_ids: List[UUID] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 여러 문서를 일괄 승인합니다."""
    if not document_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No document IDs provided")

    # 해당 ID의 문서들 조회
    documents = db.query(DocumentModel).filter(DocumentModel.id.in_(document_ids)).all()

    # ID별 문서 매핑 생성 (빠른 접근을 위해)
    doc_map = {str(doc.id): doc for doc in documents}

    # 찾지 못한 문서 ID 확인
    found_ids = [str(doc.id) for doc in documents]
    missing_ids = [str(doc_id) for doc_id in document_ids if str(doc_id) not in found_ids]

    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Documents not found: {', '.join(missing_ids)}"
        )

    # 모든 문서를 승인 상태로 변경
    for document in documents:
        # 이미 승인된 문서는 건너뜀
        if document.status == "승인완료":
            continue

        # 문서 상태 변경
        document.status = "승인완료"

        # 승인 메타데이터 추가
        metadata = document.file_metadata or {}
        metadata["approved_by"] = str(current_user.id)
        metadata["approved_at"] = datetime.utcnow().isoformat()
        metadata["batch_approval"] = True
        document.file_metadata = metadata

    # 변경사항 저장
    db.commit()

    # 변경된 문서 반환
    approved_documents = [doc for doc in documents if doc.status == "승인완료"]

    return approved_documents


# 문서 일괄 거부 API
@router.post("/documents/batch/reject", response_model=List[Document])
def reject_documents_batch(
    document_ids: List[UUID] = Body(...),
    reason: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 여러 문서를 일괄 거부합니다."""
    if not document_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No document IDs provided")

    # 해당 ID의 문서들 조회
    documents = db.query(DocumentModel).filter(DocumentModel.id.in_(document_ids)).all()

    # ID별 문서 매핑 생성 (빠른 접근을 위해)
    doc_map = {str(doc.id): doc for doc in documents}

    # 찾지 못한 문서 ID 확인
    found_ids = [str(doc.id) for doc in documents]
    missing_ids = [str(doc_id) for doc_id in document_ids if str(doc_id) not in found_ids]

    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Documents not found: {', '.join(missing_ids)}"
        )

    # 모든 문서를 거부 상태로 변경
    for document in documents:
        # 문서 상태 변경
        document.status = "승인대기"

        # 거부 메타데이터 추가
        metadata = document.file_metadata or {}
        if reason:
            metadata["reject_reason"] = reason
        metadata["rejected_by"] = str(current_user.id)
        metadata["rejected_at"] = datetime.utcnow().isoformat()
        metadata["batch_rejection"] = True
        document.file_metadata = metadata

    # 변경사항 저장
    db.commit()

    # 변경된 문서 반환
    return documents


# 문서 벡터화 API (관리자용)
@router.post("/documents/{document_id}/vectorize", response_model=Document)
def vectorize_document(
    document_id: UUID,
    full_vectorize: bool = False,
    force: bool = False,  # 유효기간 체크를 무시하고 강제로 벡터화
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 문서를 벡터화합니다.

    Args:
        document_id: 벡터화할 문서 ID
        full_vectorize: True인 경우 전체 파일 벡터화, False인 경우 요약만 벡터화 (기본값: False)
        force: True인 경우 유효기간 체크를 무시하고 강제로 벡터화 (기본값: False)
    """
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # 유효기간 체크 (force=True가 아닐 경우)
    if not force:
        today = datetime.utcnow().date()

        # 종료일이 지난 경우
        if document.end_date and document.end_date.date() < today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document has expired. Set force=True to vectorize anyway.",
            )

        # 시작일이 아직 오지 않은 경우
        if document.start_date and document.start_date.date() > today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document is not yet valid. Set force=True to vectorize anyway.",
            )

    # 파일 확인
    files = document.files
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files found for this document")

    # 요약만 벡터화하는 경우 요약 내용 확인
    if not full_vectorize and not document.summary:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document has no summary to vectorize")

    # Celery 태스크 사용하여 비동기 벡터화 작업 시작
    try:
        from app.tasks.vectorize_tasks import vectorize_document as vectorize_task
    except (ImportError, AttributeError) as e:
        # 임포트 오류 시 (Milvus 등 라이브러리 문제 발생 시)
        logging.error(f"벡터화 태스크 로드 중 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="벡터화 기능을 사용할 수 없습니다. 시스템 관리자에게 문의하세요.",
        )

    # 벡터화 작업 시작 전 메타데이터 업데이트
    metadata = document.file_metadata or {}
    metadata["vectorize_requested_by"] = str(current_user.id)
    metadata["vectorize_requested_at"] = datetime.utcnow().isoformat()
    metadata["full_vectorize"] = full_vectorize
    metadata["force_vectorize"] = force
    document.file_metadata = metadata

    # 작업 상태 설정
    document.vectorized = False  # 벡터화 작업이 완료될 때까지 False로 유지

    # 변경사항 저장
    db.commit()
    db.refresh(document)

    # Celery 작업 시작
    try:
        task = vectorize_task.delay(str(document_id))

        # 작업 ID 저장
        metadata = document.file_metadata or {}
        metadata["vectorize_task_id"] = task.id
        document.file_metadata = metadata

        db.commit()
    except Exception as e:
        logging.error(f"벡터화 작업 시작 중 오류 발생: {str(e)}")
        # 메타데이터에 오류 정보 저장
        metadata = document.file_metadata or {}
        metadata["vectorize_error"] = str(e)
        metadata["vectorize_error_time"] = datetime.utcnow().isoformat()
        document.file_metadata = metadata

        db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"벡터화 작업 시작 실패: {str(e)}"
        )

    return document


# 문서 벡터 삭제 API (관리자용)
@router.delete("/documents/{document_id}/vector", response_model=Document)
def delete_document_vector(
    document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)
):
    """관리자용 - 문서의 벡터를 삭제합니다."""
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Celery 태스크 사용하여 비동기 벡터 삭제 작업 시작
    try:
        from app.tasks.vectorize_tasks import delete_document_vectors as delete_vectors_task
    except (ImportError, AttributeError) as e:
        # 임포트 오류 시 (Milvus 등 라이브러리 문제 발생 시)
        logging.error(f"벡터 삭제 태스크 로드 중 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="벡터 삭제 기능을 사용할 수 없습니다. 시스템 관리자에게 문의하세요.",
        )

    # 작업 시작 전 메타데이터 업데이트
    metadata = document.file_metadata or {}
    metadata["vector_delete_requested_by"] = str(current_user.id)
    metadata["vector_delete_requested_at"] = datetime.utcnow().isoformat()

    # 변경사항 저장
    db.commit()

    # Celery 작업 시작
    try:
        task = delete_vectors_task.delay(str(document_id))

        # 작업 ID 저장
        metadata["vector_delete_task_id"] = task.id
        document.file_metadata = metadata

        db.commit()
    except Exception as e:
        logging.error(f"벡터 삭제 작업 시작 중 오류 발생: {str(e)}")
        # 메타데이터에 오류 정보 저장
        metadata["vector_delete_error"] = str(e)
        metadata["vector_delete_error_time"] = datetime.utcnow().isoformat()
        document.file_metadata = metadata

        db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"벡터 삭제 작업 시작 실패: {str(e)}"
        )

    return document


# 유효기간 체크하여 만료된 문서의 벡터 삭제 API
@router.post("/documents/check-validity", status_code=status.HTTP_200_OK)
def check_documents_validity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """유효기간이 지난 문서의 벡터를 자동으로 삭제합니다."""
    today = datetime.utcnow().date()

    # 유효기간이 지난 문서들 조회 (종료일이 지났거나 아직 시작되지 않은 문서)
    expired_docs_query = (
        db.query(DocumentModel)
        .filter(DocumentModel.vectorized == True)
        .filter(
            # 종료일이 지난 문서
            ((DocumentModel.end_date != None) & (DocumentModel.end_date < today))
            |
            # 시작일이 아직 오지 않은 문서
            ((DocumentModel.start_date != None) & (DocumentModel.start_date > today))
        )
    )

    expired_docs = expired_docs_query.all()

    if not expired_docs:
        return {"message": "No expired documents found with vectors", "processed_count": 0}

    # 청크 삭제 및 벡터화 상태 업데이트
    deleted_count = 0
    for doc in expired_docs:
        # 문서의 모든 청크 삭제
        db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()

        # 문서 벡터화 상태 업데이트
        doc.vectorized = False

        # 메타데이터 업데이트
        metadata = doc.file_metadata or {}
        metadata["vector_deleted_by"] = str(current_user.id)
        metadata["vector_deleted_at"] = datetime.utcnow().isoformat()
        metadata["vector_deleted_reason"] = "Document expired or not yet valid"
        doc.file_metadata = metadata

        deleted_count += 1

    # 변경사항 저장
    db.commit()

    return {"message": f"Successfully processed {deleted_count} expired documents", "processed_count": deleted_count}
