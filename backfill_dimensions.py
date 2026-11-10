#!/usr/bin/env python3
"""回填 media_metadata 中缺失的 width/height/file_size。

图片用 Pillow 读取本地文件；视频优先用 ffprobe，未安装则用 hachoir。
文件大小直接读取本地文件。可重复执行，只处理缺失字段的记录。
"""

import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import config  # noqa: F401  确保配置与目录初始化
import utils

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi'}


def image_dimensions(path):
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def video_dimensions(path):
    ffprobe = shutil.which('ffprobe')
    if ffprobe:
        try:
            result = subprocess.run(
                [
                    ffprobe, '-v', 'error', '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height', '-of', 'json', path,
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            streams = json.loads(result.stdout).get('streams') or []
            if streams:
                return int(streams[0]['width']), int(streams[0]['height'])
        except Exception:
            pass

    # ffprobe 不可用时用 hachoir 读取 MP4/MOV 等容器元数据
    try:
        from hachoir.metadata import extractMetadata
        from hachoir.parser import createParser

        metadata = extractMetadata(createParser(path))
        width = metadata.get('width')
        height = metadata.get('height')
        if width and height:
            return int(width), int(height)
    except Exception:
        pass
    return None


def main():
    utils.init_db()
    conn = utils.get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, filename, source_name, source_type, user_id, user_name, media_type, file_size "
            "FROM media_metadata WHERE width IS NULL OR height IS NULL OR file_size IS NULL"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print('没有需要回填的媒体')
        return

    updated = 0
    skipped = 0
    for record_id, filename, source_name, source_type, user_id, user_name, media_type, old_file_size in rows:
        user_stub = SimpleNamespace(id=user_id, username=user_name, first_name=user_name)
        save_dir = utils.get_save_directory(user_stub, source_name, source_type)
        path = os.path.join(save_dir, filename)
        if not os.path.exists(path):
            skipped += 1
            continue

        file_size = os.path.getsize(path)
        ext = os.path.splitext(filename)[1].lower()
        dimensions = video_dimensions(path) if (media_type == 'video' or ext in VIDEO_EXTS) else image_dimensions(path)
        width, height = dimensions if dimensions else (None, None)

        if width is None and height is None and file_size == old_file_size:
            skipped += 1
            continue

        with utils._db_lock:
            conn = utils.get_db_connection()
            try:
                conn.execute(
                    "UPDATE media_metadata SET "
                    "width = COALESCE(width, ?), "
                    "height = COALESCE(height, ?), "
                    "file_size = COALESCE(file_size, ?) WHERE id = ?",
                    (width, height, file_size, record_id),
                )
                conn.commit()
            finally:
                conn.close()
        updated += 1
        dim_text = f"{width}x{height}" if width and height else "-"
        print(f'id={record_id} {dim_text} {file_size} bytes {filename}')

    print(f'完成：更新 {updated} 条，跳过 {skipped} 条')

if __name__ == '__main__':
    main()
