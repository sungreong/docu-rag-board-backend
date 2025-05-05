from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, desc, cast, String

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


# 문서 내용 기반 검색 API (DocumentChunk에서 검색)
@router.get("/content", response_model=List[SearchResult])
def search_document_content(
    keyword: str,
    tags: Optional[List[str]] = Query(None),
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # 기본 쿼리 - DocumentChunk와 Document 조인
    chunks_query = (
        db.query(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(Document.status == "approved")
    )

    # 키워드로 청크 내용 검색
    if keyword:
        chunks_query = chunks_query.filter(DocumentChunk.chunk_text.ilike(f"%{keyword}%"))

    # 태그 필터링
    if tags:
        for tag in tags:
            chunks_query = chunks_query.filter(Document.tags.any(func.lower(tag)))

    # 중복 제거를 위해 document_id로 그룹화하고 관련성 점수 계산
    document_ids = set()
    document_scores = {}

    # 페이지네이션 관련 변수
    chunk_results = chunks_query.order_by(desc(func.similarity(DocumentChunk.chunk_text, keyword))).all()

    documents = []
    for chunk, doc in chunk_results:
        if doc.id not in document_ids:
            document_ids.add(doc.id)
            # 관련성 점수 계산 (문서 청크와 키워드 간의 유사도)
            relevance_score = func.similarity(chunk.chunk_text, keyword)
            document_scores[doc.id] = relevance_score
            documents.append(doc)

            # 페이지네이션 적용
            if len(documents) >= limit:
                break

    # 결과 포맷팅
    results = []
    for doc in documents[skip : skip + limit]:
        # 청크 텍스트에서 키워드 주변 텍스트 추출 (하이라이트)
        highlights = []
        doc_chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id, DocumentChunk.chunk_text.ilike(f"%{keyword}%"))
            .limit(3)
            .all()
        )

        for chunk in doc_chunks:
            # 간단한 하이라이트 생성
            text = chunk.chunk_text
            keyword_lower = keyword.lower()
            start_pos = text.lower().find(keyword_lower)
            if start_pos >= 0:
                # 키워드 앞뒤 50자 정도를 표시
                start = max(0, start_pos - 50)
                end = min(len(text), start_pos + len(keyword) + 50)
                context = text[start:end]

                # 키워드가 중간에 잘리지 않도록 조정
                if start > 0:
                    context = "..." + context
                if end < len(text):
                    context = context + "..."

                highlights.append(context)

        result = SearchResult(
            document=doc,
            relevance_score=float(document_scores.get(doc.id, 0)),
            highlights=highlights if highlights else None,
        )
        results.append(result)

    return results


# 유사 문서명 검색 API
@router.get("/similar-title", response_model=List[SearchResult])
def search_similar_title(
    title: str,
    tags: Optional[List[str]] = Query(None),
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # 기본 쿼리 - 승인된 문서만 검색
    query = db.query(Document, func.similarity(Document.title, title).label("similarity")).filter(
        Document.status == "approved"
    )

    # 태그 필터링
    if tags:
        for tag in tags:
            query = query.filter(Document.tags.any(func.lower(tag)))

    # 유사도 점수를 기준으로 정렬
    documents = query.order_by(desc("similarity")).offset(skip).limit(limit).all()

    # 결과 포맷팅
    results = []
    for doc, similarity in documents:
        result = SearchResult(
            document=doc,
            relevance_score=float(similarity),
            highlights=None,
        )
        results.append(result)

    return results


# 패턴 검색 API (와일드카드 사용)
@router.get("/pattern", response_model=List[SearchResult])
def search_by_pattern(
    pattern: str,
    tags: Optional[List[str]] = Query(None),
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # 와일드카드 * ? 를 SQL LIKE 패턴으로 변환
    sql_pattern = pattern.replace("*", "%").replace("?", "_")

    # 기본 쿼리 - 승인된 문서만 검색
    query = db.query(Document).filter(Document.status == "approved")

    # 패턴 검색 적용
    query = query.filter(Document.title.ilike(sql_pattern))

    # 태그 필터링
    if tags:
        for tag in tags:
            query = query.filter(Document.tags.any(func.lower(tag)))

    # 쿼리 실행
    documents = query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()

    # 결과 포맷팅
    results = []
    for doc in documents:
        result = SearchResult(
            document=doc,
            relevance_score=None,
            highlights=None,
        )
        results.append(result)

    return results
