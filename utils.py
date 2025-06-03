#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import csv
import hashlib
from datetime import datetime
import logging

from config import SAVE_DIR

logger = logging.getLogger(__name__)

def get_save_directory(user):
    """创建并返回保存目录路径
    
    Args:
        user: Telegram用户对象
        
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
    
    return date_dir

def get_short_id(media_group_id):
    """从媒体组ID获取标识符
    
    Args:
        media_group_id: Telegram媒体组ID
        
    Returns:
        str: 用于文件名的标识符
    """
    # 使用完整的媒体组ID，或者对于单张图片使用"single"
    return media_group_id if media_group_id else "single"

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

def save_to_csv(user, photo_obj, file_name, media_group_id=None):
    """将图片元数据保存到CSV文件
    
    Args:
        user: Telegram用户对象
        photo_obj: Telegram照片对象
        file_name: 保存的文件名
        media_group_id: 可选的媒体组ID
    """
    user_dir = os.path.join(SAVE_DIR, f"{user.username or user.first_name}")
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        
    date_str = datetime.now().strftime("%Y-%m-%d")
    csv_path = os.path.join(user_dir, f"{date_str}_metadata.csv")
    
    # 检查CSV是否存在，不存在则创建并写入表头
    file_exists = os.path.isfile(csv_path)
    
    try:
        with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['filename', 'datetime', 'file_id', 'file_unique_id', 'media_group_id']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            writer.writerow({
                'filename': file_name,
                'datetime': datetime.now().isoformat(),
                'file_id': photo_obj.file_id,
                'file_unique_id': photo_obj.file_unique_id,
                'media_group_id': media_group_id or ''
            })
            logger.debug(f"已将图片元数据保存至CSV: {csv_path}")
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