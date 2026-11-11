"""下载任务查询与操作接口。"""

import json
from typing import Optional

from fastapi import APIRouter, Query

from webapp.api_response import RESOURCE_NOT_FOUND, VALIDATION_FAILED, BusinessError, ok
from core import retry_service
from core import task_manager

router = APIRouter()


@router.get("/api/tasks")
def get_tasks(
    status: Optional[str] = None,
    source_name: Optional[str] = None,
    media_group_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    tasks, total, counts = task_manager.list_tasks(
        status=status, limit=limit, offset=offset,
        source_name=source_name, media_group_id=media_group_id,
    )
    for task in tasks:
        task["can_pause"] = retry_service.is_retry_queued(task["id"])
    return ok({"tasks": tasks, "total": total, "counts": counts})


@router.get("/api/tasks/{task_id}")
def get_task_detail(task_id: int):
    task = task_manager.get_task(task_id)
    if not task:
        raise BusinessError(RESOURCE_NOT_FOUND, "任务不存在")
    context_text = task.pop("retry_context", None)
    task["has_retry_context"] = bool(context_text)
    context = {}
    if context_text:
        try:
            context = json.loads(context_text)
        except ValueError:
            context = {}
    task["source_link1"] = context.get("source_link1")
    task["original_message_id"] = context.get("original_message_id") or context.get("orig_msg_id")
    task["source_id"] = context.get("source_id") or context.get("orig_chat_id")
    return ok(task)


@router.post("/api/tasks/{task_id}/retry")
def retry_task(
    task_id: int,
    priority: int = Query(0, ge=0, le=10),
):
    try:
        retry_service.retry_task(task_id, priority=priority)
    except retry_service.RetryError as exc:
        raise BusinessError(VALIDATION_FAILED, str(exc))
    return ok({"task_id": task_id, "status": "queued"})


@router.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: int):
    try:
        retry_service.pause_task(task_id)
    except retry_service.RetryError as exc:
        raise BusinessError(VALIDATION_FAILED, str(exc))
    return ok({"task_id": task_id, "status": "paused"})


@router.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: int):
    try:
        retry_service.resume_task(task_id)
    except retry_service.RetryError as exc:
        raise BusinessError(VALIDATION_FAILED, str(exc))
    return ok({"task_id": task_id, "status": "queued"})


@router.post("/api/tasks/retry-failed")
def retry_failed_tasks(
    limit: int = Query(20, ge=1, le=100),
    source_name: Optional[str] = None,
    media_group_id: Optional[str] = None,
    batch_id: Optional[str] = None,
):
    started, errors = retry_service.retry_failed(
        limit, source_name=source_name, media_group_id=media_group_id, batch_id=batch_id,
    )
    return ok({"started": started, "errors": errors})


@router.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: int):
    result = task_manager.request_cancel(task_id)
    if not result:
        raise BusinessError(VALIDATION_FAILED, "任务不存在或已结束")
    return ok({"task_id": task_id, "result": result})
