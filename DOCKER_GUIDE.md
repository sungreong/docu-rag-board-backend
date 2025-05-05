# Docker 환경 사용 가이드

이 가이드는 Docker Compose를 사용하여 Board RAG 시스템을 실행하는 방법을 설명합니다.

## 사전 요구사항

- [Docker](https://docs.docker.com/get-docker/) 설치
- [Docker Compose](https://docs.docker.com/compose/install/) 설치

## 개발 환경 실행하기

개발 환경은 실시간 코드 변경 감지 및 핫 리로딩을 지원합니다.

1. 환경 변수 설정:

   ```bash
   cp env-example.txt .env
   ```

   필요에 따라 `.env` 파일의 설정을 변경하세요.
2. Docker Compose로 시스템 시작:

   ```bash
   docker-compose up -d
   ```

   이 명령어는 PostgreSQL, MinIO, 백엔드, 프론트엔드 서비스를 시작합니다.
3. 로그 확인:

   ```bash
   # 모든 서비스의 로그 확인
   docker-compose logs -f

   # 특정 서비스의 로그 확인
   docker-compose logs -f backend
   docker-compose logs -f frontend
   ```
4. 서비스 접속:

   - 프론트엔드: http://localhost:3000
   - 백엔드 API: http://localhost:8000/api
   - API 문서: http://localhost:8000/docs
   - MinIO 콘솔: http://localhost:9001 (minioadmin/minioadmin)
   - PostgreSQL: localhost:5432 (postgres/password)
5. 서비스 중지:

   ```bash
   docker-compose down
   ```

## 프로덕션 환경 실행하기

프로덕션 환경은 최적화된 빌드와 Nginx를 통한 리버스 프록시를 포함합니다.

1. 환경 변수 설정:

   ```bash
   cp env-example.txt .env
   ```

   프로덕션에 맞게 `.env` 파일의 설정을 변경하세요 (특히 암호와 보안 키).
2. Docker Compose로 프로덕션 시스템 시작:

   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```
3. 서비스 접속:

   - 웹 애플리케이션: http://localhost (또는 서버 도메인)
   - API 문서: http://localhost/docs (또는 서버 도메인/docs)
4. 서비스 중지:

   ```bash
   docker-compose -f docker-compose.prod.yml down
   ```

## 볼륨 및 데이터 관리

Docker Compose는 다음 볼륨을 생성하여 데이터를 영구적으로 저장합니다:

- `postgres-data`: PostgreSQL 데이터베이스 파일
- `minio-data`: MinIO에 저장된 문서 파일

볼륨 관리:

```bash
# 볼륨 목록 확인
docker volume ls

# 볼륨 삭제 (모든 데이터가 사라집니다!)
docker volume rm board-rag-system_postgres-data board-rag-system_minio-data
```

## 컨테이너 관리

```bash
# 컨테이너 상태 확인
docker-compose ps

# 특정 서비스 재시작
docker-compose restart backend

# 특정 서비스의 로그 확인
docker-compose logs -f backend

# 특정 서비스의 컨테이너에 접속
docker-compose exec backend bash
docker-compose exec postgres psql -U postgres -d board_rag
```

## 문제 해결

1. **컨테이너 시작 실패**: 로그를 확인하여 오류 메시지 확인

   ```bash
   docker-compose logs service-name
   ```
2. **데이터베이스 연결 오류**: PostgreSQL 서비스가 정상적으로 시작되었는지 확인

   ```bash
   docker-compose ps
   docker-compose logs postgres
   ```
3. **API 연결 오류**: 백엔드 서비스가 정상적으로 시작되었는지 확인

   ```bash
   docker-compose logs backend
   ```
4. **환경 초기화**: 모든 컨테이너와 볼륨을 삭제하고 처음부터 다시 시작

   ```bash
   docker-compose down -v
   docker-compose up -d
   ```
