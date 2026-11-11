"""Web 任务中心的下载重试执行器。

重试统一走 User API：Web 线程不持有 PTB Bot 实例，而 User API 是同步封装，
可以在独立线程池中安全调用。媒体组上下文（media_group_id / 序号 / 文件名前缀）
会从 download_tasks.retry_context 还原，重试成功后仍归入原相册。
"""

import asyncio
import itertools
import json
import os
import queue
import shutil
import threading

from telegram import Bot
from telegram.request import HTTPXRequest

from .config import (
    logger, SAVE_DIR, USER_API_ENABLED, TASK_RETRY_CONCURRENCY, TASK_MIN_FREE_MB,
    TOKEN, DOWNLOAD_TIMEOUT, PROXY,
)
from .media_files import (
    generate_temp_filename, get_video_extension, get_image_extension,
    get_archive_ext,
)
from . import task_manager
from . import user_api
from . import utils


LARGE_FILE_THRESHOLD = 20 * 1024 * 1024
_executor = None
_task_queue = queue.PriorityQueue()
_seq = itertools.count()
_submitted = set()
_submitted_lock = threading.Lock()


def _worker():
    while True:
        item = _task_queue.get()
        if item is None:
            return
        _, _, task_id = item
        _run_retry(task_id)


def _ensure_workers():
    global _executor
    if _executor is not None:
        return
    _executor = []
    for _ in range(max(1, TASK_RETRY_CONCURRENCY)):
        thread = threading.Thread(target=_worker, name="task-retry", daemon=True)
        thread.start()
        _executor.append(thread)


def _enqueue(task_id, priority=0):
    _ensure_workers()
    _task_queue.put((-int(priority), next(_seq), task_id))


def _submit(task_id, priority=0):
    with _submitted_lock:
        if task_id in _submitted:
            raise RetryError("任务已在重试队列中")
        _submitted.add(task_id)
    task_manager.reset_task(task_id)
    _enqueue(task_id, priority)


class RetryError(Exception):
    pass


def retry_task(task_id, priority=0):
    task = task_manager.get_task(task_id)
    if not task:
        raise RetryError("任务不存在")
    if task["status"] in ("queued", "downloading", "paused"):
        raise RetryError("任务正在执行或已暂停")
    if not task.get("retry_context"):
        raise RetryError("该任务缺少重试上下文，请重新发送原消息或链接")
    _submit(task_id, priority)
    return task_id


def is_retry_queued(task_id):
    with _submitted_lock:
        return task_id in _submitted


def queue_status():
    with _submitted_lock:
        return {"pending": len(_submitted)}


def pause_task(task_id):
    if not is_retry_queued(task_id):
        raise RetryError("只有重试队列中的任务可以暂停")
    task = task_manager.get_task(task_id)
    if not task or task["status"] != "queued":
        raise RetryError("任务已经开始下载，无法暂停")
    task_manager.update_task(task_id, status="paused", error="已暂停")
    return task_id


def resume_task(task_id):
    task = task_manager.get_task(task_id)
    if not task or task["status"] != "paused":
        raise RetryError("任务不在暂停状态")
    task_manager.update_task(task_id, status="queued", error=None)
    with _submitted_lock:
        already_queued = task_id in _submitted
        if not already_queued:
            _submitted.add(task_id)
    if not already_queued:
        _enqueue(task_id)
    return task_id


def retry_failed(limit=20, source_name=None, media_group_id=None, batch_id=None):
    ids = task_manager.failed_task_ids(
        limit, source_name=source_name, media_group_id=media_group_id, batch_id=batch_id,
    )
    started = []
    errors = []
    for task_id in ids:
        try:
            retry_task(task_id)
            started.append(task_id)
        except RetryError as exc:
            errors.append({"id": task_id, "error": str(exc)})
    return started, errors


def _clear_submitted(task_id):
    with _submitted_lock:
        _submitted.discard(task_id)


def _run_retry(task_id):
    try:
        task = task_manager.get_task(task_id)
        if not task:
            return
        context = json.loads(task["retry_context"])
        _download(task, context)
    except Exception as e:
        logger.exception("任务 %s 重试失败", task_id)
        task_manager.finish_task(task_id, "failed", error=str(e))
    finally:
        _clear_submitted(task_id)
        # 暂停后立刻恢复的竞态：worker 已退出但状态已被改回 queued，重新入队
        latest = task_manager.get_task(task_id)
        if latest and latest["status"] == "queued":
            with _submitted_lock:
                already = task_id in _submitted
                if not already:
                    _submitted.add(task_id)
            if not already:
                _enqueue(task_id)


def _download(task, context):
    task_id = task["id"]
    current = task_manager.get_task(task_id)
    if not current or current["status"] != "queued":
        return
    file_unique_id = context.get("file_unique_id") or task.get("file_unique_id")
    task_manager.update_task(task_id, status="downloading")

    existing = utils.get_duplicate_info(file_unique_id) if file_unique_id else None
    if existing:
        task_manager.finish_task(
            task_id, "skipped",
            filename=existing.get("filename"),
            error=f"文件已存在：{existing.get('filename') or file_unique_id}",
        )
        return

    if task_manager.is_cancel_requested(task_id):
        task_manager.finish_task(task_id, "cancelled", error="已取消")
        return

    expected_size = int(context.get("file_size") or task.get("total_bytes") or 0)
    _check_disk(expected_size)

    date_dir = context.get("date_dir") or SAVE_DIR
    os.makedirs(date_dir, exist_ok=True)
    temp_filename = f".retry_{task_id}_{generate_temp_filename()}"
    temp_path = os.path.join(date_dir, temp_filename)

    def progress(current, total):
        task_manager.update_progress(task_id, current, total)

    candidates = _build_candidates(context)
    bot_possible = bool(
        TOKEN and context.get("file_id")
        and (expected_size <= 0 or expected_size <= LARGE_FILE_THRESHOLD)
    )
    if not candidates and not bot_possible:
        raise RetryError("重试上下文缺少可用的下载方式（User API 消息位置或 Bot file_id）")
    if not USER_API_ENABLED and not bot_possible:
        raise RetryError("该任务需要 User API（文件超过 Bot API 20MB 限制或缺少 file_id）")

    downloaded = False
    method = None
    errors = []
    if USER_API_ENABLED:
        for chat_id, message_id in candidates:
            if chat_id is None or message_id is None:
                continue
            if task_manager.is_cancel_requested(task_id):
                task_manager.finish_task(task_id, "cancelled", error="已取消")
                return
            try:
                downloaded = user_api.run_download_large_file(
                    chat_id, message_id, temp_path,
                    progress_callback=progress,
                    file_unique_id=file_unique_id,
                )
                if downloaded:
                    method = "user_api"
            except Exception as e:
                errors.append(f"User API: {e}")
                downloaded = False
            if downloaded:
                break

    if not downloaded and bot_possible:
        if task_manager.is_cancel_requested(task_id):
            task_manager.finish_task(task_id, "cancelled", error="已取消")
            return
        try:
            downloaded = _download_via_bot(context["file_id"], temp_path)
            if downloaded:
                method = "bot"
        except Exception as e:
            errors.append(f"Bot API: {e}")

    if not downloaded:
        for path in (temp_path, temp_path + ".part", temp_path + ".temp"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        detail = f"（{'；'.join(errors)}）" if errors else ""
        raise RetryError(f"下载失败{detail}")

    task_manager.update_task(task_id, download_method=method or "unknown")

    if task_manager.is_cancel_requested(task_id):
        _remove_quietly(temp_path)
        task_manager.finish_task(task_id, "cancelled", error="已取消")
        return

    ext = _detect_ext(temp_path, context)
    final_filename = _build_final_filename(context, ext)
    final_path = os.path.join(date_dir, final_filename)
    os.replace(temp_path, final_path)

    media_obj = type("Media", (), {
        "file_id": context.get("file_id") or "",
        "file_unique_id": file_unique_id,
    })
    ok = utils.save_to_db(
        _stub_user(context),
        media_obj,
        final_filename,
        save_dir=date_dir,
        media_group_id=context.get("media_group_id") or "",
        media_type=context.get("media_type") or task.get("media_type") or "document",
        caption=context.get("caption"),
        source_name=context.get("source_name"),
        source_id=context.get("source_id"),
        source_link1=context.get("source_link1"),
        source_username=context.get("source_username"),
        source_type=context.get("source_type"),
        message_time=context.get("message_time"),
        message_id=context.get("original_message_id") or context.get("message_id"),
        current_message_id=context.get("current_message_id") or context.get("message_id"),
        original_message_id=context.get("original_message_id"),
        width=context.get("width"),
        height=context.get("height"),
        file_size=context.get("file_size"),
    )
    if not ok:
        existing = utils.get_duplicate_info(file_unique_id) if file_unique_id else None
        if existing:
            # 文件可能已经写入库中，不能删除，否则会让已有记录指向不存在的文件
            task_manager.finish_task(
                task_id, "skipped",
                filename=existing.get("filename"),
                error=f"文件已存在：{existing.get('filename') or file_unique_id}",
            )
            return
        _remove_quietly(final_path)
        raise RetryError("元数据保存数据库失败")

    task_manager.finish_task(task_id, "success", filename=final_filename)


def _build_candidates(context):
    candidates = []
    for chat_key, msg_key in (
        ("link_chat_id", "link_message_id"),
        ("orig_chat_id", "orig_msg_id"),
        ("chat_id", "current_message_id"),
        ("chat_id", "message_id"),
        ("bot_username", "current_message_id"),
        ("bot_username", "message_id"),
    ):
        chat_id = context.get(chat_key)
        message_id = context.get(msg_key)
        if chat_id and message_id:
            pair = (chat_id, message_id)
            if pair not in candidates:
                candidates.append(pair)
    return candidates


def _build_final_filename(context, ext):
    group_id = context.get("media_group_id") or ""
    index = context.get("item_index")
    if group_id and index is not None:
        base = context.get("base_timestamp") or generate_temp_filename(group_id)
        return f"{group_id}_{index}_{base}{ext}"
    return f"{generate_temp_filename()}{ext}"


def _detect_ext(path, context):
    media_type = context.get("media_type")
    if media_type == "video":
        return get_video_extension(path)
    if media_type == "photo":
        return get_image_extension(path)
    if media_type == "animation":
        return get_video_extension(path)
    ext = get_archive_ext(path)
    if ext:
        return ext
    original = context.get("filename") or ""
    ext = os.path.splitext(original)[1]
    return ext if ext else ".bin"


def _check_disk(expected_size):
    free = shutil.disk_usage(SAVE_DIR).free
    required = int(expected_size * 1.05) + TASK_MIN_FREE_MB * 1024 * 1024
    if free < required:
        raise RetryError(
            f"磁盘空间不足：需要约 {required // (1024 * 1024)}MB，当前剩余 {free // (1024 * 1024)}MB"
        )


def _download_via_bot(file_id, final_path):
    """使用独立 Bot 实例通过 Bot API 下载小文件，作为 User API 失败后的回退。"""
    async def run():
        kwargs = {}
        if PROXY:
            kwargs["request"] = HTTPXRequest(proxy=PROXY)
        bot = Bot(TOKEN, **kwargs)
        async with bot:
            tg_file = await bot.get_file(file_id)
            await asyncio.wait_for(
                tg_file.download_to_drive(final_path),
                timeout=DOWNLOAD_TIMEOUT,
            )

    asyncio.run(run())
    return os.path.exists(final_path)


def _stub_user(context):
    return type("User", (), {
        "id": context.get("user_id"),
        "username": context.get("user_name"),
        "first_name": context.get("user_name"),
    })


def _remove_quietly(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
