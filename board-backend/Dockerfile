FROM python:3.9-slim

WORKDIR /app

# 필요한 패키지 설치
RUN apt-get update && apt-get install -y \
    postgresql-client \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 전체 코드 복사
COPY . .

# 시작 스크립트에 실행 권한 부여
RUN chmod +x start.sh

# 임시 디렉토리 생성
RUN mkdir -p /tmp

# 기본 환경 변수 설정
ENV APP_MODE=web

# 시작 스크립트 실행
CMD ["./start.sh"] 