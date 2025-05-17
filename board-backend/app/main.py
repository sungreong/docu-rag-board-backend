from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
import os

from app.database import engine, Base, get_db
from app.routers import auth, documents, admin, search, chunks, tasks
from app.routers import tags, admin_tags  # 태그 관련 라우터 추가
from app.initialize import create_default_admin, create_default_user, create_default_tags
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 개발 환경에서는 테이블을 재생성, 프로덕션에서는 필요에 따라 설정
RECREATE_TABLES = os.getenv("RECREATE_TABLES", "True").lower() == "true"

# 데이터베이스 테이블 생성 및 갱신
try:
    if RECREATE_TABLES:
        # 개발 환경: 테이블을 삭제하고 다시 생성
        logger.info("개발 환경 감지: RECREATE_TABLES=True")
        logger.info("기존 테이블 삭제 중...")
        Base.metadata.drop_all(bind=engine)
        logger.info("테이블 삭제 완료. 새 테이블을 생성합니다.")
    else:
        logger.info("프로덕션 환경 감지: 기존 테이블 유지, 필요한 경우 새 테이블만 생성")

    # 테이블 생성
    Base.metadata.create_all(bind=engine)
    logger.info("데이터베이스 테이블 생성 완료")

except OperationalError as e:
    logger.error(f"데이터베이스 연결 실패. 테이블을 생성할 수 없습니다. 오류: {str(e)}")
    # 가능한 경우 연결 재시도나 대체 동작 구현
    logger.info("데이터베이스 연결 문제: PostgreSQL 서비스가 실행 중인지 확인하십시오")
    logger.info(f"현재 설정된 DATABASE_URL: {os.getenv('DATABASE_URL', '미설정')}")

# FastAPI 애플리케이션 생성
app = FastAPI(
    title="Board RAG System API", description="문서 업로드 및 RAG 기반 검색 시스템을 위한 API", version="0.1.0"
)

# CORS 설정
origins = [
    "*",
    #     "http://localhost:3000",  # React 프론트엔드
    #     "http://localhost:8000",
    #     "http://127.0.0.1:3000",
    #     "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 포함
app.include_router(auth.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(chunks.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(tags.router, prefix="/api")  # 사용자 태그 라우터 추가
app.include_router(admin_tags.router, prefix="/api")  # 관리자 태그 라우터 추가


@app.get("/api/health", tags=["health"])
def health_check():
    """서버 상태 확인 엔드포인트"""
    return {"status": "ok", "message": "Server is running"}


@app.get("/", tags=["root"])
def read_root():
    """API 루트 엔드포인트"""
    return {"message": "Welcome to Board RAG System API", "docs": "/docs", "openapi": "/openapi.json"}


# 다운로드 엔드포인트를 루트 경로에도 추가 (문서 API와 동일)
@app.get("/api/download/{file_uuid}")
async def download_file_by_uuid(
    file_uuid: str,
    db: Session = Depends(get_db),
    expires: int = Query(3600, description="다운로드 URL 만료 시간(초)"),
):
    """파일 UUID로 직접 다운로드합니다."""
    # 문서 라우터의 함수 재사용
    from app.routers.documents import download_by_uuid

    return await download_by_uuid(file_uuid, db, expires)


# 애플리케이션 시작 이벤트 핸들러
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행되는 함수"""
    logger.info("애플리케이션 시작 중...")

    # 데이터베이스 세션 얻기
    db = next(get_db())
    try:
        # 기본 관리자 계정 생성
        create_default_admin(db)
        # 기본 사용자 계정 생성
        create_default_user(db)
        # 기본 시스템 태그 생성
        create_default_tags(db)
    except Exception as e:
        logger.error(f"초기화 과정에서 오류 발생: {str(e)}")
    finally:
        db.close()

    # MinIO 버킷 존재 확인
    try:
        from app.storage import ensure_bucket_exists

        if ensure_bucket_exists():
            logger.info("MinIO 버킷 확인 완료")
        else:
            logger.warning("MinIO 버킷을 확인할 수 없습니다")
    except Exception as e:
        logger.error(f"MinIO 버킷 확인 중 오류 발생: {str(e)}")

    # Celery 작업자 초기화
    try:
        from app.celery_worker import celery

        logger.info(f"Celery 작업자 초기화 완료: {celery.conf.broker_url}")
    except Exception as e:
        logger.error(f"Celery 작업자 초기화 중 오류 발생: {str(e)}")
