from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from uuid import UUID

from app.database import get_db
from app.auth import get_current_active_user
from app.models import Tag, UserTag, UserTagQuota, User
from app.schemas import TagResponse, TagCreate, UserTagResponse, Message, UserTagQuotaResponse

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/available", response_model=List[TagResponse])
async def get_available_tags(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """사용 가능한 모든 태그 목록을 조회합니다 (시스템 태그 + 내가 만든 태그)."""
    query = db.query(Tag).filter(
        (Tag.is_system == True) | ((Tag.is_system == False) & (Tag.created_by == current_user.id))
    )

    if search:
        query = query.filter(Tag.name.ilike(f"%{search}%"))

    total = query.count()
    tags = query.offset(skip).limit(limit).all()

    return tags


@router.get("/my", response_model=List[UserTagResponse])
async def get_my_tags(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """내가 사용 중인 태그 목록을 조회합니다."""
    query = db.query(UserTag).filter(UserTag.user_id == current_user.id)

    if search:
        query = query.join(Tag).filter(Tag.name.ilike(f"%{search}%"))

    total = query.count()
    user_tags = query.offset(skip).limit(limit).all()

    return user_tags


@router.post("/add/{tag_id}", response_model=UserTagResponse)
async def add_tag(tag_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """기존 태그를 내 태그로 추가합니다."""
    # 태그 존재 여부 확인
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    # 이미 추가된 태그인지 확인
    existing = db.query(UserTag).filter(UserTag.user_id == current_user.id, UserTag.tag_id == tag_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 추가된 태그입니다.")

    # 태그 할당량 확인
    quota = db.query(UserTagQuota).filter(UserTag.user_id == current_user.id).first()
    current_count = db.query(UserTag).filter(UserTag.user_id == current_user.id).count()

    if quota and current_count >= quota.max_tags:
        raise HTTPException(status_code=400, detail="태그 할당량을 초과했습니다.")

    # 태그 추가
    user_tag = UserTag(user_id=current_user.id, tag_id=tag_id)
    db.add(user_tag)
    db.commit()
    db.refresh(user_tag)

    return user_tag


@router.post("/create", response_model=UserTagResponse)
async def create_and_add_tag(
    tag: TagCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    """새로운 태그를 생성하고 내 태그로 추가합니다."""
    # 태그 이름 중복 체크
    existing_tag = db.query(Tag).filter(Tag.name == tag.name).first()
    if existing_tag:
        raise HTTPException(status_code=400, detail="이미 존재하는 태그 이름입니다.")

    # 태그 할당량 확인
    quota = db.query(UserTagQuota).filter(UserTag.user_id == current_user.id).first()
    current_count = db.query(UserTag).filter(UserTag.user_id == current_user.id).count()

    if quota and current_count >= quota.max_tags:
        raise HTTPException(status_code=400, detail="태그 할당량을 초과했습니다.")

    # 새 태그 생성
    new_tag = Tag(name=tag.name, description=tag.description, is_system=False, created_by=current_user.id)
    db.add(new_tag)
    db.commit()
    db.refresh(new_tag)

    # 생성한 태그를 사용자 태그로 추가
    user_tag = UserTag(user_id=current_user.id, tag_id=new_tag.id)
    db.add(user_tag)
    db.commit()
    db.refresh(user_tag)

    return user_tag


@router.delete("/remove/{tag_id}", response_model=Message)
async def remove_tag(
    tag_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    """내 태그 목록에서 태그를 제거합니다."""
    user_tag = db.query(UserTag).filter(UserTag.user_id == current_user.id, UserTag.tag_id == tag_id).first()

    if not user_tag:
        raise HTTPException(status_code=404, detail="태그를 찾을 수 없습니다.")

    db.delete(user_tag)
    db.commit()

    return {"message": "태그가 성공적으로 제거되었습니다."}


@router.get("/quota", response_model=Dict[str, int])
async def get_my_tag_quota(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """현재 사용자의 태그 할당량 정보를 조회합니다."""
    # 태그 할당량 정보 조회
    quota = db.query(UserTagQuota).filter(UserTagQuota.user_id == current_user.id).first()
    if not quota:
        quota = UserTagQuota(
            user_id=current_user.id,
            max_tags=20,  # 기본값 20
        )
        db.add(quota)
        db.commit()
        db.refresh(quota)

    # 사용자 태그 개수
    user_tag_count = db.query(func.count(UserTag.id)).filter(UserTag.user_id == current_user.id).scalar()

    return {
        "total": user_tag_count,
        "quota": quota.max_tags,
        "used": user_tag_count,
        "remaining": max(0, quota.max_tags - user_tag_count),
    }
