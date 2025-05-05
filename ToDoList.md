# Board RAG 시스템 개발 ToDo 리스트

## 전체 개발 로드맵

### 1단계: 백엔드 초기 설정 및 기본 API 구현
- [x] 백엔드 프로젝트 구조 설정 (FastAPI)
- [x] 데이터베이스 연결 설정 (PostgreSQL)
- [x] MinIO 연결 설정
- [x] 기본 인증 시스템 구현
- [x] 문서 업로드 API 구현
- [x] 문서 목록 조회 API 구현

### 2단계: 프론트엔드 연결 및 기본 기능 구현
- [x] 프론트엔드-백엔드 API 연결 설정
- [ ] 파일 업로드 기능 구현
- [ ] 문서 목록 조회 기능 구현
- [ ] 검색 기능 기본 구현

### 3단계: 문서 처리 및 고급 기능
- [x] 문서 청킹 기능 구현
- [ ] 벡터 저장 및 검색 기능 구현
- [ ] 태그 관리 기능 구현
- [x] 관리자 승인 시스템 구현

### 4단계: RAG 시스템 통합
- [ ] 문서 간 연관성 그래프 구현
- [ ] RAG 파이프라인 연결
- [ ] 채팅 인터페이스 연결

## 세부 작업 계획

### 백엔드 (FastAPI)

#### 1. 프로젝트 초기 설정
- [x] FastAPI 프로젝트 구조 생성
- [x] 필요한 패키지 설치 (fastapi, uvicorn, sqlalchemy, psycopg2-binary, python-jose, passlib, python-multipart 등)
- [x] 환경 설정 파일 구성 (.env 등)
- [x] Docker 설정 (선택적)

#### 2. 데이터베이스 연결 설정
- [x] PostgreSQL 연결 설정
- [x] 데이터 모델 정의 (SQLAlchemy)
  - [x] User 모델 (id, email, password_hash, role)
  - [x] Document 모델 (id, user_id, title, tags, file_path, status, created_at)
  - [x] DocumentChunk 모델 (id, doc_id, chunk_text, vector_id)
- [ ] 데이터베이스 마이그레이션 도구 설정 (Alembic)

#### 3. 스토리지 연결 설정
- [x] MinIO 클라이언트 설정
- [x] 파일 업로드/다운로드 유틸리티 함수 구현

#### 4. 인증 시스템
- [x] 회원가입 API (`POST /auth/signup`)
- [x] 로그인 API (`POST /auth/login`)
- [x] JWT 토큰 검증 미들웨어
- [x] 역할 기반 접근 제어 (RBAC) 구현

#### 5. 문서 관리 API
- [x] 문서 업로드 API (`POST /documents/upload`)
- [x] 내 문서 조회 API (`GET /documents/mine`)
- [x] 문서 다운로드 API (`GET /documents/{doc_id}/download`)
- [x] 관리자용 문서 목록 API (`GET /admin/documents`)
- [x] 문서 승인/거부 API (`POST /admin/documents/{doc_id}/approve`, `POST /admin/documents/{doc_id}/reject`)

#### 6. 문서 처리 API
- [x] 문서 텍스트 추출 유틸리티 (PDF, DOCX 등)
- [x] 문서 청킹 API (`POST /documents/{doc_id}/chunk`)
- [ ] 벡터 저장 연동 (Milvus 또는 대체 벡터 DB)

#### 7. 검색 API
- [x] 키워드 기반 검색 API (`GET /search`)
- [x] 벡터 기반 유사 문서 검색 API (`GET /search/similar`)
- [x] 태그 기반 필터링 지원

### 프론트엔드 연결

#### 1. API 클라이언트 설정
- [x] Axios 또는 fetch 기반 API 클라이언트 구성
- [x] 인증 토큰 관리 시스템 구현
- [x] API 요청/응답 인터셉터 설정

#### 2. 파일 업로드 기능
- [ ] 파일 업로드 폼에 백엔드 API 연결
- [ ] 멀티파트 폼 데이터 처리
- [ ] 업로드 진행 상태 표시 구현

#### 3. 문서 목록 기능
- [ ] 내 문서 목록에 백엔드 API 연결
- [ ] 문서 상태 표시 구현 (승인대기/승인완료)
- [ ] 문서 다운로드 기능 연결

#### 4. 검색 기능
- [ ] 검색 API 연결 구현
- [ ] 검색 결과 표시 구현
- [ ] 태그 기반 필터링 구현

### 시스템 배포

#### 1. Docker 컨테이너화
- [x] 백엔드 서비스 Dockerfile 작성
- [x] 프론트엔드 서비스 Dockerfile 작성
- [x] Docker Compose 개발 환경 설정
- [x] Docker Compose 프로덕션 환경 설정

#### 2. 웹 서버 설정
- [x] Nginx 설정 (리버스 프록시)
- [ ] HTTPS 설정 (SSL 인증서)
- [x] 로드 밸런싱 및 보안 설정

#### 3. CI/CD
- [ ] GitHub Actions 파이프라인 설정
- [ ] 자동 테스트 및 배포 구성
- [ ] 모니터링 및 로깅 설정

## 현재 작업 진행 상황

### 완료된 작업
- 프론트엔드 초기 설정 완료 (React, Tailwind CSS)
- 백엔드 프로젝트 구조 생성 및 기본 설정 완료
- 데이터베이스 모델 정의 완료
- 기본 인증 시스템 구현 완료
  - 기본 관리자 계정 자동 생성 기능 추가
- 문서 관리 API 구현 완료
  - 다중 파일 업로드 지원 추가
  - 파일 형식 검증 기능 추가
  - 지원되는 파일 형식 조회 API 추가
- 검색 API 구현 완료
  - 태그 기반 검색 개선
  - 정렬 및 필터링 옵션 추가
- 문서 청킹 API 구현 완료
- 프론트엔드 API 클라이언트 구현 완료 (Axios 기반)
- Docker 컨테이너화 및 Docker Compose 설정 완료
- DocumentChunk 모델의 'metadata' 필드명 충돌 오류 수정 ('chunk_metadata'로 변경)
- email-validator 패키지 누락 오류 수정 (Pydantic 이메일 검증용)
- 문서 모델 필드 확장 (summary, start_date, end_date, 다중 파일 지원)
- 관리자 API 개선 (거부 이유 저장, 문서 삭제 기능 추가)
- 데이터베이스 테이블 자동 생성/재생성 기능 추가 (개발/프로덕션 환경 분리)

### 진행 중인 작업
- 프론트엔드 컴포넌트와 API 연결 중
- 벡터 기반 검색 기능 구현 (Milvus 연동)
- 데이터베이스 마이그레이션 도구 설정 (Alembic)

### 다음 작업
- 파일 업로드 폼 컴포넌트와 API 연결
- 문서 목록 컴포넌트와 API 연결
- 검색 컴포넌트와 API 연결
- 실제 배포 환경 테스트 및 버그 수정 