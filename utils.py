#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import errno
import csv
import json
from datetime import datetime
import logging
import mimetypes
import re
import sqlite3
import threading
import contextlib

from config import SAVE_DIR, DATA_DIR, AUDIT_LOG

logger = logging.getLogger(__name__)

def get_save_directory(user, source=None, source_type=None):
    """创建并返回保存目录路径 (统一媒体库版)
    
    Args:
        user: Telegram用户对象
        source: 可选的来源信息
        source_type: 可选的来源类型
        
    Returns:
        str: 保存目录的完整路径
    """
    # 如果没有来源信息，统一存放在 unsorted 目录
    if not source:
        source_dir = os.path.join(SAVE_DIR, "unsorted")
    elif source_type in ["user", "private_user", "unknown_forward"]:
        # 用户来源统一放在 direct_messages 目录
        source_dir = os.path.join(SAVE_DIR, "direct_messages", source)
    else:
        # 频道、群组等，直接在 downloads 下创建来源文件夹
        source_dir = os.path.join(SAVE_DIR, source)
    
    # 确保目录存在
    # 重试处理 ESTALE (Stale file handle) — Docker overlay 文件系统常见问题
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
    """检测视频文件的实际格式并返回正确的扩展名
    
    Args:
        file_path: 视频文件路径
        
    Returns:
        str: 正确的文件扩展名（带点，如.mp4）
    """
    # 初始化mimetypes
    if not mimetypes.inited:
        mimetypes.init()
    
    # 尝试通过文件头部字节判断
    video_signatures = {
        b'\x00\x00\x00\x18\x66\x74\x79\x70\x6D\x70\x34\x32': '.mp4',  # MP4
        b'\x00\x00\x00\x1C\x66\x74\x79\x70\x6D\x70\x34\x32': '.mp4',  # MP4
        b'\x00\x00\x00\x20\x66\x74\x79\x70\x69\x73\x6F\x6D': '.mp4',  # MP4 (ISO)
        b'\x1A\x45\xDF\xA3': '.webm',  # WebM
        b'\x00\x00\x00\x14\x66\x74\x79\x70\x71\x74\x20\x20': '.mov',  # QuickTime
        b'\x52\x49\x46\x46': '.avi'    # AVI
    }
    
    try:
        with open(file_path, 'rb') as f:
            header = f.read(12)  # 读取前12字节
            for sig, ext in video_signatures.items():
                if header.startswith(sig):
                    return ext
    except Exception as e:
        logger.error(f"读取文件头部错误: {e}")
    
    # 通过mime类型判断
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type and mime_type.startswith('video/'):
        ext = mimetypes.guess_extension(mime_type)
        if ext:
            return ext
    
    # 如果无法检测，默认为mp4
    logger.warning(f"无法检测视频类型: {file_path}, 使用默认.mp4扩展名")
    return '.mp4'

def get_image_extension(file_path):
    """检测图片文件的实际格式并返回正确的扩展名

    Python 3.13 移除了标准库 imghdr，这里改用文件头魔数 (magic bytes) 自行判断。

    Args:
        file_path: 图片文件路径

    Returns:
        str: 正确的文件扩展名（带点，如.jpg）
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)
    except Exception as e:
        logger.error(f"读取图片文件头失败: {e}")
        return '.jpg'

    # 按文件头魔数判断常见图片格式
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
    # TIFF (大端/小端)
    if header.startswith(b'II*\x00') or header.startswith(b'MM\x00*'):
        return '.tiff'
    # HEIC/HEIF: ftyp box，brand 含 heic/heif/mif1
    if header[4:8] == b'ftyp' and header[8:12] in (b'heic', b'heix', b'hevc', b'mif1', b'heif'):
        return '.heic'

    logger.warning(f"无法检测图片类型: {file_path}, 使用默认.jpg扩展名")
    return '.jpg'

def generate_temp_filename(media_group_id=None):
    """生成临时文件名关键字（不带扩展名）
    
    Args:
        media_group_id: 可选的媒体组ID
        
    Returns:
        str: 生成的标识符
    """
    timestamp = int(time.time() * 1000)
    if media_group_id:
        return str(timestamp)
    return f"single_{timestamp}"

DB_PATH = os.path.join(DATA_DIR, "telegrabber.db")

def init_db():
    """初始化数据库 (含用户信息字段)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS media_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT,
            filename TEXT,
            datetime TEXT,
            file_id TEXT,
            file_unique_id TEXT UNIQUE,
            media_group_id TEXT,
            media_type TEXT,
            caption TEXT,
            source TEXT,
            source_id TEXT,
            source_link TEXT,
            source_type TEXT
        )
    ''')
    cursor.execute('PRAGMA journal_mode=WAL')
    conn.commit()
    conn.close()

# 全局数据库锁，由于 SQLite 在多线程写入时容易锁表，使用此锁确保串口化写入
_db_lock = threading.Lock()

def get_db_connection():
    """获取数据库连接 (WAL 模式, 60s 超时)"""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except:
        pass
    return conn

@contextlib.contextmanager
def get_db_cursor():
    """数据库游标上下文管理器，自动加锁并在结束时释放"""
    with _db_lock:
        conn = get_db_connection()
        try:
            yield conn.cursor()
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def get_duplicate_info(file_unique_id):
    """根据 unique_id 查找重复项"""
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT filename, source, caption, source_link FROM media_metadata WHERE file_unique_id = ?
            ''', (file_unique_id,))
            row = cursor.fetchone()
        finally:
            conn.close()
    
    if row:
        return {
            'filename': row[0],
            'source': row[1],
            'caption': row[2],
            'source_link': row[3],
        }
    return None


def get_library_stats():
    """统计媒体库概况：总数、今日新增、按来源 Top、按类型分布。"""
    stats = {'total': 0, 'today': 0, 'by_type': {}, 'top_sources': []}
    with _db_lock:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM media_metadata")
            stats['total'] = cur.fetchone()[0]

            # 今日新增（datetime 以 ISO 字符串存储，按日期前缀匹配）
            today = datetime.now().strftime("%Y-%m-%d")
            cur.execute("SELECT COUNT(*) FROM media_metadata WHERE datetime LIKE ?", (f"{today}%",))
            stats['today'] = cur.fetchone()[0]

            cur.execute("SELECT media_type, COUNT(*) FROM media_metadata GROUP BY media_type")
            stats['by_type'] = {row[0] or 'unknown': row[1] for row in cur.fetchall()}

            cur.execute(
                "SELECT source, COUNT(*) AS c FROM media_metadata "
                "WHERE source IS NOT NULL AND source != '' "
                "GROUP BY source ORDER BY c DESC LIMIT 5"
            )
            stats['top_sources'] = [(row[0], row[1]) for row in cur.fetchall()]
        finally:
            conn.close()
    return stats

# 全局 CSV 写入锁，防止并发写入导致文件冲突或性能瓶颈
_csv_lock = threading.Lock()

def delete_csv_records(save_dir, filenames):
    """从 save_dir 下的 metadata.csv 中删除指定文件名的行"""
    if not filenames:
        return
        
    csv_path = os.path.join(save_dir, "metadata.csv")
    if not os.path.exists(csv_path):
        return
        
    try:
        with _csv_lock:
            temp_path = csv_path + ".tmp"
            headers = [
                'filename', 'datetime', 'file_id', 'file_unique_id', 
                'media_group_id', 'media_type', 'caption', 'source', 
                'source_id', 'source_link', 'source_type'
            ]
            
            with open(csv_path, 'r', encoding='utf-8-sig') as fin, \
                 open(temp_path, 'w', newline='', encoding='utf-8-sig') as fout:
                reader = csv.DictReader(fin)
                writer = csv.DictWriter(fout, fieldnames=headers)
                writer.writeheader()
                
                for row in reader:
                    if row['filename'] not in filenames:
                        writer.writerow(row)
            
            os.replace(temp_path, csv_path)
            logger.info(f"已更新 CSV 备份: {csv_path} (删除了 {len(filenames)} 条记录)")
    except Exception as e:
        logger.error(f"更新 CSV 备份失败: {e}")

def save_to_db(user, media_obj, file_name, save_dir=None, media_group_id=None, media_type='photo', caption=None, source=None, source_id=None, source_link=None, source_type=None):
    """将媒体元数据保存到SQLite数据库，并同步追加到本地 CSV 作为物理备份"""
    # 清洗标题：将换行替换为空格，并将多个空格合并为一个
    if caption:
        caption = caption.replace('\n', ' ').replace('\r', ' ')
        caption = re.sub(r'\s+', ' ', caption).strip()
    else:
        caption = ''
    
    try:
        with _db_lock:
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO media_metadata (
                        user_id, user_name, filename, datetime, file_id, file_unique_id, 
                        media_group_id, media_type, caption, source, source_id, 
                        source_link, source_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user.id,
                    user.username or user.first_name,
                    file_name,
                    datetime.now().isoformat(),
                    media_obj.file_id,
                    media_obj.file_unique_id,
                    media_group_id or '',
                    media_type,
                    caption,
                    source or '',
                    source_id or '',
                    source_link or '',
                    source_type or 'unknown'
                ))
                conn.commit()
            finally:
                conn.close()
        logger.debug(f"已将{media_type}元数据保存至数据库")
        
        # 同步保存到本地 CSV 作为物理备份 (如果指定了 save_dir)
        if save_dir:
            try:
                # 使用锁确保 CSV 写入的原子性，防止并发下载时文件内容错乱
                with _csv_lock:
                    csv_path = os.path.join(save_dir, "metadata.csv")
                    file_exists = os.path.isfile(csv_path)
                    
                    headers = [
                        'filename', 'datetime', 'file_id', 'file_unique_id', 
                        'media_group_id', 'media_type', 'caption', 'source', 
                        'source_id', 'source_link', 'source_type'
                    ]
                    
                    with open(csv_path, 'a', newline='', encoding='utf-8-sig') as f:
                        writer = csv.DictWriter(f, fieldnames=headers)
                        if not file_exists:
                            writer.writeheader()
                        
                        writer.writerow({
                            'filename': file_name,
                            'datetime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            'file_id': media_obj.file_id,
                            'file_unique_id': media_obj.file_unique_id,
                            'media_group_id': media_group_id or '',
                            'media_type': media_type,
                            'caption': caption,
                            'source': source or '',
                            'source_id': source_id or '',
                            'source_link': source_link or '',
                            'source_type': source_type or 'unknown'
                        })
                logger.debug(f"已同步追加 CSV 备份: {csv_path}")
            except Exception as e:
                logger.error(f"同步 CSV 备份失败: {e}")

        return True
    except sqlite3.IntegrityError:
        logger.warning(f"检测到重复的 file_unique_id: {media_obj.file_unique_id}")
        return False
    except Exception as e:
        logger.error(f"保存元数据到数据库失败: {e}")
        return False

def delete_media_by_id(record_ids):
    """根据数据库自增 ID 列表删除媒体记录和对应的物理文件"""
    if not record_ids:
        return 0

    deleted_count = 0
    dir_files_map = {}  # {save_dir: [filenames]}

    try:
        with _db_lock:
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(record_ids))

                # 1. 一次性查出所有待删除记录的信息（避免 N+1 查询）
                cursor.execute(
                    f"SELECT id, filename, source, source_type, user_id, user_name "
                    f"FROM media_metadata WHERE id IN ({placeholders})",
                    tuple(record_ids),
                )
                rows = cursor.fetchall()

                for _id, filename, source, source_type, user_id, user_name in rows:
                    # 构建虚拟用户对象以获取目录
                    user_stub = type('User', (), {'id': user_id, 'username': user_name, 'first_name': user_name})
                    save_dir = get_save_directory(user_stub, source, source_type)
                    file_path = os.path.join(save_dir, filename)

                    dir_files_map.setdefault(save_dir, []).append(filename)

                    # 物理删除文件
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            logger.info(f"已物理删除文件: {file_path}")
                        except Exception as e:
                            logger.error(f"物理删除文件失败 {file_path}: {e}")

                # 2. 一次性从数据库删除所有记录
                cursor.execute(
                    f"DELETE FROM media_metadata WHERE id IN ({placeholders})",
                    tuple(record_ids),
                )
                deleted_count = cursor.rowcount
                conn.commit()
            finally:
                conn.close()

        # 3. 更新 CSV 备份
        for save_dir, filenames in dir_files_map.items():
            delete_csv_records(save_dir, filenames)

    except Exception as e:
        logger.error(f"按 ID 批量删除媒体记录失败: {e}")

    return deleted_count

def delete_media_records(file_unique_ids):
    """根据 unique_id 列表删除媒体记录和对应的物理文件 (向下兼容)"""
    if not file_unique_ids:
        return 0

    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(file_unique_ids))
            cursor.execute(
                f"SELECT id FROM media_metadata WHERE file_unique_id IN ({placeholders})",
                tuple(file_unique_ids),
            )
            ids = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    return delete_media_by_id(ids)


# --- 审计日志 ---

AUDIT_LOG_PATH = os.path.join(DATA_DIR, 'audit.jsonl')
_audit_lock = threading.Lock()


def append_audit(msg_type, message=None, group_info=None, raw_dict=None, note=None):
    """记录收到的消息到审计日志，便于分析消息来源和模式。

    参数:
        msg_type: 消息类型 ('photo', 'video', 'media_group', 'text', 'link', ...)
        message:  PTB Message 对象（含 to_dict 方法）
        group_info: 媒体组的 group_info dict（当 message 为 None 时使用）
        raw_dict:  任意字典，直接写入 raw 字段（覆盖自动提取的 raw）
        note:      备注文本
    """
    if not AUDIT_LOG:
        return

    entry = {
        'time': datetime.now().isoformat(),
        'type': msg_type,
    }

    if message is not None:
        try:
            if hasattr(message, 'to_dict'):
                entry['raw'] = message.to_dict()
            elif isinstance(message, dict):
                entry['raw'] = message
        except Exception:
            pass

        # 提取常用字段方便 grep
        try:
            if hasattr(message, 'chat') and message.chat:
                entry['chat_id'] = message.chat.id
                entry['chat_type'] = message.chat.type
            if hasattr(message, 'from_user') and message.from_user:
                entry['user_id'] = message.from_user.id
            if hasattr(message, 'caption') and message.caption:
                entry['caption'] = message.caption[:500]
            if hasattr(message, 'media_group_id') and message.media_group_id:
                entry['media_group_id'] = message.media_group_id
        except Exception:
            pass

    if group_info is not None:
        try:
            entry['chat_id'] = group_info.get('chat_id')
            entry['media_group_id'] = group_info.get('media_group_id')
            entry['user_id'] = group_info.get('user_id')
            entry['source'] = group_info.get('source')
            entry['source_link'] = group_info.get('source_link')
            entry['source_type'] = group_info.get('source_type')
            entry['caption'] = (group_info.get('caption') or '')[:500]
            entry['chat_type'] = group_info.get('chat_type')
            items = group_info.get('media_items', [])
            entry['item_count'] = len(items)
            entry['item_types'] = [m.get('media_type') for m in items]
            # 优先使用完整的原始消息数据（包含 entities/caption_entities）
            raw_msg = group_info.get('raw_message')
            if isinstance(raw_msg, dict):
                entry['raw'] = raw_msg
            else:
                # 降级：从 group_info 中提取已知字段
                safe = {k: v for k, v in group_info.items() if k not in ('media_items', 'raw_message')}
                safe['media_items_count'] = len(items)
                entry['raw'] = safe
        except Exception:
            pass

    if raw_dict is not None:
        entry['raw'] = raw_dict

    if note:
        entry['note'] = note

    try:
        with _audit_lock:
            with open(AUDIT_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.warning(f"写入审计日志失败: {e}")
