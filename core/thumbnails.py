"""缩略图生成与缓存。"""

import os
import io
import re
import logging
import tempfile
import shutil
import subprocess
import concurrent.futures
import threading

from .config import DATA_DIR
from .media_files import get_save_directory

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except Exception:
    Image = None
    _PIL_AVAILABLE = False

logger = logging.getLogger(__name__)

THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
THUMB_URL_PREFIX = "/thumb"
THUMB_MAX_SIZE = 400
THUMB_QUALITY = 80
_THUMB_ID_RE = re.compile(r'^[A-Za-z0-9_-]{10,128}$')
_THUMB_EXTS = ('.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi')

_thumb_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix='thumb'
)
_thumb_gen_semaphore = threading.Semaphore(2)


def is_valid_file_unique_id(file_unique_id):
    return bool(file_unique_id) and bool(_THUMB_ID_RE.fullmatch(str(file_unique_id)))


def get_thumb_path(file_unique_id):
    uid = str(file_unique_id)
    return os.path.join(THUMB_DIR, uid[:2].lower(), f"{uid}.webp")


def get_thumb_url(file_unique_id):
    if not is_valid_file_unique_id(file_unique_id):
        return ''
    return f"{THUMB_URL_PREFIX}/{file_unique_id}"


def thumb_exists(file_unique_id):
    if not is_valid_file_unique_id(file_unique_id):
        return False
    return os.path.exists(get_thumb_path(file_unique_id))


def _write_webp(img, target):
    img.thumbnail((THUMB_MAX_SIZE, THUMB_MAX_SIZE), Image.LANCZOS)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert('RGB')

    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix='.webp.tmp', dir=os.path.dirname(target))
    os.close(fd)
    try:
        img.save(tmp_path, 'WEBP', quality=THUMB_QUALITY, method=4)
        os.replace(tmp_path, target)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _extract_video_frame(original_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return None

    fd, frame_path = tempfile.mkstemp(suffix='.jpg', prefix='thumb_')
    os.close(fd)
    for seek in ('1', '0'):
        cmd = [
            ffmpeg, '-v', 'error', '-y', '-ss', seek, '-i', original_path,
            '-frames:v', '1', frame_path,
        ]
        try:
            subprocess.run(
                cmd, check=True, timeout=30,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if os.path.getsize(frame_path) > 0:
                return frame_path
        except Exception:
            continue

    try:
        os.remove(frame_path)
    except OSError:
        pass
    return None


def save_thumbnail_bytes(file_unique_id, data):
    if not _PIL_AVAILABLE or not data or not is_valid_file_unique_id(file_unique_id):
        return False
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            _write_webp(img, get_thumb_path(file_unique_id))
        return True
    except Exception as e:
        logger.debug(f"保存缩略图字节失败 {file_unique_id}: {e}")
        return False


def generate_thumbnail(original_path, file_unique_id, media_type='photo'):
    if not _PIL_AVAILABLE or not original_path or not is_valid_file_unique_id(file_unique_id):
        return False
    if not os.path.exists(original_path):
        return False

    target = get_thumb_path(file_unique_id)
    if os.path.exists(target):
        return True

    ext = os.path.splitext(original_path)[1].lower()
    frame_path = None
    try:
        if media_type in ('video', 'animation') or ext in _THUMB_EXTS:
            frame_path = _extract_video_frame(original_path)
            if not frame_path:
                return False
            source = frame_path
        else:
            source = original_path

        with Image.open(source) as img:
            img.seek(0)
            _write_webp(img, target)
        return True
    except Exception as e:
        logger.debug(f"生成缩略图失败 {original_path}: {e}")
        return False
    finally:
        if frame_path:
            try:
                os.remove(frame_path)
            except OSError:
                pass


def generate_thumbnail_from_db(file_unique_id):
    if not is_valid_file_unique_id(file_unique_id):
        return False
    if thumb_exists(file_unique_id):
        return True

    # 延迟导入，避免 db -> thumbnails -> db 的循环依赖
    from .utils import get_db_connection

    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT filename, source_name, source_type, user_id, user_name, media_type "
                "FROM media_metadata WHERE file_unique_id = ?",
                (file_unique_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"查询缩略图原文件失败 {file_unique_id}: {e}")
        return False

    if not row:
        return False

    filename, source_name, source_type, user_id, user_name, media_type = row
    user_stub = type('User', (), {'id': user_id, 'username': user_name, 'first_name': user_name})
    save_dir = get_save_directory(user_stub, source_name, source_type)
    with _thumb_gen_semaphore:
        if thumb_exists(file_unique_id):
            return True
        return generate_thumbnail(
            os.path.join(save_dir, filename), file_unique_id, media_type or 'photo'
        )


def schedule_thumbnail_generation(original_path, file_unique_id, media_type='photo'):
    if not _PIL_AVAILABLE or not is_valid_file_unique_id(file_unique_id):
        return
    try:
        _thumb_executor.submit(generate_thumbnail, original_path, file_unique_id, media_type)
    except RuntimeError:
        generate_thumbnail(original_path, file_unique_id, media_type)


def delete_thumbnail(file_unique_id):
    if not is_valid_file_unique_id(file_unique_id):
        return
    path = get_thumb_path(file_unique_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        logger.warning(f"删除缩略图失败 {path}: {e}")
