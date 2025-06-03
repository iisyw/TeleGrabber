#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import json
import logging
import warnings
from datetime import datetime

# 忽略不相关的警告
warnings.filterwarnings("ignore", message="python-telegram-bot is using upstream urllib3")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

from telegram import Update, Message
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from telegram.ext import JobQueue

from config import logger, SAVE_DIR
from utils import (
    get_save_directory, generate_filename
)

# 媒体组状态文件
MEDIA_GROUP_STATE_FILE = os.path.join(SAVE_DIR, "media_groups_state.json")
# 媒体组收集状态文件
MEDIA_GROUP_COLLECTION_FILE = os.path.join(SAVE_DIR, "media_groups_collection.json")
# 媒体组收集等待时间（秒）
MEDIA_GROUP_COLLECT_TIME = 2

def start(update: Update, context: CallbackContext) -> None:
    """发送启动消息"""
    user = update.effective_user
    update.message.reply_text(f'你好 {user.first_name}! 我会保存你发送的图片。')

def help_command(update: Update, context: CallbackContext) -> None:
    """发送帮助信息"""
    update.message.reply_text('发送图片给我，我会自动保存它们。')

def load_media_groups_collection():
    """从文件加载媒体组收集状态"""
    try:
        if not os.path.exists(MEDIA_GROUP_COLLECTION_FILE):
            # 创建空文件
            with open(MEDIA_GROUP_COLLECTION_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            return {}
        
        with open(MEDIA_GROUP_COLLECTION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 记录日志，查看加载的数据是否包含状态消息ID
            for key, value in data.items():
                if 'status_message_id' in value:
                    logger.debug(f"加载到的媒体组 {key} 包含状态消息ID: {value['status_message_id']}")
                else:
                    logger.warning(f"加载到的媒体组 {key} 不包含状态消息ID")
            return data
    except Exception as e:
        logger.error(f"加载媒体组收集状态失败: {e}")
        return {}

def save_media_groups_collection(collection):
    """保存媒体组收集状态到文件"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(MEDIA_GROUP_COLLECTION_FILE), exist_ok=True)
        
        with open(MEDIA_GROUP_COLLECTION_FILE, 'w', encoding='utf-8') as f:
            # 只保存可序列化的数据
            serializable_collection = {}
            for key, value in collection.items():
                serializable_collection[key] = {
                    'chat_id': value['chat_id'],
                    'user_id': value['user_id'],
                    'user_name': value['user_name'],
                    'media_group_id': value['media_group_id'],
                    'photos': [{'file_id': p['file_id'], 'file_unique_id': p['file_unique_id']} for p in value['photos']],
                    'first_time': value['first_time'].isoformat() if isinstance(value['first_time'], datetime) else value['first_time'],
                    'status_message_id': value.get('status_message_id')  # 确保保存状态消息ID
                }
            
            json.dump(serializable_collection, f, ensure_ascii=False, indent=2)
            logger.debug(f"已保存媒体组收集状态，包含 {len(serializable_collection)} 个媒体组")
    except Exception as e:
        logger.error(f"保存媒体组收集状态失败: {e}")

def add_photo_to_collection(media_group_id, chat_id, user, photo, context=None, message=None):
    """将照片添加到媒体组收集中"""
    collection = load_media_groups_collection()
    
    # 创建收集键
    collection_key = f"{chat_id}_{media_group_id}"
    
    # 提取必要的照片信息，避免序列化问题
    photo_info = {
        'file_id': photo.file_id,
        'file_unique_id': photo.file_unique_id
    }
    
    # 如果这是该媒体组的第一张照片
    is_first_photo = collection_key not in collection
    if is_first_photo:
        # 发送初始提示消息
        status_message = None
        if context and message:
            status_message = message.reply_text("⏳ 正在收集媒体组图片，请稍候...")
            logger.info(f"为媒体组 {media_group_id} 创建了状态消息，ID: {status_message.message_id}")
        
        # 初始化该媒体组的收集
        status_message_id = status_message.message_id if status_message else None
        collection[collection_key] = {
            'chat_id': chat_id,
            'user_id': user.id,
            'user_name': user.username or user.first_name,
            'media_group_id': media_group_id,
            'photos': [photo_info],
            'first_time': datetime.now().isoformat(),
            'status_message_id': status_message_id
        }
        logger.info(f"开始收集媒体组 {media_group_id} 的照片，状态消息ID: {status_message_id}")
    else:
        # 添加照片到现有收集，但不更新消息
        collection[collection_key]['photos'].append(photo_info)
        
        # 仅记录日志，不更新消息
        photo_count = len(collection[collection_key]['photos'])
        logger.debug(f"媒体组 {media_group_id} 添加了新照片，当前总数: {photo_count}")
    
    # 保存更新后的收集状态
    save_media_groups_collection(collection)
    
    # 返回当前收集到的照片数量和是否是第一张
    return len(collection[collection_key]['photos']), is_first_photo

def schedule_media_group_processing(context, media_group_id, chat_id):
    """安排媒体组处理任务"""
    collection_key = f"{chat_id}_{media_group_id}"
    
    # 设置延迟任务，在收集一段时间后处理
    context.job_queue.run_once(
        process_media_group_photos,
        MEDIA_GROUP_COLLECT_TIME,
        context={'collection_key': collection_key}
    )
    logger.debug(f"已安排媒体组 {media_group_id} 的处理任务")

def process_media_group_photos(context: CallbackContext):
    """处理收集好的媒体组照片"""
    job = context.job
    collection_key = job.context['collection_key']
    
    logger.info(f"开始处理媒体组 {collection_key}")
    
    # 加载媒体组收集状态
    collection = load_media_groups_collection()
    
    if collection_key not in collection:
        logger.error(f"媒体组收集 {collection_key} 不存在")
        return
    
    # 获取媒体组信息
    group_info = collection[collection_key]
    chat_id = group_info['chat_id']
    media_group_id = group_info['media_group_id']
    user_name = group_info['user_name']
    photo_infos = group_info['photos']
    
    # 获取状态消息ID并记录日志
    status_message_id = group_info.get('status_message_id')
    logger.info(f"处理媒体组 {collection_key}，状态消息ID: {status_message_id}")
    
    # 获取照片数量
    total_photos = len(photo_infos)
    
    if total_photos == 0:
        logger.warning(f"媒体组 {media_group_id} 没有照片")
        
        # 如果有状态消息，更新为错误信息
        if status_message_id:
            try:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text="❌ 未能处理任何图片"
                )
            except Exception as e:
                logger.error(f"更新状态消息失败: {e}")
        
        del collection[collection_key]
        save_media_groups_collection(collection)
        return
    
    # 直接使用初始的状态消息
    status_message = None
    if status_message_id:
        try:
            # 直接更新收集阶段的初始消息，显示开始处理
            status_message = context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=f"⏳ 正在保存图片组：0/{total_photos}"
            )
            logger.info(f"成功更新初始消息以开始处理阶段，消息ID: {status_message_id}")
        except Exception as e:
            logger.error(f"更新初始状态消息失败: {e}")
            status_message_id = None
    
    # 只有在确实找不到初始消息ID时才创建新消息（这种情况应该很少发生）
    if not status_message_id:
        logger.warning("找不到有效的初始消息ID，将创建新消息")
        try:
            status_message = context.bot.send_message(
                chat_id=chat_id,
                text=f"⏳ 正在保存图片组：0/{total_photos}"
            )
            # 保存新创建的消息ID以便后续使用
            status_message_id = status_message.message_id
            logger.info(f"已创建新的状态消息，ID: {status_message_id}")
        except Exception as e:
            logger.error(f"创建状态消息失败: {e}")
    
    # 获取用户目录
    user_dir = os.path.join(SAVE_DIR, user_name)
    date_dir = os.path.join(user_dir, datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(date_dir, exist_ok=True)
    
    start_time = time.time()
    processed_count = 0
    
    # 逐个处理照片
    for index, photo_info in enumerate(photo_infos, 1):
        try:
            # 获取照片文件
            file = context.bot.get_file(photo_info['file_id'])
            
            # 生成文件名和路径
            timestamp = int(time.time())
            file_name = f"{timestamp}_{photo_info['file_unique_id']}_{media_group_id}.jpg"
            file_path = os.path.join(date_dir, file_name)
            
            # 下载照片
            file.download(file_path)
            processed_count += 1
            
            # 更新状态消息 - 每张图片都更新一次
            try:
                if status_message_id:
                    context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_message_id,
                        text=f"⏳ 正在保存图片组：{index}/{total_photos}"
                    )
            except Exception as e:
                logger.error(f"更新进度消息失败: {e}")
            
            logger.info(f"已保存媒体组图片 ({index}/{total_photos}): {file_path}")
            
        except Exception as e:
            logger.error(f"保存媒体组照片失败: {e}")
    
    # 清理收集状态
    del collection[collection_key]
    save_media_groups_collection(collection)
    
    # 处理完成，更新状态消息
    elapsed_time = time.time() - start_time
    try:
        if status_message_id:
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=f"✅ 图片组保存完成！({processed_count}/{total_photos}张图片，用时{elapsed_time:.1f}秒)"
            )
    except Exception as e:
        logger.error(f"更新完成消息失败: {e}")
    
    logger.info(f"媒体组 {media_group_id} 处理完成，共 {processed_count}/{total_photos} 张图片")

def process_photo(update: Update, context: CallbackContext) -> None:
    """处理所有照片，包括单张和媒体组中的照片"""
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 检查是否为媒体组的一部分
    media_group_id = message.media_group_id
    
    # 单张图片处理
    if not media_group_id:
        # 获取保存目录
        date_dir = get_save_directory(user)
        
        # 获取图片
        photo = message.photo[-1]
        photo_file = photo.get_file()
        
        # 生成文件名
        file_name = generate_filename(photo)
        file_path = os.path.join(date_dir, file_name)
        
        try:
            # 下载图片
            photo_file.download(file_path)
            logger.info(f"已保存单张图片: {file_path}")
            
            # 发送确认消息
            update.message.reply_text(f"✅ 图片已保存")
        except Exception as e:
            logger.error(f"下载失败: {str(e)}")
            update.message.reply_text(f"❌ 图片保存失败: {str(e)}")
        return
    
    # 媒体组处理
    # 获取照片对象（取最大尺寸的版本）
    photo = message.photo[-1]
    
    # 添加照片到收集
    photo_count, is_first_photo = add_photo_to_collection(media_group_id, chat_id, user, photo, context, message)
    logger.debug(f"媒体组 {media_group_id} 现有 {photo_count} 张照片, 是否第一张: {is_first_photo}")
    
    # 如果这是第一张照片，安排处理任务
    if is_first_photo:
        schedule_media_group_processing(context, media_group_id, chat_id)
        logger.debug(f"已为媒体组 {media_group_id} 安排处理任务")

def download_document(update: Update, context: CallbackContext) -> None:
    """下载用户发送的文件（针对图片文件）"""
    user = update.effective_user
    message = update.message
    document = message.document
    
    # 检查是否为图片文件
    mime_type = document.mime_type
    if not mime_type or not mime_type.startswith('image/'):
        update.message.reply_text("❌ 只支持图片文件")
        return
    
    # 获取保存目录
    date_dir = get_save_directory(user)
    
    # 获取文件
    file = document.get_file()
    
    # 保持原始文件名或生成新的文件名
    original_name = document.file_name
    file_name = original_name if original_name else f"{int(time.time())}_{document.file_id}"
    file_path = os.path.join(date_dir, file_name)
    
    try:
        # 下载文件
        file.download(file_path)
        logger.info(f"已保存文件: {file_path}")
        
        # 回复确认消息
        update.message.reply_text(f"✅ 图片已保存")
    except Exception as e:
        logger.error(f"下载失败: {str(e)}")
        update.message.reply_text(f"❌ 图片保存失败: {str(e)}")

def handle_url_with_image(update: Update, context: CallbackContext) -> None:
    """处理包含图片的URL链接"""
    # 此功能需要额外的库来解析网页和下载图片，这里仅提供提示
    message = update.message
    if message.entities and any(entity.type == 'url' for entity in message.entities):
        update.message.reply_text("检测到链接，但目前不支持从URL下载图片。") 