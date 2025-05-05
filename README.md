# Board RAG 시스템

문서 업로드 및 검색을 위한 RAG(Retrieval-Augmented Generation) 기반 시스템입니다.

## 시스템 구성

- **프론트엔드**: React, Tailwind CSS
- **백엔드**: FastAPI
- **데이터베이스**: PostgreSQL
- **스토리지**: MinIO
- **벡터 데이터베이스**: Milvus (향후 통합 예정)
- **컨테이너화**: Docker, Docker Compose

## 주요 기능

- 사용자 인증 (회원가입, 로그인)
- 문서 업로드 및 관리
- 문서 검색 (키워드 및 태그 기반)
- 관리자 승인 시스템
- 문서 청킹 및 벡터화 (RAG 기반)

## 시작하기

### 개발 환경 설정

1. 저장소 클론:
   ```bash
   git clone https://github.com/your-username/board-rag-system.git
   cd board-rag-system
   ```

2. 환경 변수 설정:
   ```bash
   cp env-example.txt .env
   ```
   `.env` 파일 내용을 필요에 맞게 수정하세요.

3. Docker Compose로 개발 환경 시작:
   ```bash
   docker-compose up -d
   ```

4. 서비스 접속:
   - 프론트엔드: http://localhost:3000
   - 백엔드 API: http://localhost:8000
   - MinIO 콘솔: http://localhost:9001
   - API 문서: http://localhost:8000/docs

### 프로덕션 환경 설정

1. 환경 변수 설정:
   ```bash
   cp env-example.txt .env
   ```
   `.env` 파일 내용을 프로덕션 환경에 맞게 수정하세요.

2. Docker Compose로 프로덕션 환경 시작:
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

3. 서비스 접속:
   - 웹 애플리케이션: http://your-domain.com
   - API 문서: http://your-domain.com/docs

## 데이터베이스 테이블 관리

시스템은 환경 변수 `RECREATE_TABLES`를 통해 데이터베이스 테이블 생성/재생성을 제어합니다:

- **개발 환경**: `RECREATE_TABLES=true` (기본값) - 애플리케이션 시작 시 기존 테이블을 삭제하고 새로 생성
- **프로덕션 환경**: `RECREATE_TABLES=false` - 기존 데이터 유지, 없는 테이블만 생성

이 기능은 개발 중 스키마 변경이 자주 발생할 때 유용하며, 데이터베이스 구조를 자동으로 최신 상태로 유지합니다.

### 환경 변수 설정

Docker Compose 파일이나 .env 파일에서 설정할 수 있습니다:

```yaml
# docker-compose.yml (개발 환경)
environment:
  RECREATE_TABLES: "true"
```

```yaml
# docker-compose.prod.yml (프로덕션 환경)
environment:
  RECREATE_TABLES: "false"
```

## 프로젝트 구조

```
board-rag-system/
├── board-front/           # 프론트엔드 (React)
├── board-backend/         # 백엔드 (FastAPI)
├── nginx/                 # Nginx 설정
├── docker-compose.yml     # 개발 환경 Docker Compose 설정
├── docker-compose.prod.yml # 프로덕션 환경 Docker Compose 설정
└── README.md
```

## 개발 가이드

### 백엔드 개발

백엔드는 FastAPI를 사용하여 구현되었습니다. 주요 구성은 다음과 같습니다:

- **데이터베이스 모델**: SQLAlchemy ORM
- **인증**: JWT 기반 인증
- **파일 저장소**: MinIO
- **API 문서**: Swagger UI (/docs)

자세한 내용은 `board-backend/README.md`를 참조하세요.

### 프론트엔드 개발

프론트엔드는 React와 Tailwind CSS로 구현되었습니다:

- **상태 관리**: React Hooks
- **API 통신**: Axios
- **스타일링**: Tailwind CSS

자세한 내용은 `board-front/README.md`를 참조하세요.

## 기여하기

1. 이슈 발행 또는 기존 이슈 확인
2. 개발용 브랜치 생성 (`git checkout -b feature/your-feature`)
3. 변경사항 커밋 (`git commit -m 'Add some feature'`)
4. 브랜치에 푸시 (`git push origin feature/your-feature`)
5. Pull Request 생성 