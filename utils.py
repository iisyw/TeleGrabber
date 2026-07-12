#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import errno
import json
from datetime import datetime, timezone
import logging
import mimetypes
import re
import sqlite3
import threading
import contextlib

from config import SAVE_DIR, DATA_DIR, AUDIT_LOG

logger = logging.getLogger(__name__)


def get_message_date(message):
    """从 PTB Message 对象获取原始消息时间（转发消息使用原消息时间）"""
    if message.forward_origin and message.forward_origin.date:
        return message.forward_origin.date
    return message.date


def get_message_id(message):
    """从 PTB Message 对象获取原始消息 ID（转发消息使用原消息 ID），没有则返回 None"""
    if message.forward_origin:
        return getattr(message.forward_origin, 'message_id', None)
    return None


def utc_to_local(dt):
    """将 naive UTC datetime 转为本地 naive datetime"""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def get_save_directory(user, source_name=None, source_type=None):
    """创建并返回保存目录路径 (统一媒体库版)
    
    Args:
        user: Telegram用户对象
        source_name: 可选的来源名称
        source_type: 可选的来源类型
        
    Returns:
        str: 保存目录的完整路径
    """
    if not source_name:
        source_dir = os.path.join(SAVE_DIR, "unsorted")
    elif source_type in ["user", "private_user", "unknown_forward"]:
        source_dir = os.path.join(SAVE_DIR, "direct_messages", source_name)
    else:
        source_dir = os.path.join(SAVE_DIR, source_name)
    
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
    """初始化数据库"""
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
            source_name TEXT,
            source_id TEXT,
            source_username TEXT DEFAULT '',
            source_link1 TEXT,
            source_link2 TEXT DEFAULT '',
            source_type TEXT,
            message_time TEXT,
            message_id INTEGER,
            remark TEXT DEFAULT ''
        )
    ''')
    # 迁移 source → source_name
    try:
        cursor.execute("ALTER TABLE media_metadata RENAME COLUMN source TO source_name")
    except sqlite3.OperationalError:
        pass
    # 迁移 source_link → source_link1
    try:
        cursor.execute("ALTER TABLE media_metadata RENAME COLUMN source_link TO source_link1")
    except sqlite3.OperationalError:
        pass
    # 为已有数据库添加缺失的列
    for col in ['message_time', 'message_id', 'remark', 'source_username', 'source_link2']:
        try:
            if col == 'message_time':
                cursor.execute("ALTER TABLE media_metadata ADD COLUMN message_time TEXT")
            elif col == 'message_id':
                cursor.execute("ALTER TABLE media_metadata ADD COLUMN message_id INTEGER")
            elif col == 'remark':
                cursor.execute("ALTER TABLE media_metadata ADD COLUMN remark TEXT DEFAULT ''")
            elif col == 'source_username':
                cursor.execute("ALTER TABLE media_metadata ADD COLUMN source_username TEXT DEFAULT ''")
            elif col == 'source_link2':
                cursor.execute("ALTER TABLE media_metadata ADD COLUMN source_link2 TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
    cursor.execute('PRAGMA journal_mode=WAL')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS _schema_docs (
            table_name TEXT,
            column_name TEXT,
            description TEXT,
            PRIMARY KEY (table_name, column_name)
        )
    ''')
    cursor.executemany('INSERT OR IGNORE INTO _schema_docs (table_name, column_name, description) VALUES (?, ?, ?)', [
        ('media_metadata', 'id', '自增主键'),
        ('media_metadata', 'user_id', '储存者的 Telegram 用户 ID（转发消息到 bot 的人）'),
        ('media_metadata', 'user_name', '储存者的 Telegram 用户名'),
        ('media_metadata', 'filename', '本地文件名（含扩展名）'),
        ('media_metadata', 'datetime', '下载完成时间（本地时间）'),
        ('media_metadata', 'file_id', 'Telegram file_id，可用于重新下载'),
        ('media_metadata', 'file_unique_id', 'Telegram 文件唯一标识，用于去重'),
        ('media_metadata', 'media_group_id', '媒体组 ID（相册）'),
        ('media_metadata', 'media_type', '媒体类型：photo/video/document/audio/animation'),
        ('media_metadata', 'caption', '原始文案'),
        ('media_metadata', 'source_name', '来源名称（原始发送者的频道标题/群组名/用户名/bot名）'),
        ('media_metadata', 'source_id', '来源 ID（原始发送者的 chat_id）'),
        ('media_metadata', 'source_link1', '来源链接1（优先用户名格式，如 https://t.me/username/msg_id）'),
        ('media_metadata', 'source_link2', '来源链接2（数字 ID 格式，如 https://t.me/c/id/msg_id）'),
        ('media_metadata', 'source_username', '来源用户名（Telegram 用户名，如 sifangktv10）'),
        ('media_metadata', 'source_type', '来源类型：channel/bot/group/private_user（原始发送者类型）'),
        ('media_metadata', 'message_time', '原始消息时间（本地时间，转发时取原消息时间）'),
        ('media_metadata', 'message_id', '原始消息 ID（转发时取原消息 ID）'),
        ('media_metadata', 'remark', '备注（如受保护内容无法下载等）'),
    ])
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
                SELECT filename, source_name, caption, source_username, source_link1, source_link2 FROM media_metadata WHERE file_unique_id = ?
            ''', (file_unique_id,))
            row = cursor.fetchone()
        finally:
            conn.close()
    
    if row:
        return {
            'filename': row[0],
            'source_name': row[1],
            'caption': row[2],
            'source_username': row[3],
            'source_link1': row[4],
            'source_link2': row[5],
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
                "SELECT source_name, COUNT(*) AS c FROM media_metadata "
                "WHERE source_name IS NOT NULL AND source_name != '' "
                "GROUP BY source_name ORDER BY c DESC LIMIT 5"
            )
            stats['top_sources'] = [(row[0], row[1]) for row in cur.fetchall()]
        finally:
            conn.close()
    return stats


def save_to_db(user, media_obj, file_name, save_dir=None, media_group_id=None, media_type='photo', caption=None, source_name=None, source_id=None, source_link1=None, source_link2=None, source_username=None, source_type=None, message_time=None, message_id=None, remark=None):
    """将媒体元数据保存到SQLite数据库"""
    if not caption:
        caption = ''

    # 统一 message_time 格式，去掉时区信息
    if message_time:
        message_time = message_time.replace('+00:00', '').replace('+0000', '').replace('Z', '')
    
    try:
        with _db_lock:
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO media_metadata (
                        user_id, user_name, filename, datetime, file_id, file_unique_id,
                        media_group_id, media_type, caption, source_name, source_id,
                        source_username, source_link1, source_link2, source_type, message_time, message_id, remark
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    source_name or '',
                    source_id or '',
                    source_username or '',
                    source_link1 or '',
                    source_link2 or '',
                    source_type or 'unknown',
                    message_time,
                    message_id,
                    remark or '',
                ))
                conn.commit()
            finally:
                conn.close()
        logger.debug(f"已将{media_type}元数据保存至数据库")

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

    try:
        with _db_lock:
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(record_ids))

                # 1. 一次性查出所有待删除记录的信息（避免 N+1 查询）
                cursor.execute(
                    f"SELECT id, filename, source_name, source_type, user_id, user_name "
                    f"FROM media_metadata WHERE id IN ({placeholders})",
                    tuple(record_ids),
                )
                rows = cursor.fetchall()

                for _id, filename, source_name, source_type, user_id, user_name in rows:
                    user_stub = type('User', (), {'id': user_id, 'username': user_name, 'first_name': user_name})
                    save_dir = get_save_directory(user_stub, source_name, source_type)
                    file_path = os.path.join(save_dir, filename)

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

AUDIT_DIR = DATA_DIR
_audit_lock = threading.Lock()


def _audit_source_type(entry):
    """从 entry 中提取来源分类：channel / bot / group / private / other"""
    # group_info 路径已自带 source_type
    st = entry.get('source_type')
    if st in ('channel', 'bot', 'group'):
        return st
    if st in ('user', 'private', 'private_user'):
        return 'private'

    # message 路径：从 raw.to_dict 中提取
    raw = entry.get('raw')
    if isinstance(raw, dict):
        # 优先 forward_origin
        fo = raw.get('forward_origin') or {}
        fo_type = fo.get('type')
        if fo_type == 'channel':
            return 'channel'
        if fo_type in ('chat', 'supergroup'):
            return 'group'
        if fo_type == 'hidden_user':
            return 'private'
        if fo_type == 'user':
            sender = fo.get('sender_user') or {}
            return 'bot' if sender.get('is_bot') else 'private'

        # 没有 forward_origin：看 chat_type
        chat_type = raw.get('chat', {}).get('type')
        if chat_type == 'channel':
            return 'channel'
        if chat_type in ('supergroup', 'group'):
            return 'group'
        if chat_type == 'private':
            from_user = raw.get('from_user') or {}
            return 'bot' if from_user.get('is_bot') else 'private'
        if chat_type == 'bot':
            return 'bot'

    return 'other'


_source_type_labels = {
    'channel': '频道',
    'bot': '机器人',
    'group': '群组',
    'private': '用户',
    'other': '其他',
}


def _audit_path(source_type):
    return os.path.join(AUDIT_DIR, f'audit_{source_type}.json')


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
            # 原始消息 ID 和时间
            fo = getattr(message, 'forward_origin', None)
            if fo:
                msg_id = getattr(fo, 'message_id', None) or getattr(message, 'message_id', None)
                msg_date = getattr(fo, 'date', None)
            else:
                msg_id = message.message_id
                msg_date = getattr(message, 'date', None)
            if msg_id is not None:
                entry['message_id'] = msg_id
            if msg_date is not None:
                try:
                    entry['message_time'] = msg_date.isoformat() if hasattr(msg_date, 'isoformat') else str(msg_date)
                except Exception:
                    pass
        except Exception:
            pass

    if group_info is not None:
        try:
            entry['chat_id'] = group_info.get('chat_id')
            entry['media_group_id'] = group_info.get('media_group_id')
            entry['user_id'] = group_info.get('user_id')
            entry['source_name'] = group_info.get('source_name')
            entry['source_link1'] = group_info.get('source_link1')
            entry['source_link2'] = group_info.get('source_link2')
            entry['source_type'] = group_info.get('source_type')
            entry['caption'] = (group_info.get('caption') or '')[:500]
            entry['chat_type'] = group_info.get('chat_type')
            items = group_info.get('media_items', [])
            entry['item_count'] = len(items)
            entry['item_types'] = [m.get('media_type') for m in items]
            # 取首项的消息时间和 message_id
            if items:
                first = items[0]
                if first.get('message_date'):
                    entry['message_time'] = first['message_date']
                elif first.get('message_time'):
                    entry['message_time'] = first['message_time']
                if first.get('message_id') is not None:
                    entry['message_id'] = first['message_id']
            # raw 写入完整原始数据（包含 media_items）
            raw_msg = group_info.get('raw_message')
            if isinstance(raw_msg, dict):
                entry['raw'] = raw_msg
            else:
                entry['raw'] = {k: v for k, v in group_info.items() if k != 'raw_message'}
        except Exception:
            pass

    if raw_dict is not None:
        entry['raw'] = raw_dict

    if note:
        entry['note'] = note

    try:
        st = _audit_source_type(entry)
        entry['source_type'] = st
        path = _audit_path(st)
        with _audit_lock:
            entries = []
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                    if isinstance(existing, list):
                        entries = existing
                except Exception:
                    entries = []
            entries.append(entry)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"写入审计日志失败: {e}")
