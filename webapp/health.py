"""媒体文件健康检查：缺失文件、缺失缩略图、缺失尺寸统计。"""

import os
import threading
import time
from datetime import datetime

from core.config import SAVE_DIR
from core.thumbnails import THUMB_DIR, get_thumb_path
from core.utils import get_db_connection

HEALTH_CACHE_SECONDS = 60

_lock = threading.Lock()
_cache = {"at": 0.0, "data": {}}


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
        if not filename:
            missing_files += 1
        else:
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


def cached():
    """返回最近一次健康检查快照；尚未检查过时返回 None。"""
    with _lock:
        if not _cache["data"]:
            return None
        return dict(_cache["data"])


def snapshot(force=False):
    now = time.time()
    with _lock:
        if (
            not force
            and _cache["data"]
            and now - _cache["at"] < HEALTH_CACHE_SECONDS
        ):
            return dict(_cache["data"])

    data = _compute_health()
    with _lock:
        _cache["at"] = time.time()
        _cache["data"] = data
    return dict(data)
