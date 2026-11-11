"""本地媒体文件路径、扩展名与文件名工具。"""

import os
import errno
import time
import logging
import mimetypes

from .config import SAVE_DIR

logger = logging.getLogger(__name__)


def get_save_directory(user, source_name=None, source_type=None):
    """创建并返回媒体保存目录。"""
    if not source_name:
        source_dir = os.path.join(SAVE_DIR, "unsorted")
    elif source_type in ["user", "private_user", "unknown_forward"]:
        source_dir = os.path.join(SAVE_DIR, "direct_messages", source_name)
    else:
        source_dir = os.path.join(SAVE_DIR, source_name)

    for attempt in range(3):
        try:
            if not os.path.exists(source_dir):
                os.makedirs(source_dir, exist_ok=True)
            return source_dir
        except OSError as e:
            if e.errno == errno.ESTALE and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    return source_dir


def get_video_extension(file_path):
    """检测视频文件的实际格式并返回扩展名。"""
    if not mimetypes.inited:
        mimetypes.init()

    video_signatures = {
        b'\x00\x00\x00\x18\x66\x74\x79\x70\x6D\x70\x34\x32': '.mp4',
        b'\x00\x00\x00\x1C\x66\x74\x79\x70\x6D\x70\x34\x32': '.mp4',
        b'\x00\x00\x00\x20\x66\x74\x79\x70\x69\x73\x6F\x6D': '.mp4',
        b'\x1A\x45\xDF\xA3': '.webm',
        b'\x00\x00\x00\x14\x66\x74\x79\x70\x71\x74\x20\x20': '.mov',
        b'\x52\x49\x46\x46': '.avi',
    }

    try:
        with open(file_path, 'rb') as f:
            header = f.read(12)
            for sig, ext in video_signatures.items():
                if header.startswith(sig):
                    return ext
    except Exception as e:
        logger.error(f"读取文件头部错误: {e}")

    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type and mime_type.startswith('video/'):
        ext = mimetypes.guess_extension(mime_type)
        if ext:
            return ext

    logger.warning(f"无法检测视频类型: {file_path}, 使用默认.mp4扩展名")
    return '.mp4'


def get_image_extension(file_path):
    """通过文件头魔数检测图片格式并返回扩展名。"""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)
    except Exception as e:
        logger.error(f"读取图片文件头失败: {e}")
        return '.jpg'

    if header.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
        return '.gif'
    if header.startswith(b'BM'):
        return '.bmp'
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return '.webp'
    if header.startswith(b'II*\x00') or header.startswith(b'MM\x00*'):
        return '.tiff'
    if header[4:8] == b'ftyp' and header[8:12] in (b'heic', b'heix', b'hevc', b'mif1', b'heif'):
        return '.heic'

    logger.warning(f"无法检测图片类型: {file_path}, 使用默认.jpg扩展名")
    return '.jpg'


def generate_temp_filename(media_group_id=None):
    """生成临时文件名关键字（不带扩展名）。"""
    timestamp = int(time.time() * 1000)
    if media_group_id:
        return str(timestamp)
    return f"single_{timestamp}"


def get_archive_ext(file_path):
    """通过文件头检测压缩包/文档类型，返回扩展名。"""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)
        if header[:2] == b'PK':
            return '.zip'
        if header[:4] == b'Rar!':
            return '.rar'
        if header[:6] == b'7z\xbc\xaf\x27\x1c':
            return '.7z'
        if header[:2] == b'\x1f\x8b':
            return '.gz'
        if header[:5] == b'\xfd7zXZ':
            return '.xz'
        if header[:4] == b'\x25\x50\x44\x46':
            return '.pdf'
        if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            return '.doc'
        return None
    except Exception:
        return None
