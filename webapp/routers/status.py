"""系统状态与健康检查接口。"""

import os
import shutil

from fastapi import APIRouter

from webapp.api_response import ok
from core.config import (
    ALLOWED_USERS, DATA_DIR, DOWNLOAD_RETRIES, DOWNLOAD_STALL_TIMEOUT,
    DOWNLOAD_TIMEOUT, PROXY, SAVE_DIR, TASK_MIN_FREE_MB, TASK_RETAIN_DAYS,
    TASK_RETRY_CONCURRENCY, TOKEN, WEB_HOST, WEB_PORT, mask_proxy_url,
)
from core.utils import DB_PATH, get_db_connection
from core import retry_service
from core import runtime_state
from core import task_manager
from core import user_api
from webapp import health as health_service

router = APIRouter()


@router.get("/api/status")
def get_system_status():
    disk = shutil.disk_usage(SAVE_DIR)
    _, task_total, counts = task_manager.list_tasks(limit=1, offset=0)
    last_failed_tasks, _, _ = task_manager.list_tasks(status="failed", limit=1, offset=0)
    runtime = runtime_state.snapshot()
    health = health_service.cached()
    thumb_bytes = health.get("thumb_bytes") if health else None
    db_size = 0
    for suffix in ("", "-wal", "-shm"):
        path = DB_PATH + suffix
        if os.path.exists(path):
            db_size += os.path.getsize(path)

    conn = get_db_connection()
    try:
        media_count, media_bytes = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM media_metadata"
        ).fetchone()
        duplicate = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM((cnt - 1) * size), 0) FROM ("
            "SELECT file_unique_id, COUNT(*) AS cnt, MAX(COALESCE(file_size, 0)) AS size "
            "FROM media_metadata WHERE file_unique_id IS NOT NULL AND file_unique_id != '' "
            "GROUP BY file_unique_id HAVING COUNT(*) > 1)"
        ).fetchone()
    finally:
        conn.close()

    return ok({
        "runtime": runtime,
        "telegram": {
            "bot_configured": bool(TOKEN),
            "bot_id": runtime.get("bot_id"),
            "bot_username": runtime.get("bot_username"),
            "proxy_configured": bool(PROXY),
            "proxy": mask_proxy_url(PROXY) if PROXY else "",
        },
        "user_api": user_api.get_status(),
        "storage": {
            "save_dir": SAVE_DIR,
            "data_dir": DATA_DIR,
            "disk_total": disk.total,
            "disk_used": disk.used,
            "disk_free": disk.free,
            "min_free_mb": TASK_MIN_FREE_MB,
            "db_size": db_size,
            "media_count": media_count,
            "media_bytes": media_bytes,
            "thumb_bytes": thumb_bytes,
            "media_total_bytes": (media_bytes + thumb_bytes) if thumb_bytes is not None else None,
            "duplicate_groups": duplicate[0],
            "duplicate_wasted_bytes": duplicate[1],
        },
        "health": health,
        "tasks": {
            "total": task_total,
            "counts": counts,
            "last_failed": last_failed_tasks[0] if last_failed_tasks else None,
            "retry_pending": retry_service.queue_status()["pending"],
            "retain_days": TASK_RETAIN_DAYS,
        },
        "config": {
            "web_host": WEB_HOST,
            "web_port": WEB_PORT,
            "download_timeout": DOWNLOAD_TIMEOUT,
            "download_stall_timeout": DOWNLOAD_STALL_TIMEOUT,
            "download_retries": DOWNLOAD_RETRIES,
            "retry_concurrency": TASK_RETRY_CONCURRENCY,
            "allowed_users": len(ALLOWED_USERS),
        },
    })


@router.post("/api/status/health")
def run_health_check():
    return ok(health_service.snapshot(force=True))


@router.get("/healthz")
def healthz():
    db_ok = os.path.exists(DB_PATH)
    disk = shutil.disk_usage(SAVE_DIR)
    return ok({
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "disk_free": disk.free,
    })
