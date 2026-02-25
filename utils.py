#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import csv
import hashlib
import imghdr
from datetime import datetime
import logging
import mimetypes
import re
import sqlite3

from config import SAVE_DIR

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
    if not os.path.exists(source_dir):
        os.makedirs(source_dir, exist_ok=True)
    
    return source_dir

def get_short_id(media_group_id):
    """从媒体组ID获取标识符
    
    Args:
        media_group_id: Telegram媒体组ID
        
    Returns:
        str: 用于文件名的标识符
    """
    # 使用完整的媒体组ID，或者对于单张图片使用"single"
    return media_group_id if media_group_id else "single"

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
    
    Args:
        file_path: 图片文件路径
        
    Returns:
        str: 正确的文件扩展名（带点，如.jpg）
    """
    # 使用imghdr检测图片类型
    img_type = imghdr.what(file_path)
    
    # 确保获取到了类型
    if img_type:
        # 特殊处理jpeg (imghdr返回'jpeg'但扩展名通常为'jpg')
        if img_type == 'jpeg':
            return '.jpg'
        # webp不在imghdr的默认检测中，需要单独处理
        elif img_type == 'webp':
            return '.webp'
        return f'.{img_type}'
    
    # 如果无法检测，返回默认.jpg
    logger.warning(f"无法检测图片类型: {file_path}, 使用默认.jpg扩展名")
    return '.jpg'

def generate_temp_filename(media_group_id=None):
    """生成临时文件名（不带扩展名）用于下载
    
    Args:
        media_group_id: 可选的媒体组ID
        
    Returns:
        str: 生成的临时文件名
    """
    timestamp = int(time.time() * 1000)  # 毫秒级时间戳
    short_id = get_short_id(media_group_id)
    return f"{short_id}_{timestamp}"

def generate_filename(photo_obj, media_group_id=None):
    """根据图片对象生成简洁的唯一文件名
    
    Args:
        photo_obj: Telegram照片对象
        media_group_id: 可选的媒体组ID
        
    Returns:
        str: 生成的文件名
    """
    # 使用精确到毫秒的纯数字时间戳
    timestamp = int(time.time() * 1000)  # 毫秒级时间戳，例如：1686834561723
    
    short_id = get_short_id(media_group_id)
    return f"{short_id}_{timestamp}.jpg"

DB_PATH = os.path.join(SAVE_DIR, "telegrabber.db")

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
    conn.commit()
    conn.close()

def get_db_connection():
    """获取数据库连接"""
    return sqlite3.connect(DB_PATH)

def get_duplicate_info(file_unique_id):
    """根据 unique_id 查找重复项"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT filename, source, caption, source_link FROM media_metadata WHERE file_unique_id = ?
    ''', (file_unique_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'filename': result[0],
            'source': result[1],
            'caption': result[2],
            'source_link': result[3]
        }
    return None

def save_to_db(user, media_obj, file_name, save_dir=None, media_group_id=None, media_type='photo', caption=None, source=None, source_id=None, source_link=None, source_type=None):
    """将媒体元数据保存到SQLite数据库，并同步追加到本地 CSV 作为物理备份"""
    # 清洗标题：将换行替换为空格，并将多个空格合并为一个
    if caption:
        caption = caption.replace('\n', ' ').replace('\r', ' ')
        caption = re.sub(r'\s+', ' ', caption).strip()
    else:
        caption = ''
    
    try:
        conn = get_db_connection()
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
        conn.close()
        logger.debug(f"已将{media_type}元数据保存至数据库")
        
        # 同步保存到本地 CSV 作为物理备份 (如果指定了 save_dir)
        if save_dir:
            try:
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

def get_mime_type(document):
    """获取文档的MIME类型
    
    Args:
        document: Telegram文档对象
        
    Returns:
        str: MIME类型
    """
    return document.mime_type 