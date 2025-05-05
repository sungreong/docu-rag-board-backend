import logging
from sqlalchemy.orm import Session
from app.models import User
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
            email=settings.DEFAULT_ADMIN_EMAIL, hashed_password=hashed_password, role="admin", is_active=True
        )

        # 데이터베이스에 저장
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

        logger.info(f"기본 관리자 계정이 성공적으로 생성되었습니다: {settings.DEFAULT_ADMIN_EMAIL}")
    except Exception as e:
        db.rollback()
        logger.error(f"관리자 계정 생성 중 오류 발생: {str(e)}")
