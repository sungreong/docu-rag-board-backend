# Board RAG System 백엔드

문서 업로드 및 RAG 기반 검색 시스템을 위한 백엔드 API 서버입니다.

## 기술 스택

- **FastAPI**: 웹 API 프레임워크
- **SQLAlchemy**: 데이터베이스 ORM
- **PostgreSQL**: 관계형 데이터베이스
- **MinIO**: 객체 스토리지
- **Milvus**: 벡터 데이터베이스

## 설치 방법

### 1. 가상 환경 생성 및 활성화

```bash
# 가상 환경 생성
python -m venv venv

# Windows에서 활성화
venv\Scripts\activate

# Linux/Mac에서 활성화
source venv/bin/activate
```

### 2. 패키지 설치

```bash
pip install -r requirements.txt
```

### 3. 환경 변수 설정

`env_example.txt` 파일을 참고하여 `.env` 파일을 생성하고 필요한 설정을 입력하세요.

### 4. 데이터베이스 준비

PostgreSQL 데이터베이스를 설치하고 `.env` 파일에 연결 정보를 설정하세요.

### 5. MinIO 설정

MinIO를 설치하고 `.env` 파일에 연결 정보를 설정하세요.

## 실행 방법

```bash
# 개발 서버 실행
python run.py
```

서버는 기본적으로 `http://localhost:8000`에서 실행됩니다.

## API 문서

API 문서는 서버 실행 후 다음 URL에서 확인할 수 있습니다:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 주요 API 엔드포인트

### 인증

- `POST /api/auth/signup`: 회원가입
- `POST /api/auth/login`: 로그인

### 문서 관리

- `POST /api/documents/upload`: 문서 업로드
- `GET /api/documents/mine`: 내 문서 목록 조회
- `GET /api/documents/{document_id}`: 문서 상세 조회
- `GET /api/documents/{document_id}/download`: 문서 다운로드

### 관리자 기능

- `GET /api/admin/documents`: 전체 문서 목록 조회
- `POST /api/admin/documents/{document_id}/approve`: 문서 승인
- `POST /api/admin/documents/{document_id}/reject`: 문서 거부

### 검색

- `GET /api/search`: 키워드 기반 검색
- `GET /api/search/tags`: 태그 기반 검색

### 문서 처리

- `POST /api/chunks/{document_id}`: 문서 청킹 및 벡터 생성
- `GET /api/chunks/{document_id}`: 문서의 청크 목록 조회
