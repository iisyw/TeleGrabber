"""媒体文件健康检查：缺失文件、缺失缩略图、缺失尺寸统计。"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

from core.config import DATA_DIR, SAVE_DIR
from core.thumbnails import (
    THUMB_DIR, generate_thumbnail, get_thumb_path, get_thumb_url,
)
from core.utils import _db_lock, get_db_connection

logger = logging.getLogger("webapp.health")

HEALTH_CACHE_SECONDS = 60
HEALTH_FILE = os.path.join(DATA_DIR, "health_cache.json")

_lock = threading.Lock()
_computing_lock = threading.Lock()


def _load_persisted():
    if not os.path.exists(HEALTH_FILE):
        return {}
    try:
        with open(HEALTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "checked_at" in data:
                return data
    except Exception as e:
        logger.debug("读取健康检查持久化缓存失败: %s", e)
    return {}


def _save_persisted(data):
    try:
        os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
        temp_file = f"{HEALTH_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, HEALTH_FILE)
    except Exception as e:
        logger.warning("保存健康检查持久化缓存失败: %s", e)


_initial_data = _load_persisted()
_cache = {
    "at": time.time() if _initial_data else 0.0,
    "data": _initial_data,
}


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


def _probe_video_dimensions(file_path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None, None
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
        file_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and "x" in proc.stdout:
            parts = proc.stdout.strip().split("\n")[0].split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return int(parts[0]), int(parts[1])
    except Exception as e:
        logger.debug("ffprobe 获取视频尺寸失败 %s: %s", file_path, e)
    return None, None


def _probe_image_dimensions(file_path):
    try:
        from PIL import Image
        with Image.open(file_path) as img:
            return img.width, img.height
    except Exception as e:
        logger.debug("PIL 获取图片尺寸失败 %s: %s", file_path, e)
        return None, None


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
        file_exists = False
        if filename:
            rel = _media_relative_path(source_name, source_type, filename)
            path = os.path.abspath(os.path.join(root, rel))
            if path.startswith(root + os.sep) and os.path.exists(path):
                file_exists = True

        if not file_exists:
            missing_files += 1
        else:
            if (
                media_type in ("photo", "video", "animation")
                and unique_id and not os.path.exists(get_thumb_path(unique_id))
            ):
                missing_thumbs += 1
            if width is None or height is None or size is None or size <= 0:
                missing_dimensions += 1

    return {
        "checked_at": datetime.now().isoformat(),
        "total": len(rows),
        "missing_files": missing_files,
        "missing_thumbs": missing_thumbs,
        "missing_dimensions": missing_dimensions,
        "thumb_bytes": _dir_size(THUMB_DIR),
    }


def list_issues(issue_type="all", limit=50, offset=0):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, filename, source_name, source_type, file_unique_id, "
            "media_type, width, height, file_size, datetime FROM media_metadata "
            "ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()

    root = os.path.abspath(SAVE_DIR)
    issues = []

    for row in rows:
        row_id, filename, source_name, source_type, unique_id, media_type, width, height, size, dt = row
        item_issues = []
        file_exists = False

        if not filename:
            item_issues.append("missing_files")
        else:
            rel = _media_relative_path(source_name, source_type, filename)
            path = os.path.abspath(os.path.join(root, rel))
            if path.startswith(root + os.sep) and os.path.exists(path):
                file_exists = True
            else:
                item_issues.append("missing_files")

        if file_exists:
            if media_type in ("photo", "video", "animation") and unique_id:
                if not os.path.exists(get_thumb_path(unique_id)):
                    item_issues.append("missing_thumbs")
            if width is None or height is None or size is None or size <= 0:
                item_issues.append("missing_dimensions")

        if not item_issues:
            continue

        match = False
        if issue_type == "all":
            match = True
        elif issue_type in item_issues:
            match = True

        if match:
            issues.append({
                "id": row_id,
                "filename": filename or "-",
                "source_name": source_name or "未分类",
                "source_type": source_type or "unknown",
                "file_unique_id": unique_id or "-",
                "media_type": media_type or "file",
                "width": width,
                "height": height,
                "file_size": size or 0,
                "datetime": dt or "-",
                "issues": item_issues,
                "file_exists": file_exists,
                "thumb_url": get_thumb_url(unique_id) if file_exists and "missing_thumbs" not in item_issues else "",
            })

    total = len(issues)
    paged = issues[offset : offset + limit]
    return {
        "items": paged,
        "total": total,
    }


def repair_issues(action="all"):
    """批量修复缺失缩略图或尺寸的媒体记录。"""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, filename, source_name, source_type, file_unique_id, "
            "media_type, width, height, file_size FROM media_metadata ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    root = os.path.abspath(SAVE_DIR)
    repaired_thumbs = 0
    repaired_dimensions = 0

    do_thumbs = action in ("thumbs", "all")
    do_dimensions = action in ("dimensions", "all")

    for row_id, filename, source_name, source_type, unique_id, media_type, width, height, size in rows:
        if not filename:
            continue
        rel = _media_relative_path(source_name, source_type, filename)
        path = os.path.abspath(os.path.join(root, rel))
        if not path.startswith(root + os.sep) or not os.path.exists(path):
            continue

        # 修复缩略图
        if do_thumbs and media_type in ("photo", "video", "animation") and unique_id:
            if not os.path.exists(get_thumb_path(unique_id)):
                try:
                    if generate_thumbnail(path, unique_id, media_type):
                        repaired_thumbs += 1
                except Exception as e:
                    logger.debug("修复缩略图异常 %s: %s", unique_id, e)

        # 修复尺寸与文件大小
        if do_dimensions and (width is None or height is None or size is None or size <= 0):
            try:
                new_size = size if (size and size > 0) else os.path.getsize(path)
                new_w, new_h = width, height
                if new_w is None or new_h is None:
                    ext = os.path.splitext(path)[1].lower()
                    if media_type == "video" or ext in (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"):
                        new_w, new_h = _probe_video_dimensions(path)
                    else:
                        new_w, new_h = _probe_image_dimensions(path)

                if new_w is not None or new_h is not None or (new_size and new_size != size):
                    with _db_lock:
                        db = get_db_connection()
                        try:
                            db.execute(
                                "UPDATE media_metadata SET width = ?, height = ?, file_size = ? WHERE id = ?",
                                (new_w if new_w is not None else width,
                                 new_h if new_h is not None else height,
                                 new_size,
                                 row_id),
                            )
                            db.commit()
                            repaired_dimensions += 1
                        finally:
                            db.close()
            except Exception as e:
                logger.debug("修复尺寸异常 %s: %s", path, e)

    new_snapshot = snapshot(force=True)
    return {
        "repaired_thumbs": repaired_thumbs,
        "repaired_dimensions": repaired_dimensions,
        "health": new_snapshot,
    }


def clean_missing_records(ids=None):
    """清理磁盘上原文件已不存在的数据库记录。"""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, filename, source_name, source_type FROM media_metadata ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    root = os.path.abspath(SAVE_DIR)
    target_ids = set(ids) if ids else None
    to_delete = []

    for row_id, filename, source_name, source_type in rows:
        if target_ids is not None and row_id not in target_ids:
            continue
        if not filename:
            to_delete.append(row_id)
            continue
        rel = _media_relative_path(source_name, source_type, filename)
        path = os.path.abspath(os.path.join(root, rel))
        if not path.startswith(root + os.sep) or not os.path.exists(path):
            to_delete.append(row_id)

    deleted_count = 0
    if to_delete:
        from core.utils import delete_media_by_id
        deleted_count = delete_media_by_id(to_delete)
        snapshot(force=True)

    return {
        "deleted_count": deleted_count,
        "health": cached(),
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

    with _computing_lock:
        # 双重检查，避免多个并发请求重复全盘扫描
        with _lock:
            if (
                not force
                and _cache["data"]
                and time.time() - _cache["at"] < HEALTH_CACHE_SECONDS
            ):
                return dict(_cache["data"])

        data = _compute_health()
        _save_persisted(data)
        with _lock:
            _cache["at"] = time.time()
            _cache["data"] = data
        return dict(data)
