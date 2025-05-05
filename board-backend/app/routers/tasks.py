from typing import Dict, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from celery.result import AsyncResult
from pydantic import BaseModel
from uuid import UUID

from app.database import get_db
from app.auth import get_current_active_user, get_current_admin_user
from app.models import User
from app.celery_worker import celery

router = APIRouter(prefix="/tasks", tags=["tasks"])


# 작업 상태 응답 모델
class TaskStatus(BaseModel):
    task_id: str
    status: str
    result: Optional[Dict] = None
    error: Optional[str] = None


# 작업 상태 조회 API
@router.get("/{task_id}", response_model=TaskStatus)
def get_task_status(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """작업 상태를 조회합니다."""
    try:
        task_result = AsyncResult(task_id, app=celery)

        response = {
            "task_id": task_id,
            "status": task_result.status,
        }

        # 작업이 완료된 경우 결과 포함
        if task_result.status == "SUCCESS":
            response["result"] = task_result.result
        # 작업이 실패한 경우 오류 메시지 포함
        elif task_result.status == "FAILURE":
            response["error"] = str(task_result.result)

        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error fetching task status: {str(e)}"
        )


# 작업 취소 API (관리자 전용)
@router.delete("/{task_id}", response_model=TaskStatus)
def revoke_task(
    task_id: str,
    terminate: bool = False,  # 실행 중인 작업을 강제로 종료할지 여부
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """(관리자용) 진행 중인 작업을 취소합니다."""
    try:
        task_result = AsyncResult(task_id, app=celery)

        # 이미 완료된 작업은 취소할 수 없음
        if task_result.status in ["SUCCESS", "FAILURE"]:
            return {
                "task_id": task_id,
                "status": task_result.status,
                "result": task_result.result if task_result.status == "SUCCESS" else None,
                "error": str(task_result.result) if task_result.status == "FAILURE" else None,
            }

        # 작업 취소
        celery.control.revoke(task_id, terminate=terminate)

        return {
            "task_id": task_id,
            "status": "REVOKED",
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error revoking task: {str(e)}")


# 활성 작업 목록 조회 API (관리자 전용)
@router.get("/active/list", response_model=List[Dict])
def list_active_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """(관리자용) 현재 실행 중인 모든 작업 목록을 조회합니다."""
    try:
        # 실행 중인 작업 목록 조회
        active_tasks = celery.control.inspect().active()

        if not active_tasks:
            return []

        # 모든 워커의 작업 목록 병합
        tasks = []
        for worker, worker_tasks in active_tasks.items():
            for task in worker_tasks:
                tasks.append(
                    {
                        "task_id": task["id"],
                        "name": task["name"],
                        "args": task["args"],
                        "kwargs": task["kwargs"],
                        "worker": worker,
                        "time_start": task.get("time_start", None),
                    }
                )

        return tasks
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error listing active tasks: {str(e)}"
        )
