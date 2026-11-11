"""下载任务中心：持久化记录每条媒体的下载状态、进度与重试上下文。"""

import json
import threading
from datetime import datetime, timedelta

from .config import logger
from . import utils

_lock = utils._db_lock
_TABLE_READY = False

TERMINAL_STATUSES = ('success', 'failed', 'skipped', 'cancelled')


def _now():
    return datetime.now().isoformat()


def _ensure_table():
    global _TABLE_READY
    if _TABLE_READY:
        return
    # init_db 会建表；这里兜底处理 Web 侧单独启动任务中心的情况
    try:
        conn = utils.get_db_connection()
        try:
            conn.execute("SELECT 1 FROM download_tasks LIMIT 1")
        finally:
            conn.close()
        _TABLE_READY = True
    except Exception:
        try:
            utils.init_db()
            _TABLE_READY = True
        except Exception as e:
            logger.warning(f"初始化下载任务表失败: {e}")


def create_task(user_id=None, user_name=None, chat_id=None, message_id=None,
                media_group_id=None, batch_id=None, file_unique_id=None, filename=None,
                media_type=None, source_name=None, source_type=None,
                download_method=None, total_bytes=0, item_index=None,
                retry_context=None):
    _ensure_table()
    context_text = None
    if retry_context:
        try:
            context_text = json.dumps(retry_context, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning(f"下载任务重试上下文序列化失败: {e}")
    with _lock:
        conn = utils.get_db_connection()
        try:
            cursor = conn.cursor()
            now = _now()
            cursor.execute(
                '''
                INSERT INTO download_tasks (
                    user_id, user_name, chat_id, message_id, media_group_id, batch_id,
                    file_unique_id, filename, media_type, source_name, source_type,
                    download_method, status, progress, downloaded_bytes, total_bytes,
                    item_index, retry_context, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, 0, ?, ?, ?, ?, ?)
                ''',
                (
                    user_id, user_name, chat_id, message_id, media_group_id, batch_id,
                    file_unique_id, filename, media_type, source_name, source_type,
                    download_method, int(total_bytes or 0), item_index,
                    context_text, now, now,
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()


def update_task(task_id, **fields):
    if not task_id:
        return
    _ensure_table()
    allowed = {
        'status', 'progress', 'downloaded_bytes', 'total_bytes', 'error',
        'filename', 'download_method', 'media_type', 'source_name', 'source_type',
        'finished_at', 'item_index', 'cancel_requested',
    }
    values = {k: v for k, v in fields.items() if k in allowed}
    if not values:
        return
    if values.get('status') in TERMINAL_STATUSES and 'finished_at' not in values:
        values['finished_at'] = _now()
    if 'error' in values and values['error'] is not None:
        values['error'] = str(values['error'])[:500]
    values['updated_at'] = _now()

    assignments = ', '.join(f"{key} = ?" for key in values)
    with _lock:
        conn = utils.get_db_connection()
        try:
            conn.execute(
                f"UPDATE download_tasks SET {assignments} WHERE id = ?",
                (*values.values(), task_id),
            )
            conn.commit()
        finally:
            conn.close()


def update_progress(task_id, downloaded, total):
    if not task_id:
        return
    _ensure_table()
    downloaded = int(downloaded or 0)
    total = int(total or 0)
    progress = min(100, int(downloaded * 100 / total)) if total > 0 else 0
    now = _now()
    with _lock:
        conn = utils.get_db_connection()
        try:
            # 已完成/失败/取消的任务不再被迟到的进度回调覆盖
            conn.execute(
                "UPDATE download_tasks SET status = 'downloading', progress = ?, "
                "downloaded_bytes = ?, total_bytes = ?, updated_at = ? "
                "WHERE id = ? AND status IN ('queued', 'downloading')",
                (progress, downloaded, total, now, task_id),
            )
            conn.commit()
        finally:
            conn.close()


def finish_task(task_id, status, error=None, filename=None):
    fields = {'status': status, 'error': error}
    if filename:
        fields['filename'] = filename
    if status == 'success':
        fields['progress'] = 100
    update_task(task_id, **fields)
    if status == 'success':
        # Bot API 没有进度回调，成功时用已知总大小补齐已下载字节数
        with _lock:
            conn = utils.get_db_connection()
            try:
                conn.execute(
                    "UPDATE download_tasks SET downloaded_bytes = "
                    "CASE WHEN total_bytes > 0 THEN total_bytes ELSE downloaded_bytes END "
                    "WHERE id = ?",
                    (task_id,),
                )
                conn.commit()
            finally:
                conn.close()


def get_task(task_id):
    _ensure_table()
    conn = utils.get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, user_id, user_name, chat_id, message_id, media_group_id, batch_id, "
            "file_unique_id, filename, media_type, source_name, source_type, "
            "download_method, status, progress, downloaded_bytes, total_bytes, "
            "error, item_index, retry_context, cancel_requested, "
            "created_at, updated_at, finished_at "
            "FROM download_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    keys = [
        'id', 'user_id', 'user_name', 'chat_id', 'message_id', 'media_group_id', 'batch_id',
        'file_unique_id', 'filename', 'media_type', 'source_name', 'source_type',
        'download_method', 'status', 'progress', 'downloaded_bytes', 'total_bytes',
        'error', 'item_index', 'retry_context', 'cancel_requested',
        'created_at', 'updated_at', 'finished_at',
    ]
    return dict(zip(keys, row))


def reset_task(task_id):
    """把失败/取消任务重新置为排队，保留重试上下文。"""
    if not task_id:
        return
    _ensure_table()
    with _lock:
        conn = utils.get_db_connection()
        try:
            conn.execute(
                "UPDATE download_tasks SET status = 'queued', progress = 0, "
                "downloaded_bytes = 0, error = NULL, finished_at = NULL, "
                "cancel_requested = 0, updated_at = ? WHERE id = ?",
                (_now(), task_id),
            )
            conn.commit()
        finally:
            conn.close()


def request_cancel(task_id):
    """排队中的任务立即取消；下载中的任务标记取消，由下载器在下一个检查点处理。"""
    task = get_task(task_id)
    if not task:
        return None
    if task['status'] == 'queued':
        update_task(task_id, status='cancelled', error='已取消')
        return 'cancelled'
    if task['status'] == 'downloading':
        update_task(task_id, cancel_requested=1)
        return 'requested'
    return None


def is_cancel_requested(task_id):
    if not task_id:
        return False
    task = get_task(task_id)
    return bool(task and task.get('cancel_requested'))


def failed_task_ids(limit=20, source_name=None, media_group_id=None, batch_id=None):
    _ensure_table()
    limit = max(1, min(int(limit or 20), 100))
    conn = utils.get_db_connection()
    try:
        where = "status = 'failed' AND retry_context IS NOT NULL AND retry_context != ''"
        params = []
        if source_name:
            where += " AND source_name = ?"
            params.append(source_name)
        if media_group_id:
            where += " AND media_group_id = ?"
            params.append(media_group_id)
        if batch_id:
            where += " AND batch_id = ?"
            params.append(batch_id)
        rows = conn.execute(
            f"SELECT id FROM download_tasks WHERE {where} "
            "ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def prune_tasks(retain_days=30):
    """删除超过保留期的终态任务，避免任务表无限增长。"""
    _ensure_table()
    if not retain_days or retain_days <= 0:
        return 0
    cutoff = (datetime.now() - timedelta(days=retain_days)).isoformat()
    with _lock:
        conn = utils.get_db_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM download_tasks WHERE status IN ('success', 'failed', 'skipped', 'cancelled') "
                "AND updated_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


def list_tasks(status=None, limit=50, offset=0, source_name=None, media_group_id=None):
    _ensure_table()
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    conditions = []
    params = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if source_name:
        conditions.append("source_name = ?")
        params.append(source_name)
    if media_group_id:
        conditions.append("media_group_id = ?")
        params.append(media_group_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = utils.get_db_connection()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM download_tasks {where}", tuple(params)
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT id, user_id, user_name, chat_id, message_id, media_group_id, batch_id,
                   file_unique_id, filename, media_type, source_name, source_type,
                   download_method, status, progress, downloaded_bytes, total_bytes,
                   error, item_index, created_at, updated_at, finished_at
            FROM download_tasks
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        counts = dict(conn.execute(
            "SELECT status, COUNT(*) FROM download_tasks GROUP BY status"
        ).fetchall())
    finally:
        conn.close()

    keys = [
        'id', 'user_id', 'user_name', 'chat_id', 'message_id', 'media_group_id', 'batch_id',
        'file_unique_id', 'filename', 'media_type', 'source_name', 'source_type',
        'download_method', 'status', 'progress', 'downloaded_bytes', 'total_bytes',
        'error', 'item_index', 'created_at', 'updated_at', 'finished_at',
    ]
    tasks = [dict(zip(keys, row)) for row in rows]
    return tasks, total, counts


def fail_stale_tasks():
    """进程重启后，把上次未完成的任务标记为失败，避免永远显示下载中。"""
    _ensure_table()
    try:
        with _lock:
            conn = utils.get_db_connection()
            try:
                cursor = conn.execute(
                    "UPDATE download_tasks SET status = 'failed', error = ?, "
                    "updated_at = ?, finished_at = ? "
                    "WHERE status IN ('queued', 'downloading')",
                    ("进程重启，任务中断", _now(), _now()),
                )
                conn.commit()
                count = cursor.rowcount
            finally:
                conn.close()
        if count:
            logger.warning(f"已将 {count} 个中断的下载任务标记为失败")
    except Exception as e:
        logger.warning(f"清理中断下载任务失败: {e}")
