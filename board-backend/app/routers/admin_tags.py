from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from datetime import datetime

from app.database import get_db
from app.auth import get_current_admin_user, get_current_active_user
from app.models import Tag, UserTag, UserTagQuota, User
from app.schemas import TagResponse, TagCreate, TagUpdate, UserTagQuotaUpdate, UserTagQuotaResponse, Message

router = APIRouter(prefix="/admin/tags", tags=["admin-tags"])


@router.get("/", response_model=List[TagResponse])
def get_all_tags(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    """모든 태그 목록을 조회합니다."""
    query = db.query(Tag)

    # 검색어가 있는 경우
    if search:
        search_pattern = f"%{search.lower()}%"
        query = query.filter(
            func.lower(Tag.name).like(search_pattern) | func.lower(Tag.description).like(search_pattern)
        )

    # 정렬 및 페이지네이션
    total = query.count()
    tags = query.order_by(Tag.is_system.desc(), Tag.name).offset(skip).limit(limit).all()

    return tags


@router.get("/system", response_model=List[TagResponse])
async def get_system_tags(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """시스템 태그 목록을 조회합니다."""
    query = db.query(Tag).filter(Tag.is_system == True)

    if search:
        query = query.filter(Tag.name.ilike(f"%{search}%"))

    total = query.count()
    tags = query.offset(skip).limit(limit).all()

    return tags


@router.get("/user", response_model=List[TagResponse])
async def get_user_tags(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """사용자 생성 태그 목록을 조회합니다."""
    query = db.query(Tag).filter(Tag.is_system == False)

    if search:
        query = query.filter(Tag.name.ilike(f"%{search}%"))

    total = query.count()
    tags = query.offset(skip).limit(limit).all()

    return tags


@router.post("/system", response_model=TagResponse)
async def create_system_tag(
    tag: TagCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)
):
    """새로운 시스템 태그를 생성합니다."""
    # 태그 이름 중복 체크
    existing_tag = db.query(Tag).filter(Tag.name == tag.name).first()
    if existing_tag:
        raise HTTPException(status_code=400, detail="이미 존재하는 태그 이름입니다.")

    db_tag = Tag(name=tag.name, description=tag.description, is_system=True, created_by=current_user.id)
    db.add(db_tag)
    db.commit()
    db.refresh(db_tag)
    return db_tag


@router.put("/system/{tag_id}", response_model=TagResponse)
async def update_system_tag(
    tag_id: UUID,
    tag_update: TagUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """시스템 태그를 수정합니다."""
    db_tag = db.query(Tag).filter(Tag.id == tag_id, Tag.is_system == True).first()
    if not db_tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    if tag_update.name and tag_update.name != db_tag.name:
        # 태그 이름 중복 체크
        existing_tag = db.query(Tag).filter(Tag.name == tag_update.name).first()
        if existing_tag:
            raise HTTPException(status_code=400, detail="이미 존재하는 태그 이름입니다.")
        db_tag.name = tag_update.name

    if tag_update.description is not None:
        db_tag.description = tag_update.description

    db.commit()
    db.refresh(db_tag)
    return db_tag


@router.delete("/system/{tag_id}", response_model=Message)
async def delete_system_tag(
    tag_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)
):
    """시스템 태그를 삭제합니다."""
    db_tag = db.query(Tag).filter(Tag.id == tag_id, Tag.is_system == True).first()
    if not db_tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    # 연관된 사용자 태그도 함께 삭제
    db.query(UserTag).filter(UserTag.tag_id == tag_id).delete()
    db.delete(db_tag)
    db.commit()

    return {"message": "태그가 성공적으로 삭제되었습니다."}


@router.get("/quota/{user_id}", response_model=UserTagQuotaResponse)
async def get_user_tag_quota(
    user_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)
):
    """사용자의 태그 할당량을 조회합니다."""
    quota = db.query(UserTagQuota).filter(UserTagQuota.user_id == user_id).first()
    if not quota:
        raise HTTPException(status_code=404, detail="태그 할당량 정보를 찾을 수 없습니다.")
    return quota


@router.put("/quota/{user_id}", response_model=UserTagQuotaResponse)
async def update_user_tag_quota(
    user_id: UUID,
    quota_update: UserTagQuotaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """사용자의 태그 할당량을 수정합니다."""
    quota = db.query(UserTagQuota).filter(UserTagQuota.user_id == user_id).first()
    if not quota:
        # 할당량 정보가 없으면 새로 생성
        quota = UserTagQuota(user_id=user_id, max_tags=quota_update.max_tags, updated_by=current_user.id)
        db.add(quota)
    else:
        quota.max_tags = quota_update.max_tags
        quota.updated_by = current_user.id
        quota.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(quota)
    return quota


@router.get("/quota", response_model=List[UserTagQuotaResponse])
def get_all_user_tag_quotas(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """관리자용 - 모든 사용자의 태그 할당량을 조회합니다."""
    quotas = db.query(UserTagQuota).offset(skip).limit(limit).all()
    return quotas
