#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SQLite schema、媒体元数据 CRUD、去重与删除。"""

import os
import sqlite3
import threading
import contextlib
import logging
from datetime import datetime

from .config import DATA_DIR
from .media_files import get_save_directory
from .thumbnails import schedule_thumbnail_generation, delete_thumbnail

logger = logging.getLogger(__name__)


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
            width INTEGER,
            height INTEGER,
            file_size INTEGER,
            caption TEXT,
            source_name TEXT,
            source_id TEXT,
            source_username TEXT DEFAULT '',
            source_link1 TEXT,
            source_type TEXT,
            message_time TEXT,
            current_message_id INTEGER,
            original_message_id INTEGER,
            remark TEXT DEFAULT '',
            favorite INTEGER NOT NULL DEFAULT 0,
            tags TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    cursor.execute('PRAGMA journal_mode=WAL')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_source ON media_metadata(source_type, source_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_group ON media_metadata(media_group_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_message_time ON media_metadata(message_time DESC, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_datetime ON media_metadata(datetime DESC, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_type ON media_metadata(media_type, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_source_name ON media_metadata(source_name, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_sort_expr ON media_metadata(COALESCE(message_time, datetime) DESC, id DESC)")

    # 全文检索（trigram 支持中文/子串），与 media_metadata 保持同步
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    try:
        cursor.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5("
            "caption, filename, source_name, "
            "content='media_metadata', content_rowid='id', tokenize='trigram')"
        )
        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS media_fts_ai AFTER INSERT ON media_metadata BEGIN
                INSERT INTO media_fts(rowid, caption, filename, source_name)
                VALUES (new.id, new.caption, new.filename, new.source_name);
            END
        ''')
        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS media_fts_ad AFTER DELETE ON media_metadata BEGIN
                INSERT INTO media_fts(media_fts, rowid, caption, filename, source_name)
                VALUES ('delete', old.id, old.caption, old.filename, old.source_name);
            END
        ''')
        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS media_fts_au AFTER UPDATE ON media_metadata BEGIN
                INSERT INTO media_fts(media_fts, rowid, caption, filename, source_name)
                VALUES ('delete', old.id, old.caption, old.filename, old.source_name);
                INSERT INTO media_fts(rowid, caption, filename, source_name)
                VALUES (new.id, new.caption, new.filename, new.source_name);
            END
        ''')
        rebuilt = cursor.execute(
            "SELECT value FROM app_meta WHERE key = 'fts_rebuilt'"
        ).fetchone()
        if not rebuilt:
            # 外部内容表的 COUNT(*) 永远等于媒体表行数，不能用来判断索引是否已建。
            cursor.execute("INSERT INTO media_fts(media_fts) VALUES ('rebuild')")
            cursor.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('fts_rebuilt', '1')"
            )
    except sqlite3.OperationalError as e:
        logger.warning(f"FTS5 初始化失败，搜索将回退为 LIKE: {e}")

    # 来源管理（置顶 / 隐藏 / 备注）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS source_meta (
            source_name TEXT PRIMARY KEY,
            pinned INTEGER NOT NULL DEFAULT 0,
            hidden INTEGER NOT NULL DEFAULT 0,
            remark TEXT DEFAULT '',
            updated_at TEXT
        )
    ''')

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
        ('media_metadata', 'width', '媒体原始宽度（像素）'),
        ('media_metadata', 'height', '媒体原始高度（像素）'),
        ('media_metadata', 'file_size', '媒体文件大小（字节）'),
        ('media_metadata', 'caption', '原始文案'),
        ('media_metadata', 'source_name', '来源名称（原始发送者的频道标题/群组名/用户名/bot名）'),
        ('media_metadata', 'source_id', '来源 ID（原始发送者的 chat_id）'),
        ('media_metadata', 'source_link1', '来源链接（优先用户名格式，如 https://t.me/username/msg_id）'),
        ('media_metadata', 'source_username', '来源用户名（Telegram 用户名，如 sifangktv10）'),
        ('media_metadata', 'source_type', '来源类型：channel/bot/group/private_user（原始发送者类型）'),
        ('media_metadata', 'message_time', '原始消息时间（本地时间，转发时取原消息时间）'),
        ('media_metadata', 'current_message_id', '机器人当前会话收到的消息 ID，用于重试下载'),
        ('media_metadata', 'original_message_id', '原始来源消息 ID，用于溯源；非转发消息可为空'),
        ('media_metadata', 'remark', '备注（如受保护内容无法下载等）'),
        ('media_metadata', 'favorite', '是否收藏：0 否 / 1 是'),
        ('media_metadata', 'tags', '标签列表，存储为 ,tag1,tag2, 形式'),
    ])
    conn.commit()
    conn.close()

# 全局数据库锁，由于 SQLite 在多线程写入时容易锁表，使用此锁确保串口化写入
_db_lock = threading.Lock()

def get_db_connection():
    """获取数据库连接；WAL 模式仅在 init_db() 中设置一次。"""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute('PRAGMA busy_timeout=60000')
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
                SELECT filename, source_name, caption, source_username, source_link1 FROM media_metadata WHERE file_unique_id = ?
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


def save_to_db(user, media_obj, file_name, save_dir=None, media_group_id=None, media_type='photo', caption=None, source_name=None, source_id=None, source_link1=None, source_username=None, source_type=None, message_time=None, current_message_id=None, original_message_id=None, width=None, height=None, file_size=None, remark=None):
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
                        source_username, source_link1, source_type, message_time,
                        current_message_id, original_message_id, width, height, file_size, remark
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    source_type or 'unknown',
                    message_time,
                    current_message_id,
                    original_message_id,
                    width,
                    height,
                    file_size,
                    remark or '',
                ))
                conn.commit()
            finally:
                conn.close()
        logger.debug(f"已将{media_type}元数据保存至数据库")

        # 异步预热缩略图（图片走 Pillow，视频在 ffmpeg 可用时抽帧）
        if save_dir and file_name:
            schedule_thumbnail_generation(
                os.path.join(save_dir, file_name),
                getattr(media_obj, 'file_unique_id', None),
                media_type,
            )

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
                    f"SELECT id, filename, source_name, source_type, user_id, user_name, file_unique_id "
                    f"FROM media_metadata WHERE id IN ({placeholders})",
                    tuple(record_ids),
                )
                rows = cursor.fetchall()

                deletable_ids = []
                deleted_unique_ids = []
                for _id, filename, source_name, source_type, user_id, user_name, unique_id in rows:
                    user_stub = type('User', (), {'id': user_id, 'username': user_name, 'first_name': user_name})
                    save_dir = get_save_directory(user_stub, source_name, source_type)
                    file_path = os.path.join(save_dir, filename)

                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            logger.info(f"已物理删除文件: {file_path}")
                        except OSError as e:
                            logger.error(f"物理删除文件失败，保留数据库记录 {file_path}: {e}")
                            continue
                    deletable_ids.append(_id)
                    deleted_unique_ids.append(unique_id)

                # 2. 只删除文件已成功移除或原本不存在的数据库记录
                if deletable_ids:
                    deletable_placeholders = ",".join("?" * len(deletable_ids))
                    cursor.execute(
                        f"DELETE FROM media_metadata WHERE id IN ({deletable_placeholders})",
                        tuple(deletable_ids),
                    )
                else:
                    deleted_count = 0
                    conn.commit()
                    return deleted_count
                deleted_count = cursor.rowcount
                conn.commit()
            finally:
                conn.close()

        # 缩略图是派生文件，跟随原记录一起清理
        for unique_id in deleted_unique_ids:
            delete_thumbnail(unique_id)

    except Exception as e:
        logger.error(f"按 ID 批量删除媒体记录失败: {e}")

    return deleted_count

def delete_media_records(file_unique_ids):
    """根据 unique_id 列表删除媒体记录和对应的物理文件"""
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
