from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.database import get_db
from app.auth import get_current_active_user
from app.schemas import SearchResult
from app.models import Document, User, DocumentChunk

router = APIRouter(prefix="/search", tags=["search"])


# 키워드 기반 검색 API
@router.get("", response_model=List[SearchResult])
def search_documents(
    keyword: str,
    tags: Optional[List[str]] = Query(None),
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # 기본 쿼리 - 승인된 문서만 검색
    query = db.query(Document).filter(Document.status == "approved")

    # 키워드 검색 (제목, 태그에서 검색)
    if keyword:
        query = query.filter(
            or_(
                Document.title.ilike(f"%{keyword}%"),
                Document.tags.any(func.lower(keyword)),  # PostgreSQL의 array에서 검색
            )
        )

    # 태그 필터링
    if tags:
        for tag in tags:
            query = query.filter(Document.tags.any(func.lower(tag)))

    # 페이지네이션 및 실행
    documents = query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()

    # 결과 포맷팅
    results = []
    for doc in documents:
        # 검색 결과 형식으로 변환
        result = SearchResult(
            document=doc,
            relevance_score=None,  # 단순 키워드 검색에서는 관련성 점수 없음
            highlights=None,  # 하이라이트 기능은 향후 구현
        )
        results.append(result)

    return results


# 태그 기반 검색 API
@router.get("/tags", response_model=List[SearchResult])
def search_by_tags(
    tags: List[str] = Query(...),
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # 승인된 문서 중에서 태그로 검색
    query = db.query(Document).filter(Document.status == "approved")

    # 각 태그에 대해 필터 적용
    for tag in tags:
        query = query.filter(Document.tags.any(func.lower(tag)))

    # 쿼리 실행
    documents = query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()

    # 결과 포맷팅
    results = []
    for doc in documents:
        result = SearchResult(document=doc, relevance_score=None, highlights=None)
        results.append(result)

    return results
