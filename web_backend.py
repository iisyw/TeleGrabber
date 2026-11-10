import os
import json
import logging
import shutil
import threading
import time
import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from typing import Optional
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from utils import (
    SAVE_DIR, DATA_DIR, DB_PATH, THUMB_DIR, delete_media_by_id, delete_media_records,
    get_db_connection, generate_thumbnail_from_db, get_thumb_path,
    get_thumb_url, is_valid_file_unique_id,
)
from config import (
    TOKEN, PROXY, mask_proxy_url, TASK_RETAIN_DAYS, TASK_MIN_FREE_MB,
    WEB_HOST, WEB_PORT, DOWNLOAD_TIMEOUT, DOWNLOAD_STALL_TIMEOUT,
    DOWNLOAD_RETRIES, TASK_RETRY_CONCURRENCY, ALLOWED_USERS,
)
import task_manager
import retry_service
import runtime_state
import user_api
from api_response import (
    ACCESS_DENIED, INTERNAL_SERVER_ERROR, METHOD_NOT_ALLOWED,
    RESOURCE_NOT_FOUND, UNAUTHORIZED, VALIDATION_FAILED, BusinessError,
    error_payload, error_response, ok, set_request_id,
)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("web_backend")

app = FastAPI(title="TeleGrabber Web Management")


@app.middleware("http")
async def request_context(request: Request, call_next):
    """注入 requestId，并为构建产物/媒体文件设置长缓存。"""
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    if response.status_code == 200 and request.url.path.startswith(("/assets/", "/media/")):
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    return response


def _is_api_request(request: Request) -> bool:
    return request.url.path.startswith("/api/")


@app.exception_handler(BusinessError)
async def handle_business_error(request: Request, exc: BusinessError):
    return error_response(exc.code, exc.msg)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    if not _is_api_request(request):
        return PlainTextResponse("Bad Request", status_code=400)
    return error_response(VALIDATION_FAILED, "请求参数校验失败")


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if not _is_api_request(request):
        return PlainTextResponse(
            str(exc.detail), status_code=exc.status_code, headers=exc.headers
        )

    if exc.status_code == 401:
        code = UNAUTHORIZED
    elif exc.status_code == 403:
        code = ACCESS_DENIED
    elif exc.status_code == 404:
        code = RESOURCE_NOT_FOUND
    elif exc.status_code == 405:
        code = METHOD_NOT_ALLOWED
    elif exc.status_code in (400, 422):
        code = VALIDATION_FAILED
    else:
        code = INTERNAL_SERVER_ERROR

    return JSONResponse(
        status_code=exc.status_code if exc.status_code == 401 else 200,
        content=error_payload(code, exc.detail),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    logger.exception("未捕获异常: %s", exc)
    runtime_state.record_error(str(exc), source="web")
    if not _is_api_request(request):
        return PlainTextResponse("Internal Server Error", status_code=500)
    return error_response(INTERNAL_SERVER_ERROR)


# 媒体文件映射 (用于预览下载的内容)
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=SAVE_DIR), name="media")

# Vue 构建产物（web/dist）
web_dist_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dist")
web_assets_dir = os.path.join(web_dist_dir, "assets")
os.makedirs(web_assets_dir, exist_ok=True)
app.mount("/assets", StaticFiles(directory=web_assets_dir), name="assets")


def get_index_path():
    dist_index = os.path.join(web_dist_dir, "index.html")
    return dist_index if os.path.exists(dist_index) else None


@app.get("/")
def read_index():
    index_path = get_index_path()
    if index_path:
        return FileResponse(index_path)
    return error_response(INTERNAL_SERVER_ERROR, "前端尚未构建，请执行 cd web && npm run build")


@app.get("/favicon.ico")
async def favicon():
    favicon_path = os.path.join(web_dist_dir, "favicon.png")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    raise HTTPException(status_code=404, detail="资源不存在")


@app.get("/favicon.png")
async def favicon_png():
    return await favicon()

THUMB_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _search_condition(conn, search):
    """构造检索条件：FTS5 trigram 优先，短词回退 LIKE。"""
    terms = [term for term in (search or "").split() if term]
    if not terms:
        return None, []
    has_fts = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_fts'"
    ).fetchone()
    if has_fts and all(len(term) >= 3 for term in terms):
        match = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
        return "id IN (SELECT rowid FROM media_fts WHERE media_fts MATCH ?)", [match]
    conditions = []
    params = []
    for term in terms:
        conditions.append("(caption LIKE ? OR filename LIKE ? OR source_name LIKE ?)")
        like = f"%{term}%"
        params.extend([like, like, like])
    return " AND ".join(conditions), params


def _media_relative_path(source_name, source_type, filename):
    if not source_name:
        return os.path.join("unsorted", filename)
    if source_type in ("user", "private_user", "unknown_forward"):
        return os.path.join("direct_messages", source_name, filename)
    return os.path.join(source_name, filename)


def _dir_size(path):
    total = 0
    if not os.path.isdir(path):
        return 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


_health_lock = threading.Lock()
_health_cache = {"at": 0.0, "data": {}}
HEALTH_CACHE_SECONDS = 60


def _compute_health():
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT filename, source_name, source_type, file_unique_id, "
            "media_type, width, height, file_size FROM media_metadata"
        ).fetchall()
    finally:
        conn.close()
    root = os.path.abspath(SAVE_DIR)
    missing_files = 0
    missing_thumbs = 0
    missing_dimensions = 0
    for filename, source_name, source_type, unique_id, media_type, width, height, size in rows:
        rel = _media_relative_path(source_name, source_type, filename)
        path = os.path.abspath(os.path.join(root, rel))
        if not path.startswith(root + os.sep) or not os.path.exists(path):
            missing_files += 1
        if (
            media_type in ("photo", "video", "animation")
            and unique_id and not os.path.exists(get_thumb_path(unique_id))
        ):
            missing_thumbs += 1
        if width is None or height is None or size is None:
            missing_dimensions += 1
    return {
        "checked_at": datetime.now().isoformat(),
        "total": len(rows),
        "missing_files": missing_files,
        "missing_thumbs": missing_thumbs,
        "missing_dimensions": missing_dimensions,
        "thumb_bytes": _dir_size(THUMB_DIR),
    }


def _health_cached():
    with _health_lock:
        if not _health_cache["data"]:
            return None
        return dict(_health_cache["data"])


def _health_snapshot(force=False):
    now = time.time()
    with _health_lock:
        if (
            not force
            and _health_cache["data"]
            and now - _health_cache["at"] < HEALTH_CACHE_SECONDS
        ):
            return dict(_health_cache["data"])
    data = _compute_health()
    with _health_lock:
        _health_cache["at"] = time.time()
        _health_cache["data"] = data
    return dict(data)


@app.get("/thumb/{file_unique_id}")
def get_thumbnail(file_unique_id: str):
    """缩略图接口：命中磁盘直接返回，未命中时按需生成并缓存。

    缩略图内容不会变化，返回长缓存头，浏览器/代理只需拉取一次。
    """
    if not is_valid_file_unique_id(file_unique_id):
        raise HTTPException(status_code=404, detail="缩略图不存在")

    thumb_path = get_thumb_path(file_unique_id)
    if not os.path.exists(thumb_path):
        # 懒生成：兼容没有在下载时预热过的历史数据
        generate_thumbnail_from_db(file_unique_id)

    if os.path.exists(thumb_path):
        return FileResponse(
            thumb_path, media_type="image/webp", headers=THUMB_CACHE_HEADERS
        )
    raise HTTPException(status_code=404, detail="缩略图不存在")

@app.get("/api/media")
def get_media(
    limit: int = Query(30, ge=1, le=100),
    search: Optional[str] = None,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None,
    media_group_id: Optional[str] = None,
    media_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    favorite: Optional[bool] = None,
    tag: Optional[str] = None,
    sort: Optional[str] = "message_time",
    cursor_time: Optional[str] = None,
    cursor_id: Optional[int] = None,
):
    """获取媒体记录列表，支持按原始消息时间(message_time)或下载时间(datetime)排序"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = ("SELECT id, user_id, user_name, filename, datetime, message_time, "
                 "media_group_id, media_type, caption, source_name, source_id, "
                 "source_username, source_link1, source_link2, source_type, "
                 "file_unique_id, file_id, message_id, current_message_id, original_message_id, remark, width, height, file_size, favorite, tags "
                 "FROM media_metadata")
        params = []
        conditions = []

        if search:
            clause, search_params = _search_condition(cursor, search)
            if clause:
                conditions.append(clause)
                params.extend(search_params)

        if source_name:
            conditions.append("source_name = ?")
            params.append(source_name)

        if media_group_id:
            if media_group_id == "single":
                conditions.append("(media_group_id IS NULL OR media_group_id = '' OR media_group_id = 'single')")
            else:
                conditions.append("media_group_id = ?")
                params.append(media_group_id)

        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)

        if media_type:
            conditions.append("media_type = ?")
            params.append(media_type)

        if favorite:
            conditions.append("favorite = 1")

        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%,{tag},%")

        if date_from:
            conditions.append("COALESCE(message_time, datetime) >= ?")
            params.append(date_from)

        if date_to:
            upper = date_to + "T23:59:59" if len(date_to) == 10 else date_to
            conditions.append("COALESCE(message_time, datetime) <= ?")
            params.append(upper)

        if cursor_id is not None:
            if sort == "datetime":
                conditions.append("id < ?")
                params.append(cursor_id)
            elif cursor_time:
                conditions.append(
                    "(COALESCE(message_time, datetime) < ? OR "
                    "(COALESCE(message_time, datetime) = ? AND id < ?))"
                )
                params.extend([cursor_time, cursor_time, cursor_id])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        # 默认 message_time DESC（原始消息时间），可切 datetime DESC（下载时间）
        if sort == "datetime":
            query += " ORDER BY id DESC"  # datetime 和 id DESC 基本等价（下载顺序）
        else:
            # 按 COALESCE(message_time, datetime) 排序，空的排后面
            query += " ORDER BY COALESCE(message_time, datetime) DESC, id DESC"

        query += " LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return ok([
            {
                "id": row[0], "user_id": row[1], "user_name": row[2],
                "filename": row[3], "datetime": row[4], "message_time": row[5],
                "media_group_id": row[6], "media_type": row[7], "caption": row[8],
                "source_name": row[9], "source_id": row[10],
                "source_username": row[11], "source_link1": row[12],
                "source_link2": row[13], "source_type": row[14],
                "file_unique_id": row[15], "file_id": row[16],
                "message_id": row[17], "current_message_id": row[18],
                "original_message_id": row[19], "thumb_url": get_thumb_url(row[15]),
                "remark": row[20], "width": row[21], "height": row[22],
                "file_size": row[23], "favorite": bool(row[24]), "tags": row[25] or '',
            }
            for row in rows
        ])
    except Exception as e:
        logger.error(f"获取媒体记录失败: {e}")
        raise HTTPException(status_code=500, detail="获取媒体记录失败")

@app.get("/api/sources")
def get_sources(source_type: Optional[str] = None):
    """一次返回来源列表及各来源媒体/消息计数，避免前端 N+1 请求。"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = (
            "SELECT m.source_name, m.source_type, COUNT(*) AS media_count, "
            "COUNT(DISTINCT CASE "
            "WHEN m.media_group_id IS NOT NULL AND m.media_group_id != '' AND m.media_group_id != 'single' "
            "THEN m.media_group_id ELSE 'msg_' || m.id END) AS message_count, "
            "MAX(m.datetime) AS last_synced_at, "
            "COALESCE(sm.pinned, 0) AS pinned, COALESCE(sm.hidden, 0) AS hidden, "
            "COALESCE(sm.remark, '') AS remark, MAX(m.source_id) AS source_id "
            "FROM media_metadata m LEFT JOIN source_meta sm ON sm.source_name = m.source_name "
            "WHERE m.source_name IS NOT NULL AND m.source_name != ''"
        )
        params = []
        if source_type:
            query += " AND m.source_type = ?"
            params.append(source_type)
        query += (
            " GROUP BY m.source_name, m.source_type "
            "ORDER BY COALESCE(sm.pinned, 0) DESC, MAX(m.id) DESC"
        )
        cursor.execute(query, params)
        rows = cursor.fetchall()
        failed_rows = cursor.execute(
            "SELECT source_name, COUNT(*) FROM download_tasks "
            "WHERE status = 'failed' AND source_name IS NOT NULL AND source_name != '' "
            "GROUP BY source_name"
        ).fetchall()
        failed_map = {row[0]: row[1] for row in failed_rows}

        total_query = (
            "SELECT COUNT(*), COUNT(DISTINCT CASE "
            "WHEN media_group_id IS NOT NULL AND media_group_id != '' AND media_group_id != 'single' "
            "THEN media_group_id ELSE 'msg_' || id END) FROM media_metadata"
        )
        total_params = []
        if source_type:
            total_query += " WHERE source_type = ?"
            total_params.append(source_type)
        cursor.execute(total_query, total_params)
        totals = cursor.fetchone()
        conn.close()
        return ok({
            "sources": [
                {
                    "source_name": row[0],
                    "source_type": row[1],
                    "media_count": row[2],
                    "message_count": row[3],
                    "last_synced_at": row[4],
                    "pinned": bool(row[5]),
                    "hidden": bool(row[6]),
                    "remark": row[7] or '',
                    "source_id": row[8],
                    "protected": user_api.is_chat_protected(row[8]),
                    "failed_count": failed_map.get(row[0], 0),
                }
                for row in rows
            ],
            "totals": {"media_count": totals[0], "message_count": totals[1]},
        })
    except Exception as e:
        logger.error(f"获取来源列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取来源列表失败")

@app.get("/api/stats")
def get_stats(
    search: Optional[str] = None,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None,
    media_group_id: Optional[str] = None,
    media_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    favorite: Optional[bool] = None,
    tag: Optional[str] = None,
):
    """获取媒体统计信息。支持与 /api/media 相同的筛选参数，
    返回媒体数和消息数。"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = ("SELECT COUNT(*), "
                 "COUNT(DISTINCT CASE WHEN media_group_id IS NOT NULL AND media_group_id != '' AND media_group_id != 'single' "
                 "THEN media_group_id ELSE 'msg_' || id END) "
                 "FROM media_metadata")
        params = []
        conditions = []
        if search:
            clause, search_params = _search_condition(cursor, search)
            if clause:
                conditions.append(clause)
                params.extend(search_params)
        if source_name:
            conditions.append("source_name = ?")
            params.append(source_name)
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        if media_type:
            conditions.append("media_type = ?")
            params.append(media_type)
        if favorite:
            conditions.append("favorite = 1")
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%,{tag},%")
        if date_from:
            conditions.append("COALESCE(message_time, datetime) >= ?")
            params.append(date_from)
        if date_to:
            upper = date_to + "T23:59:59" if len(date_to) == 10 else date_to
            conditions.append("COALESCE(message_time, datetime) <= ?")
            params.append(upper)
        if media_group_id:
            if media_group_id == "single":
                conditions.append("(media_group_id IS NULL OR media_group_id = '' OR media_group_id = 'single')")
            else:
                conditions.append("media_group_id = ?")
                params.append(media_group_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        cursor.execute(query, params)
        row = cursor.fetchone()
        conn.close()
        return ok({"total_count": row[0], "message_count": row[1], "filtered": bool(conditions)})
    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail="获取统计信息失败")


@app.get("/api/tasks")
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


@app.get("/api/tasks/{task_id}")
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
    task["source_link2"] = context.get("source_link2")
    task["original_message_id"] = context.get("original_message_id") or context.get("orig_msg_id")
    task["source_id"] = context.get("source_id") or context.get("orig_chat_id")
    return ok(task)


@app.post("/api/tasks/{task_id}/retry")
def retry_task(
    task_id: int,
    priority: int = Query(0, ge=0, le=10),
):
    try:
        retry_service.retry_task(task_id, priority=priority)
    except retry_service.RetryError as exc:
        raise BusinessError(VALIDATION_FAILED, str(exc))
    return ok({"task_id": task_id, "status": "queued"})


@app.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: int):
    try:
        retry_service.pause_task(task_id)
    except retry_service.RetryError as exc:
        raise BusinessError(VALIDATION_FAILED, str(exc))
    return ok({"task_id": task_id, "status": "paused"})


@app.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: int):
    try:
        retry_service.resume_task(task_id)
    except retry_service.RetryError as exc:
        raise BusinessError(VALIDATION_FAILED, str(exc))
    return ok({"task_id": task_id, "status": "queued"})


@app.post("/api/tasks/retry-failed")
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


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: int):
    result = task_manager.request_cancel(task_id)
    if not result:
        raise BusinessError(VALIDATION_FAILED, "任务不存在或已结束")
    return ok({"task_id": task_id, "result": result})


class SourceMetaUpdate(BaseModel):
    source_name: str
    pinned: Optional[bool] = None
    hidden: Optional[bool] = None
    remark: Optional[str] = None


class MediaMetaUpdate(BaseModel):
    favorite: Optional[bool] = None
    tags: Optional[str] = None
    remark: Optional[str] = None


@app.patch("/api/media/{media_id}/meta")
def update_media_meta(media_id: int, payload: MediaMetaUpdate):
    fields = []
    params = []
    if payload.favorite is not None:
        fields.append("favorite = ?")
        params.append(1 if payload.favorite else 0)
    if payload.tags is not None:
        raw = payload.tags.replace("，", ",").split(",")
        tags = []
        for item in raw:
            tag = item.strip()
            if tag and tag not in tags:
                tags.append(tag)
        normalized = f",{','.join(tags)}," if tags else ""
        fields.append("tags = ?")
        params.append(normalized)
    if payload.remark is not None:
        fields.append("remark = ?")
        params.append(payload.remark.strip())
    if not fields:
        raise BusinessError(VALIDATION_FAILED, "没有需要更新的字段")

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            f"UPDATE media_metadata SET {', '.join(fields)} WHERE id = ?",
            (*params, media_id),
        )
        conn.commit()
        if cursor.rowcount <= 0:
            raise BusinessError(RESOURCE_NOT_FOUND, "媒体不存在")
        row = conn.execute(
            "SELECT favorite, tags, remark FROM media_metadata WHERE id = ?",
            (media_id,),
        ).fetchone()
    finally:
        conn.close()
    return ok({
        "id": media_id,
        "favorite": bool(row[0]),
        "tags": row[1] or '',
        "remark": row[2] or '',
    })


@app.get("/api/duplicates")
def get_duplicates(limit: int = Query(50, ge=1, le=200)):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT file_unique_id, COUNT(*) AS cnt, COALESCE(SUM(file_size), 0), "
            "GROUP_CONCAT(filename, char(31)), GROUP_CONCAT(COALESCE(source_name, ''), char(31)) "
            "FROM media_metadata WHERE file_unique_id IS NOT NULL AND file_unique_id != '' "
            "GROUP BY file_unique_id HAVING COUNT(*) > 1 "
            "ORDER BY cnt DESC, file_unique_id LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return ok([
        {
            "file_unique_id": row[0],
            "count": row[1],
            "total_bytes": row[2],
            "filenames": (row[3] or '').split(chr(31)),
            "sources": (row[4] or '').split(chr(31)),
        }
        for row in rows
    ])


@app.patch("/api/sources/meta")
def update_source_meta(payload: SourceMetaUpdate):
    source_name = (payload.source_name or "").strip()
    if not source_name:
        raise BusinessError(VALIDATION_FAILED, "来源名称不能为空")
    if payload.pinned is None and payload.hidden is None and payload.remark is None:
        raise BusinessError(VALIDATION_FAILED, "没有需要更新的字段")
    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT pinned, hidden, remark FROM source_meta WHERE source_name = ?",
            (source_name,),
        ).fetchone()
        pinned = int(payload.pinned) if payload.pinned is not None else (existing[0] if existing else 0)
        hidden = int(payload.hidden) if payload.hidden is not None else (existing[1] if existing else 0)
        remark = payload.remark if payload.remark is not None else (existing[2] if existing else '')
        conn.execute(
            "INSERT INTO source_meta (source_name, pinned, hidden, remark, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(source_name) DO UPDATE SET pinned = excluded.pinned, "
            "hidden = excluded.hidden, remark = excluded.remark, updated_at = excluded.updated_at",
            (source_name, pinned, hidden, remark, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return ok({"source_name": source_name, "pinned": bool(pinned), "hidden": bool(hidden), "remark": remark})


@app.get("/api/status")
def get_system_status():
    disk = shutil.disk_usage(SAVE_DIR)
    _, task_total, counts = task_manager.list_tasks(limit=1, offset=0)
    last_failed_tasks, _, _ = task_manager.list_tasks(status="failed", limit=1, offset=0)
    runtime = runtime_state.snapshot()
    health = _health_cached()
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
        "tasks": {            "total": task_total,
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


@app.post("/api/status/health")
def run_health_check():
    return ok(_health_snapshot(force=True))


@app.get("/healthz")
def healthz():
    db_ok = os.path.exists(DB_PATH)
    disk = shutil.disk_usage(SAVE_DIR)
    return ok({
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "disk_free": disk.free,
    })


@app.get("/api/storage/summary")
def get_storage_summary():
    try:
        conn = get_db_connection()
        try:
            totals = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM media_metadata"
            ).fetchone()
            by_source = conn.execute(
                "SELECT source_name, source_type, COUNT(*), COALESCE(SUM(file_size), 0) "
                "FROM media_metadata GROUP BY source_name, source_type "
                "ORDER BY COUNT(*) DESC"
            ).fetchall()
            by_type = conn.execute(
                "SELECT media_type, COUNT(*), COALESCE(SUM(file_size), 0) "
                "FROM media_metadata GROUP BY media_type ORDER BY COUNT(*) DESC"
            ).fetchall()
        finally:
            conn.close()

        disk = shutil.disk_usage(SAVE_DIR)
        return ok({
            "total_count": totals[0],
            "total_bytes": totals[1],
            "by_source": [
                {
                    "source_name": row[0] or '',
                    "source_type": row[1] or '',
                    "count": row[2],
                    "bytes": row[3],
                }
                for row in by_source
            ],
            "by_type": [
                {"media_type": row[0] or '', "count": row[1], "bytes": row[2]}
                for row in by_type
            ],
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
            },
        })
    except Exception as e:
        logger.error(f"获取存储统计失败: {e}")
        raise BusinessError(INTERNAL_SERVER_ERROR, "获取存储统计失败")


@app.delete("/api/media/{id}")
def delete_media(id: int):
    """删除指定记录及物理文件 (按主键 ID)"""
    try:
        deleted_count = delete_media_by_id([id])
    except Exception as e:
        logger.error(f"删除媒体失败: {e}")
        raise BusinessError(INTERNAL_SERVER_ERROR, "删除媒体失败")

    if deleted_count <= 0:
        raise BusinessError(RESOURCE_NOT_FOUND, "未找到相关记录或文件已删除")
    return ok({"status": "success", "deleted_count": deleted_count})

@app.delete("/api/media_group/{media_group_id}")
def delete_media_group(media_group_id: str):
    """删除整个媒体组及其物理文件"""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_unique_id FROM media_metadata WHERE media_group_id = ?",
                (media_group_id,),
            )
            unique_ids = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"查询媒体组失败: {e}")
        raise BusinessError(INTERNAL_SERVER_ERROR, "批量删除媒体组失败")

    if not unique_ids:
        raise BusinessError(RESOURCE_NOT_FOUND, "未找到该媒体组记录")

    try:
        deleted_count = delete_media_records(unique_ids)
    except Exception as e:
        logger.error(f"批量删除媒体组失败: {e}")
        raise BusinessError(INTERNAL_SERVER_ERROR, "批量删除媒体组失败")

    return ok({"status": "success", "deleted_count": deleted_count})


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """Vue Router history 模式回退：非 API/静态资源路径统一返回 index.html。"""
    reserved = ("api", "media", "thumb", "assets", "static")
    if any(full_path == name or full_path.startswith(f"{name}/") for name in reserved):
        raise HTTPException(status_code=404, detail="接口不存在")

    index_path = get_index_path()
    if index_path:
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="前端尚未构建")


def run_server(host="127.0.0.1", port=5000):
    if host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "Web 后台未启用内置鉴权，正在监听 %s。请确保网络可信，或在前置反向代理上配置访问控制。",
            host,
        )
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    run_server()
