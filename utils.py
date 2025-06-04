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

from config import SAVE_DIR

logger = logging.getLogger(__name__)

def get_save_directory(user, source=None, source_type=None):
    """创建并返回保存目录路径
    
    Args:
        user: Telegram用户对象
        source: 可选的来源信息（如转发来源的频道名或ID）
        source_type: 可选的来源类型（如channel, group, user, bot等）
        
    Returns:
        str: 保存目录的完整路径
    """
    # 创建以用户名命名的子文件夹
    user_dir = os.path.join(SAVE_DIR, f"{user.username or user.first_name}")
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    
    # 创建以日期命名的子文件夹
    date_dir = os.path.join(user_dir, datetime.now().strftime("%Y-%m-%d"))
    if not os.path.exists(date_dir):
        os.makedirs(date_dir)
    
    # 如果没有提供来源信息，直接返回日期目录
    if not source:
        return date_dir
    
    # 根据来源类型决定保存路径
    if source_type in ["user", "private_user", "unknown_forward"]:
        # 用户来源统一放在"users"文件夹下
        users_dir = os.path.join(date_dir, "users")
        if not os.path.exists(users_dir):
            os.makedirs(users_dir)
        
        # 在users目录下创建特定用户的子文件夹
        source_dir = os.path.join(users_dir, source)
    else:
        # 其他类型的来源（频道、群组、机器人等）直接在日期目录下创建子文件夹
        source_dir = os.path.join(date_dir, source)
    
    # 确保目录存在
    if not os.path.exists(source_dir):
        os.makedirs(source_dir)
    
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

def save_to_csv(user, media_obj, file_name, media_group_id=None, media_type='photo', source=None, source_id=None, source_link=None, source_type=None):
    """将媒体元数据保存到CSV文件
    
    Args:
        user: Telegram用户对象
        media_obj: Telegram媒体对象 (照片/视频)
        file_name: 保存的文件名
        media_group_id: 可选的媒体组ID
        media_type: 媒体类型 ('photo' 或 'video')
        source: 可选的来源信息（如转发来源的频道名或ID）
        source_id: 可选的来源ID（如频道ID或用户ID）
        source_link: 可选的来源链接（如频道链接或用户链接）
        source_type: 可选的来源类型（如channel, group, user, bot等）
    """
    # 获取用户目录
    user_dir = os.path.join(SAVE_DIR, f"{user.username or user.first_name}")
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        
    # 获取日期目录
    date_str = datetime.now().strftime("%Y-%m-%d")
    date_dir = os.path.join(user_dir, date_str)
    if not os.path.exists(date_dir):
        os.makedirs(date_dir)
    
    # CSV文件保存在日期目录下，而不是用户目录下
    csv_path = os.path.join(date_dir, "metadata.csv")
    
    # 检查CSV是否存在，不存在则创建并写入表头
    file_exists = os.path.isfile(csv_path)
    
    try:
        with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['filename', 'datetime', 'file_id', 'file_unique_id', 'media_group_id', 'media_type', 'source', 'source_id', 'source_link', 'source_type']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            writer.writerow({
                'filename': file_name,
                'datetime': datetime.now().isoformat(),
                'file_id': media_obj.file_id,
                'file_unique_id': media_obj.file_unique_id,
                'media_group_id': media_group_id or '',
                'media_type': media_type,
                'source': source or '',
                'source_id': source_id or '',
                'source_link': source_link or '',
                'source_type': source_type or 'unknown'
            })
            logger.debug(f"已将{media_type}元数据保存至CSV: {csv_path}")
    except Exception as e:
        logger.error(f"保存元数据到CSV失败: {e}")

def get_mime_type(document):
    """获取文档的MIME类型
    
    Args:
        document: Telegram文档对象
        
    Returns:
        str: MIME类型
    """
    return document.mime_type 