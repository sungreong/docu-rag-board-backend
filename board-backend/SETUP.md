# Board RAG 시스템 환경 설정 가이드

이 문서는 Board RAG 시스템의 백엔드 환경 설정 방법을 안내합니다.

## 1. PostgreSQL 설정

### 1.1 PostgreSQL 설치

#### Windows
1. PostgreSQL 다운로드 페이지(https://www.enterprisedb.com/downloads/postgres-postgresql-downloads)에서 최신 버전을 다운로드합니다.
2. 설치 프로그램을 실행하고 기본 설정으로 설치합니다.
3. 설치 중 비밀번호를 설정할 때 기억하기 쉬운 비밀번호를 입력하세요.

#### Linux(Ubuntu)
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

### 1.2 데이터베이스 생성

#### Windows
1. pgAdmin을 실행합니다.
2. 서버에 연결합니다.
3. 데이터베이스 생성:
   - 데이터베이스 노드에서 우클릭 > "Create" > "Database..."
   - 데이터베이스 이름: `board_rag`
   - 저장합니다.

#### Linux/Mac
```bash
sudo -u postgres psql
CREATE DATABASE board_rag;
\q
```

### 1.3 환경 변수 설정
`.env` 파일을 생성하고 다음과 같은 내용을 입력합니다:

```
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password_here
DB_NAME=board_rag
```

## 2. MinIO 설정

### 2.1 MinIO 설치 및 실행

#### Windows
1. [MinIO 다운로드 페이지](https://min.io/download)에서 Windows 버전을 다운로드합니다.
2. 다운로드한 파일을 적절한 위치에 압축 해제합니다.
3. 명령 프롬프트를 열고 압축 해제한 위치로 이동합니다.
4. 다음 명령을 실행하여 MinIO 서버를 시작합니다:
   ```cmd
   minio.exe server C:\minio\data --console-address ":9001"
   ```

#### Linux/Mac
```bash
wget https://dl.min.io/server/minio/release/linux-amd64/minio
chmod +x minio
./minio server /data --console-address ":9001"
```

### 2.2 MinIO 설정
- 기본 엑세스 키: `minioadmin`
- 기본 시크릿 키: `minioadmin`
- MinIO 콘솔: http://localhost:9001
- API 엔드포인트: http://localhost:9000

### 2.3 버킷 생성
1. MinIO 콘솔(http://localhost:9001)에 접속합니다.
2. 기본 자격 증명으로 로그인합니다:
   - 액세스 키: `minioadmin`
   - 시크릿 키: `minioadmin`
3. 왼쪽 메뉴에서 "Buckets"를 클릭합니다.
4. "+ Create Bucket" 버튼을 클릭합니다.
5. 버킷 이름을 `documents`로 입력하고 생성합니다.

### 2.4 환경 변수 설정
`.env` 파일에 다음 내용을 추가합니다:

```
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_SECURE=false
MINIO_BUCKET_NAME=documents
```

## 3. Milvus 설정 (향후 구현)

### 3.1 Docker를 사용한 Milvus 설치
Docker와 Docker Compose가 설치되어 있어야 합니다.

```bash
# docker-compose.yml 생성
mkdir -p milvus && cd milvus
wget https://github.com/milvus-io/milvus/releases/download/v2.3.2/milvus-standalone-docker-compose.yml -O docker-compose.yml

# Milvus 시작
docker-compose up -d
```

### 3.2 환경 변수 설정
`.env` 파일에 다음 내용을 추가합니다:

```
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=document_chunks
```

## 4. 백엔드 서버 실행

### 4.1 가상 환경 생성 및 활성화
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python -m venv venv
source venv/bin/activate
```

### 4.2 의존성 설치
```bash
pip install -r requirements.txt
```

### 4.3 서버 실행
```bash
python run.py
```

서버는 기본적으로 `http://localhost:8000`에서 실행됩니다.
API 문서는 `http://localhost:8000/docs`에서 확인할 수 있습니다.

## 5. 프론트엔드 연결 테스트

### 5.1 프론트엔드 실행
```bash
cd board-front
npm install
npm start
```

### 5.2 API 연결 테스트
1. 브라우저 개발자 도구 콘솔에서 다음을 실행하여 API 연결을 테스트할 수 있습니다:
   ```javascript
   fetch('http://localhost:8000/api/health')
     .then(response => response.json())
     .then(data => console.log(data));
   ```

2. 결과로 `{status: "ok", message: "Server is running"}`가 표시되면 연결이 정상적으로 작동하는 것입니다. 