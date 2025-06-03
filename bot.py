#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import json
import logging
import warnings
from datetime import datetime
import functools
from collections import defaultdict

# 忽略不相关的警告
warnings.filterwarnings("ignore", message="python-telegram-bot is using upstream urllib3")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

from telegram import Update, Message
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from telegram.ext import JobQueue

from config import logger, SAVE_DIR, ALLOWED_USERS, ENABLE_USER_RESTRICTION, GITHUB_REPO
from utils import (
    get_save_directory, generate_filename, save_to_csv, get_short_id,
    generate_temp_filename, get_image_extension, get_video_extension
)

# 媒体组状态文件
MEDIA_GROUP_STATE_FILE = os.path.join(SAVE_DIR, "media_groups_state.json")
# 媒体组收集状态文件
MEDIA_GROUP_COLLECTION_FILE = os.path.join(SAVE_DIR, "media_groups_collection.json")
# 媒体组收集等待时间（秒）
MEDIA_GROUP_COLLECT_TIME = 2

# 存储最近提示过的用户，格式为 {user_id: last_notification_time}
user_notification_cache = defaultdict(int)
# 设置提示冷却时间（秒）
NOTIFICATION_COOLDOWN = 60

def is_user_allowed(update: Update) -> bool:
    """检查用户是否被允许使用机器人"""
    if not ENABLE_USER_RESTRICTION:
        return True
    
    user = update.effective_user
    if not user:
        return False
    
    # 检查用户名和用户ID
    username = user.username
    user_id = str(user.id)
    
    # 检查用户是否在允许列表中
    is_allowed = (username in ALLOWED_USERS) or (user_id in ALLOWED_USERS)
    
    # 记录验证结果
    if not is_allowed:
        logger.warning(f"用户验证失败: {username} (ID: {user_id}) 尝试使用机器人")
    
    return is_allowed

def restricted(func):
    """装饰器函数，仅允许特定用户访问"""
    @functools.wraps(func)
    def wrapped(update, context, *args, **kwargs):
        if not is_user_allowed(update):
            user_id = update.effective_user.id
            current_time = time.time()
            
            # 检查是否在冷却时间内已经提示过
            if current_time - user_notification_cache.get(user_id, 0) > NOTIFICATION_COOLDOWN:
                unauthorized_message = (
                    f"⛔ 访问受限\n\n"
                    f"此机器人是私有实例，仅供特定用户使用。媒体文件将被下载到部署服务器的本地存储中，而不是转发给其他用户。\n\n"
                    f"由于这是一个私人存储工具，只有授权用户才能使用此功能。\n\n" 
                    f"您可以在GitHub上部署自己的TeleGrabber实例：\n"
                    f"{GITHUB_REPO}"
                )
                update.message.reply_text(unauthorized_message)
                
                # 更新最后提示时间
                user_notification_cache[user_id] = current_time
            return
        return func(update, context, *args, **kwargs)
    return wrapped

@restricted
def start(update: Update, context: CallbackContext) -> None:
    """发送启动消息"""
    user = update.effective_user
    welcome_message = (
        f"你好 {user.first_name}！我是 TeleGrabber 机器人。\n\n"
        f"我可以自动保存你发送的图片、视频和 GIF 动画。\n\n"
        f"支持的媒体类型：\n"
        f"✅ 图片 (JPG, PNG, WEBP 等)\n"
        f"✅ 视频 (MP4, AVI, MOV 等)\n"
        f"✅ GIF 动画\n"
        f"✅ 媒体组/相册（包含图片和视频）\n\n"
        f"⚠️ 注意：由于 Telegram Bot API 的限制，我只能下载 20MB 以下的媒体文件。\n\n"
        f"发送 /help 查看更多帮助信息。"
    )
    update.message.reply_text(welcome_message)

@restricted
def help_command(update: Update, context: CallbackContext) -> None:
    """发送帮助信息"""
    help_message = (
        f"💡 TeleGrabber 使用指南:\n\n"
        f"直接发送以下内容给我，我会自动保存：\n"
        f"• 单张图片\n"
        f"• 单个视频\n"
        f"• GIF 动画\n"
        f"• 媒体组（相册）\n"
        f"• 图片文件\n\n"
        
        f"⚠️ 限制说明：\n"
        f"• 每个媒体文件最大 20MB\n"
        f"• 超过大小限制的文件无法保存\n"
        f"• 媒体组中的部分文件若超过限制，其他文件仍会正常保存\n\n"
        
        f"📁 文件保存路径：\n"
        f"• 媒体文件按用户名和日期自动分类存储\n"
        f"• 格式：downloads/用户名/日期/文件名\n\n"
        
        f"🔍 额外信息：\n"
        f"• 所有媒体元数据会保存到CSV文件中\n"
        f"• 支持断网重连和代理设置\n"
        f"• 发送大型媒体组时，会显示实时进度\n"
    )
    update.message.reply_text(help_message)

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
                    'media_items': [{'file_id': p['file_id'], 'file_unique_id': p['file_unique_id'], 'media_type': p.get('media_type', 'photo')} for p in value['media_items']],
                    'first_time': value['first_time'].isoformat() if isinstance(value['first_time'], datetime) else value['first_time'],
                    'status_message_id': value.get('status_message_id')
                }
            
            json.dump(serializable_collection, f, ensure_ascii=False, indent=2)
            logger.debug(f"已保存媒体组收集状态，包含 {len(serializable_collection)} 个媒体组")
    except Exception as e:
        logger.error(f"保存媒体组收集状态失败: {e}")

def add_photo_to_collection(media_group_id, chat_id, user, photo, context=None, message=None):
    """将照片添加到媒体组收集中"""
    # 修改为调用通用函数
    return add_media_to_collection(media_group_id, chat_id, user, photo, "photo", context, message)

def add_video_to_collection(media_group_id, chat_id, user, video, context=None, message=None):
    """将视频添加到媒体组收集中"""
    # 修改为调用通用函数
    return add_media_to_collection(media_group_id, chat_id, user, video, "video", context, message)

def add_media_to_collection(media_group_id, chat_id, user, media_obj, media_type, context=None, message=None):
    """将媒体（照片或视频）添加到媒体组收集中"""
    collection = load_media_groups_collection()
    
    # 创建收集键
    collection_key = f"{chat_id}_{media_group_id}"
    
    # 提取必要的媒体信息，避免序列化问题
    media_info = {
        'file_id': media_obj.file_id,
        'file_unique_id': media_obj.file_unique_id,
        'media_type': media_type  # 添加媒体类型字段
    }
    
    # 如果这是该媒体组的第一个媒体项
    is_first_media = collection_key not in collection
    if is_first_media:
        # 发送初始提示消息
        status_message = None
        if context and message:
            status_message = message.reply_text("⏳ 正在收集媒体组内容，请稍候...")
            logger.info(f"为媒体组 {media_group_id} 创建了状态消息，ID: {status_message.message_id}")
        
        # 初始化该媒体组的收集
        status_message_id = status_message.message_id if status_message else None
        collection[collection_key] = {
            'chat_id': chat_id,
            'user_id': user.id,
            'user_name': user.username or user.first_name,
            'media_group_id': media_group_id,
            'media_items': [media_info],  # 改名以反映可包含不同媒体类型
            'first_time': datetime.now().isoformat(),
            'status_message_id': status_message_id
        }
        logger.info(f"开始收集媒体组 {media_group_id} 的内容，状态消息ID: {status_message_id}")
    else:
        # 添加媒体到现有收集，但不更新消息
        collection[collection_key]['media_items'].append(media_info)
        
        # 仅记录日志，不更新消息
        media_count = len(collection[collection_key]['media_items'])
        logger.debug(f"媒体组 {media_group_id} 添加了新{media_type}，当前总数: {media_count}")
    
    # 保存更新后的收集状态
    save_media_groups_collection(collection)
    
    # 返回当前收集到的媒体数量和是否是第一个
    return len(collection[collection_key]['media_items']), is_first_media

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
    """处理收集好的媒体组内容（包括照片和视频）"""
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
    media_items = group_info['media_items']
    
    # 获取状态消息ID并记录日志
    status_message_id = group_info.get('status_message_id')
    logger.info(f"处理媒体组 {collection_key}，状态消息ID: {status_message_id}")
    
    # 获取媒体数量
    total_items = len(media_items)
    
    if total_items == 0:
        logger.warning(f"媒体组 {media_group_id} 没有内容")
        
        # 如果有状态消息，更新为错误信息
        if status_message_id:
            try:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text="❌ 未能处理任何媒体内容"
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
                text=f"⏳ 正在保存媒体组：0/{total_items}"
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
                text=f"⏳ 正在保存媒体组：0/{total_items}"
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
    
    # 创建一个用户对象以便传递给save_to_csv函数
    user_obj = type('User', (), {'username': user_name, 'first_name': user_name})
    
    # 逐个处理媒体项
    for index, media_info in enumerate(media_items, 1):
        try:
            # 获取媒体文件
            file = context.bot.get_file(media_info['file_id'])
            
            # 生成临时文件名（不带扩展名）
            temp_filename = generate_temp_filename(media_group_id)
            temp_path = os.path.join(date_dir, f"{temp_filename}_temp")
            
            # 下载到临时文件
            file.download(temp_path)
            
            # 根据媒体类型选择不同的扩展名检测函数
            media_type = media_info.get('media_type', 'photo')
            if media_type == 'video':
                ext = get_video_extension(temp_path)
            else:  # 默认为照片
                ext = get_image_extension(temp_path)
                
            final_filename = f"{temp_filename}{ext}"
            final_path = os.path.join(date_dir, final_filename)
            
            # 重命名为正确的扩展名
            os.rename(temp_path, final_path)
            
            processed_count += 1
            
            # 创建媒体对象以便保存元数据
            media_obj = type('Media', (), {
                'file_id': media_info['file_id'],
                'file_unique_id': media_info['file_unique_id'],
                'media_type': media_type
            })
            
            # 保存元数据到CSV
            save_to_csv(user_obj, media_obj, final_filename, media_group_id, media_type)
            
            # 更新状态消息 - 每个媒体项都更新一次
            try:
                if status_message_id:
                    context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_message_id,
                        text=f"⏳ 正在保存媒体组：{index}/{total_items}"
                    )
            except Exception as e:
                logger.error(f"更新进度消息失败: {e}")
            
            logger.info(f"已保存媒体组{media_type} ({index}/{total_items}): {final_path}")
            
        except Exception as e:
            logger.error(f"保存媒体组{media_info.get('media_type', '内容')}失败: {e}")
    
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
                text=f"✅ 媒体组保存完成！({processed_count}/{total_items}个文件，用时{elapsed_time:.1f}秒)"
            )
    except Exception as e:
        logger.error(f"更新完成消息失败: {e}")
    
    logger.info(f"媒体组 {media_group_id} 处理完成，共 {processed_count}/{total_items} 个文件")

@restricted
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
        
        # 生成临时文件名（不带扩展名）
        temp_filename = generate_temp_filename()
        temp_path = os.path.join(date_dir, f"{temp_filename}_temp")
        
        try:
            # 下载到临时文件
            photo_file.download(temp_path)
            
            # 检测实际图片类型并获取扩展名
            ext = get_image_extension(temp_path)
            final_filename = f"{temp_filename}{ext}"
            final_path = os.path.join(date_dir, final_filename)
            
            # 重命名为正确的扩展名
            os.rename(temp_path, final_path)
            
            # 保存元数据到CSV
            save_to_csv(user, photo, final_filename)
            
            logger.info(f"已保存单张图片: {final_path}")
            
            # 发送确认消息
            update.message.reply_text(f"✅ 图片已保存")
        except Exception as e:
            # 清理临时文件
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
                
            logger.error(f"下载失败: {str(e)}")
            update.message.reply_text(f"❌ 图片保存失败: {str(e)}")
        return
    
    # 媒体组处理
    # 获取照片对象（取最大尺寸的版本）
    photo = message.photo[-1]
    
    # 添加照片到收集
    media_count, is_first_media = add_photo_to_collection(media_group_id, chat_id, user, photo, context, message)
    logger.debug(f"媒体组 {media_group_id} 现有 {media_count} 个媒体项, 是否第一个: {is_first_media}")
    
    # 如果这是第一个媒体项，安排处理任务
    if is_first_media:
        schedule_media_group_processing(context, media_group_id, chat_id)
        logger.debug(f"已为媒体组 {media_group_id} 安排处理任务")

@restricted
def process_video(update: Update, context: CallbackContext) -> None:
    """处理所有视频，包括单个和媒体组中的视频"""
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 检查是否为媒体组的一部分
    media_group_id = message.media_group_id
    
    # 单个视频处理
    if not media_group_id:
        # 获取保存目录
        date_dir = get_save_directory(user)
        
        # 获取视频
        video = message.video
        video_file = video.get_file()
        
        # 生成临时文件名（不带扩展名）
        temp_filename = generate_temp_filename()
        temp_path = os.path.join(date_dir, f"{temp_filename}_temp")
        
        try:
            # 下载到临时文件
            video_file.download(temp_path)
            
            # 检测实际视频类型并获取扩展名
            ext = get_video_extension(temp_path)
            final_filename = f"{temp_filename}{ext}"
            final_path = os.path.join(date_dir, final_filename)
            
            # 重命名为正确的扩展名
            os.rename(temp_path, final_path)
            
            # 保存元数据到CSV
            save_to_csv(user, video, final_filename, media_type='video')
            
            logger.info(f"已保存单个视频: {final_path}")
            
            # 发送确认消息
            update.message.reply_text(f"✅ 视频已保存")
        except Exception as e:
            # 清理临时文件
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
                
            logger.error(f"下载失败: {str(e)}")
            update.message.reply_text(f"❌ 视频保存失败: {str(e)}")
        return
    
    # 媒体组处理
    # 获取视频对象
    video = message.video
    
    # 添加视频到收集
    media_count, is_first_media = add_video_to_collection(media_group_id, chat_id, user, video, context, message)
    logger.debug(f"媒体组 {media_group_id} 现有 {media_count} 个媒体项, 是否第一个: {is_first_media}")
    
    # 如果这是第一个媒体项，安排处理任务
    if is_first_media:
        schedule_media_group_processing(context, media_group_id, chat_id)
        logger.debug(f"已为媒体组 {media_group_id} 安排处理任务")

@restricted
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
    
    # 处理文件名
    original_name = document.file_name
    timestamp = int(time.time() * 1000)  # 毫秒级时间戳
    
    # 创建临时文件名用于下载
    temp_filename = f"doc_{timestamp}_temp"
    temp_path = os.path.join(date_dir, temp_filename)
    
    try:
        # 下载到临时文件
        file.download(temp_path)
        
        # 如果有原始文件名，优先使用其扩展名
        if original_name and '.' in original_name:
            ext = os.path.splitext(original_name)[1].lower()
            # 验证扩展名是否与实际格式一致
            detected_ext = get_image_extension(temp_path)
            
            # 如果检测到的扩展名与原始文件名不一致，记录日志
            if ext.lower() != detected_ext.lower():
                logger.warning(f"文件扩展名不匹配: 原始={ext}, 检测={detected_ext}, 使用检测结果")
                ext = detected_ext
        else:
            # 没有原始扩展名，检测实际格式
            ext = get_image_extension(temp_path)
        
        # 生成最终文件名和路径
        final_filename = f"doc_{timestamp}{ext}"
        final_path = os.path.join(date_dir, final_filename)
        
        # 重命名为最终文件名
        os.rename(temp_path, final_path)
        
        # 保存元数据到CSV
        photo_obj = type('Photo', (), {
            'file_id': document.file_id,
            'file_unique_id': document.file_unique_id
        })
        save_to_csv(user, photo_obj, final_filename)
        
        logger.info(f"已保存文件: {final_path}")
        
        # 回复确认消息
        update.message.reply_text(f"✅ 图片已保存")
    except Exception as e:
        # 清理临时文件
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
                
        logger.error(f"下载失败: {str(e)}")
        update.message.reply_text(f"❌ 图片保存失败: {str(e)}")

@restricted
def process_animation(update: Update, context: CallbackContext) -> None:
    """处理GIF动画"""
    message = update.message
    user = update.effective_user
    animation = message.animation
    
    # GIF动画不支持媒体组，所以不需要检查media_group_id
    
    # 获取保存目录
    date_dir = get_save_directory(user)
    
    # 获取动画文件
    animation_file = animation.get_file()
    
    # 生成临时文件名（不带扩展名）
    temp_filename = generate_temp_filename()
    temp_path = os.path.join(date_dir, f"{temp_filename}_temp")
    
    try:
        # 下载到临时文件
        animation_file.download(temp_path)
        
        # GIF通常就是.gif格式，但我们也可以检测一下
        ext = '.gif'  # 默认扩展名
        
        # 如果有mime_type，可以用它来确定扩展名
        mime_type = getattr(animation, 'mime_type', None)
        if mime_type == 'video/mp4':
            ext = '.mp4'  # 有些"GIF"其实是无声MP4
        elif mime_type and '/' in mime_type:
            format_type = mime_type.split('/')[-1]
            if format_type:
                ext = f'.{format_type}'
        
        # 如果文件名中有扩展名，也可以从那里获取
        file_name = getattr(animation, 'file_name', '')
        if file_name and '.' in file_name:
            name_ext = os.path.splitext(file_name)[1].lower()
            if name_ext:
                ext = name_ext
        
        # 生成最终文件名和路径
        final_filename = f"{temp_filename}{ext}"
        final_path = os.path.join(date_dir, final_filename)
        
        # 重命名为最终文件名
        os.rename(temp_path, final_path)
        
        # 保存元数据到CSV
        animation_obj = type('Animation', (), {
            'file_id': animation.file_id,
            'file_unique_id': animation.file_unique_id
        })
        save_to_csv(user, animation_obj, final_filename, media_type='animation')
        
        logger.info(f"已保存GIF动画: {final_path}")
        
        # 发送确认消息
        update.message.reply_text(f"✅ GIF动画已保存")
    except Exception as e:
        # 清理临时文件
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
                
        logger.error(f"下载GIF失败: {str(e)}")
        update.message.reply_text(f"❌ GIF动画保存失败: {str(e)}")

def handle_url_with_image(update: Update, context: CallbackContext) -> None:
    """处理包含图片的URL链接"""
    # 此功能需要额外的库来解析网页和下载图片，这里仅提供提示
    message = update.message
    if message.entities and any(entity.type == 'url' for entity in message.entities):
        update.message.reply_text("检测到链接，但目前不支持从URL下载图片。") 

def main() -> None:
    """启动机器人"""
    # 初始化数据目录
    os.makedirs(SAVE_DIR, exist_ok=True)
    
    # 创建updater和dispatcher
    updater = Updater(token=os.environ.get('TELEGRAM_BOT_TOKEN'))
    dispatcher = updater.dispatcher
    
    # 添加处理器
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    
    # 照片处理器
    dispatcher.add_handler(MessageHandler(Filters.photo, process_photo))
    
    # 视频处理器
    dispatcher.add_handler(MessageHandler(Filters.video, process_video))
    
    # 文档处理器（图片文件）
    dispatcher.add_handler(MessageHandler(Filters.document, download_document))
    
    # 动画处理器
    dispatcher.add_handler(MessageHandler(Filters.animation, process_animation))
    
    # 启动机器人
    updater.start_polling()
    updater.idle()

# 确保在直接运行脚本时执行main函数
if __name__ == "__main__":
    main() 