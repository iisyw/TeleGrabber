#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
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

def generate_filename(photo_obj, media_group_id=None):
    """根据图片对象生成唯一文件名
    
    Args:
        photo_obj: Telegram照片对象
        media_group_id: 可选的媒体组ID
        
    Returns:
        str: 生成的文件名
    """
    timestamp = int(time.time())
    if media_group_id:
        return f"{timestamp}_{photo_obj.file_id}_{media_group_id}.jpg"
    return f"{timestamp}_{photo_obj.file_id}.jpg"

def get_mime_type(document):
    """获取文档的MIME类型
    
    Args:
        document: Telegram文档对象
        
    Returns:
        str: MIME类型
    """
    return document.mime_type 