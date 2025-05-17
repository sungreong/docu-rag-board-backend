import logging
from sqlalchemy.orm import Session
from app.models import User, Tag
from app.auth import get_password_hash
from app.config import settings

logger = logging.getLogger(__name__)


def create_default_admin(db: Session):
    """
    기본 관리자 계정이 없으면 생성합니다.
    애플리케이션 시작 시 호출됩니다.
    """
    if not settings.CREATE_DEFAULT_ADMIN:
        logger.info("기본 관리자 계정 생성이 비활성화되어 있습니다.")
        return

    # 이미 관리자 계정이 있는지 확인
    existing_admin = db.query(User).filter(User.role == "admin").first()
    if existing_admin:
        logger.info(f"관리자 계정이 이미 존재합니다: {existing_admin.email}")
        return

    # 이미 동일한 이메일의 사용자가 있는지 확인
    existing_user = db.query(User).filter(User.email == settings.DEFAULT_ADMIN_EMAIL).first()
    if existing_user:
        logger.warning(f"해당 이메일을 사용하는 계정이 이미 존재합니다: {settings.DEFAULT_ADMIN_EMAIL}")
        return

    try:
        # 비밀번호 해싱
        hashed_password = get_password_hash(settings.DEFAULT_ADMIN_PASSWORD)

        # 관리자 계정 생성
        admin_user = User(
            email=settings.DEFAULT_ADMIN_EMAIL,
            hashed_password=hashed_password,
            role="admin",
            is_active=True,
            is_approved=True,
            name="관리자",
        )

        # 데이터베이스에 저장
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

        logger.info(f"기본 관리자 계정이 성공적으로 생성되었습니다: {settings.DEFAULT_ADMIN_EMAIL}")
    except Exception as e:
        db.rollback()
        logger.error(f"관리자 계정 생성 중 오류 발생: {str(e)}")


def create_default_user(db: Session):
    """
    기본 사용자 계정이 없으면 생성합니다.
    애플리케이션 시작 시 호출됩니다.
    """

    if not settings.CREATE_DEFAULT_USER:
        logger.info("기본 사용자 계정 생성이 비활성화되어 있습니다.")
        return

    existing_user = db.query(User).filter(User.email == settings.DEFAULT_USER_EMAIL).first()

    if existing_user:
        logger.warning(f"해당 이메일을 사용하는 계정이 이미 존재합니다: {settings.DEFAULT_USER_EMAIL}")
        return

    try:
        # 비밀번호 해싱
        hashed_password = get_password_hash(settings.DEFAULT_USER_PASSWORD)

        # 사용자 생성
        default_user = User(
            email=settings.DEFAULT_USER_EMAIL,
            name=settings.DEFAULT_USER_NAME,
            hashed_password=hashed_password,
            role="user",
            is_active=True,
            is_approved=True,
        )

        # 데이터베이스에 저장
        db.add(default_user)
        db.commit()
        db.refresh(default_user)

        logger.info(f"기본 사용자 계정이 성공적으로 생성되었습니다: {settings.DEFAULT_USER_EMAIL}")
    except Exception as e:
        db.rollback()
        logger.error(f"사용자 계정 생성 중 오류 발생: {str(e)}")


def create_default_tags(db: Session) -> None:
    """기본 시스템 태그를 생성합니다."""
    default_tags = [
        {"name": "공지사항", "description": "공지사항 관련 문서", "is_system": True},
        {"name": "중요", "description": "중요 문서", "is_system": True},
        {"name": "보고서", "description": "각종 보고서", "is_system": True},
        {"name": "인사", "description": "인사 관련 문서", "is_system": True},
        {"name": "회계", "description": "회계/재무 관련 문서", "is_system": True},
        {"name": "개발", "description": "개발 관련 문서", "is_system": True},
        {"name": "마케팅", "description": "마케팅 관련 문서", "is_system": True},
        {"name": "영업", "description": "영업 관련 문서", "is_system": True},
        {"name": "프로젝트", "description": "프로젝트 관련 문서", "is_system": True},
        {"name": "회의", "description": "회의 관련 문서", "is_system": True},
        {"name": "계약", "description": "계약 관련 문서", "is_system": True},
        {"name": "교육", "description": "교육/훈련 관련 문서", "is_system": True},
        {"name": "정책", "description": "정책/지침 관련 문서", "is_system": True},
        {"name": "규정", "description": "규정/규칙 관련 문서", "is_system": True},
    ]

    for tag_data in default_tags:
        # 이미 존재하는 태그인지 확인
        existing_tag = db.query(Tag).filter(Tag.name == tag_data["name"]).first()
        if not existing_tag:
            tag = Tag(**tag_data)
            db.add(tag)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error creating default tags: {str(e)}")
