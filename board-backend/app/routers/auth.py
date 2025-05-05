from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import authenticate_user, create_access_token, get_password_hash, verify_password
from app.config import settings
from app.schemas import Token, UserCreate, User
from app.models import User as UserModel

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=User)
def signup(user: UserCreate, db: Session = Depends(get_db)):
    # 사용자 이메일 중복 확인
    db_user = db.query(UserModel).filter(UserModel.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    # 새 사용자 생성
    hashed_password = get_password_hash(user.password)
    db_user = UserModel(
        email=user.email, hashed_password=hashed_password, name=user.name, contact_email=user.contact_email
    )

    # 데이터베이스에 저장
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.post("/login", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 사용자 인증
    user = db.query(UserModel).filter(UserModel.email == form_data.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 비밀번호 확인
    if not authenticate_user(db, form_data.username, form_data.password):
        # 승인 여부 확인 (비밀번호가 일치하는 경우에만)
        if verify_password(form_data.password, user.hashed_password) and not user.is_approved and user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your account is waiting for approval. Please contact administrator.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 토큰 만료 시간
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    # 액세스 토큰 생성
    access_token = create_access_token(data={"sub": str(user.id)}, expires_delta=access_token_expires)

    # User 객체로 변환
    user_response = User(
        id=user.id,
        email=user.email,
        role=user.role,
        name=user.name,
        contact_email=user.contact_email,
        is_active=user.is_active,
        is_approved=user.is_approved,
        created_at=user.created_at,
    )

    return {"access_token": access_token, "token_type": "bearer", "user": user_response}
