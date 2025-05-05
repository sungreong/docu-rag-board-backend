import os
from celery import Celery
from celery.signals import worker_ready

from app.config import settings

# Redis 연결 URL 설정
broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# Celery 객체 생성
celery = Celery(
    "board_backend",
    broker=broker_url,
    backend=result_backend,
    include=["app.tasks.file_tasks", "app.tasks.vectorize_tasks"],
)

# 선택적 설정
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",  # 한국 시간대 사용
    enable_utc=False,
    task_track_started=True,  # 작업 시작 시점을 추적
    task_time_limit=3600,  # 작업 제한 시간 (초)
    worker_hijack_root_logger=False,  # 기존 로거 설정 유지
    worker_prefetch_multiplier=1,  # 동시에 가져올 태스크 수 제한
)


@worker_ready.connect
def on_worker_ready(**kwargs):
    """워커가 시작될 때 실행되는 함수"""
    print("Celery worker is ready to receive tasks!")


if __name__ == "__main__":
    celery.start()
