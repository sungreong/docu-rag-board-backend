#!/bin/bash
set -e

# 필요한 디렉토리 생성
mkdir -p /tmp

# 환경 변수 확인 (기본값 = web)
APP_MODE=${APP_MODE:-web}

# 명령 실행
case "$APP_MODE" in
  web)
    echo "Starting FastAPI web server..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    echo "Starting Celery worker..."
    exec celery -A app.celery_worker.celery worker --loglevel=info
    ;;
  flower)
    echo "Starting Celery Flower monitoring..."
    exec celery -A app.celery_worker.celery flower --port=5555 --address=0.0.0.0
    ;;
  *)
    echo "Unknown APP_MODE: $APP_MODE. Using default (web)"
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
esac 