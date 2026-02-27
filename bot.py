#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import json
import logging
import warnings
from datetime import datetime
import functools
from collections import defaultdict, deque
import re
import threading
from concurrent.futures import ThreadPoolExecutor

# 忽略不相关的警告
warnings.filterwarnings("ignore", message="python-telegram-bot is using upstream urllib3")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

from telegram import Update, Message
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from telegram.ext import JobQueue

from config import (
    logger, SAVE_DIR, ALLOWED_USERS, ENABLE_USER_RESTRICTION, 
    GITHUB_REPO, USER_API_ENABLED
)
from utils import (
    get_save_directory, generate_temp_filename, get_image_extension, 
    get_video_extension, save_to_db, get_duplicate_info, DB_PATH
)
import user_api
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

# 添加全局锁，确保同一时间只处理一个媒体组
media_group_lock = threading.Lock()
# 添加待处理媒体组队列
pending_media_groups = deque()
# 标记是否有正在处理的媒体组
is_processing_media_group = False

# --- 内存缓存优化 ---
# 在内存中存储当前正在收集的媒体组，减少磁盘 I/O
# 格式: {collection_key: group_info_dict}
active_collections = {}
# 并发下载执行器 (推荐 10-20 以匹配集群带宽)
# 下载执行器：限制为 5 个并发，既能保证速度也能避免触发 Telegram 限制或代理过载
download_executor = ThreadPoolExecutor(max_workers=5)
# --- 内存缓存优化结束 ---

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
        f"• 媒体文件按来源自动分类存储（统一媒体库）\n"
        f"• 格式：downloads/来源名称/文件名\n\n"
        
        f"🔍 额外信息：\n"
        f"• 所有媒体元数据会保存到 SQLite 数据库中并记录用户信息\n"
        f"• 自动检测重复资源并跳过，节省磁盘空间\n"
        f"• 支持断网重连和代理设置\n"
        f"• 发送大型媒体组时，会显示实时进度\n"
    )
    update.message.reply_text(help_message)

def load_media_groups_collection():
    """从文件加载媒体组收集状态（仅在启动时调用一次）"""
    global active_collections
    try:
        if not os.path.exists(MEDIA_GROUP_COLLECTION_FILE):
            return {}
        
        with open(MEDIA_GROUP_COLLECTION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 加载到内存缓存
            active_collections = data
            logger.info(f"已从磁盘恢复了 {len(active_collections)} 个媒体组收集状态")
            return data
    except Exception as e:
        logger.error(f"加载媒体组收集状态失败: {e}")
        return {}

def save_media_groups_collection(collection=None):
    """保存媒体组收集状态到文件（异步持久化）"""
    # 允许不传参，默认保存内存中的数据
    if collection is None:
        collection = active_collections
        
    try:
        os.makedirs(os.path.dirname(MEDIA_GROUP_COLLECTION_FILE), exist_ok=True)
        temp_file = f"{MEDIA_GROUP_COLLECTION_FILE}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            serializable_collection = {}
            for key, value in collection.items():
                # 确保数据是可序列化的
                serializable_collection[key] = {
                    'chat_id': value['chat_id'],
                    'user_id': value['user_id'],
                    'user_name': value['user_name'],
                    'media_group_id': value['media_group_id'],
                    'media_items': value['media_items'],
                    'first_time': value['first_time'],
                    'status_message_id': value.get('status_message_id'),
                    'source': value.get('source'),
                    'source_id': value.get('source_id'),
                    'source_link': value.get('source_link'),
                    'source_type': value.get('source_type'),
                    'caption': value.get('caption')
                }
            json.dump(serializable_collection, f, ensure_ascii=False, indent=2)
        
        os.replace(temp_file, MEDIA_GROUP_COLLECTION_FILE)
        logger.debug("已将媒体组状态异步持久化到磁盘")
    except Exception as e:
        logger.error(f"保存媒体组收集状态失败: {e}")

def add_photo_to_collection(media_group_id, chat_id, user, photo, context=None, message=None):
    """将照片添加到媒体组收集中"""
    # 获取转发来源
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = get_forward_source_info(message)
    
    if media_group_id:
        return add_media_to_collection(
            media_group_id, chat_id, user, photo, 'photo', context, message, 
            source, source_id, source_link, source_type,
            chat_type=message.chat.type if message else None,
            orig_chat_id=orig_chat_id,
            orig_msg_id=orig_msg_id
        )

def add_video_to_collection(media_group_id, chat_id, user, video, context=None, message=None):
    """将视频添加到媒体组收集中"""
    # 获取转发来源
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = get_forward_source_info(message)
    
    if media_group_id:
        return add_media_to_collection(
            media_group_id, chat_id, user, video, 'video', context, message, 
            source, source_id, source_link, source_type,
            chat_type=message.chat.type if message else None,
            orig_chat_id=orig_chat_id,
            orig_msg_id=orig_msg_id
        )

def add_media_to_collection(media_group_id, chat_id, user, media_obj, media_type, context=None, message=None, 
                           source=None, source_id=None, source_link=None, source_type=None, 
                           chat_type=None, orig_chat_id=None, orig_msg_id=None):
    """将媒体（照片或视频）添加到媒体组收集中 (优化版：优先操作内存)"""
    with media_group_lock:
        collection_key = f"{chat_id}_{media_group_id}"
        
        media_info = {
            'file_id': media_obj.file_id,
            'file_unique_id': media_obj.file_unique_id,
            'media_type': media_type,
            'message_id': message.message_id if message else None,
            'file_size': getattr(media_obj, 'file_size', 0),
            'orig_chat_id': orig_chat_id,
            'orig_msg_id': orig_msg_id
        }
        
        is_first_media = collection_key not in active_collections
        if is_first_media:
            status_message = None
            if context and message:
                if is_processing_media_group or pending_media_groups:
                    status_message = message.reply_text("⏳ 媒体组已加入队列，请稍候...")
                else:
                    status_message = message.reply_text("⏳ 正在收集媒体组内容，请稍候...")
            
            status_message_id = status_message.message_id if status_message else None
            active_collections[collection_key] = {
                'chat_id': chat_id,
                'user_id': user.id,
                'user_name': user.username or user.first_name,
                'media_group_id': media_group_id,
                'media_items': [media_info],
                'first_time': datetime.now().isoformat(),
                'status_message_id': status_message_id,
                'source': source,
                'source_id': source_id,
                'source_link': source_link,
                'source_type': source_type,
                'chat_type': chat_type or (message.chat.type if message else None),
                'caption': message.caption if message else None
            }
            logger.info(f"开始收集媒体组 {media_group_id}，消息ID: {status_message_id}")
            # 只有第一个消息产生时才写盘，减少 I/O
            save_media_groups_collection()
        else:
            active_collections[collection_key]['media_items'].append(media_info)
            # 如果后续消息有 caption 而之前的没有，则更新（针对媒体组）
            if not active_collections[collection_key].get('caption') and message and message.caption:
                active_collections[collection_key]['caption'] = message.caption
            logger.debug(f"媒体组 {media_group_id} 添加了{media_type}，总数: {len(active_collections[collection_key]['media_items'])}")
        
        return len(active_collections[collection_key]['media_items']), is_first_media

def schedule_media_group_processing(context, media_group_id, chat_id):
    """安排媒体组处理任务"""
    collection_key = f"{chat_id}_{media_group_id}"
    
    # 添加到待处理队列
    with media_group_lock:
        pending_media_groups.append(collection_key)
        logger.debug(f"媒体组 {media_group_id} 已添加到处理队列，当前队列长度: {len(pending_media_groups)}")
    
    # 设置延迟任务，在收集一段时间后处理
    context.job_queue.run_once(
        process_next_media_group,
        MEDIA_GROUP_COLLECT_TIME,
        context={'initial_key': collection_key}
    )
    logger.debug(f"已安排媒体组 {media_group_id} 的处理任务")

def process_next_media_group(context: CallbackContext):
    """处理队列中的下一个媒体组"""
    global is_processing_media_group
    
    with media_group_lock:
        # 检查是否有待处理的媒体组
        if not pending_media_groups:
            is_processing_media_group = False
            logger.debug("没有待处理的媒体组")
            return
            
        # 如果已经有处理中的媒体组，直接返回
        if is_processing_media_group:
            return
            
        # 获取下一个媒体组
        collection_key = pending_media_groups.popleft()
        is_processing_media_group = True
    
    try:
        # 处理媒体组
        process_media_group_photos(context, collection_key)
    except Exception as e:
        logger.error(f"处理媒体组 {collection_key} 出错: {e}")
    finally:
        # 处理完成后，检查是否还有待处理的媒体组
        with media_group_lock:
            is_processing_media_group = False
            if pending_media_groups:
                # 如果还有待处理的媒体组，安排下一个处理任务
                context.job_queue.run_once(
                    process_next_media_group,
                    0.5,  # 短暂延迟，避免连续处理导致的问题
                    context={}
                )

def process_media_group_photos(context: CallbackContext, collection_key=None):
    """处理收集好的媒体组内容（包括照片和视频）"""
    # 如果没有指定collection_key，则从job中获取
    if collection_key is None:
        job = context.job
        collection_key = job.context.get('initial_key')
    
    logger.info(f"开始处理媒体组 {collection_key}")
    
    # 加载媒体组收集状态
    with media_group_lock:
        collection = load_media_groups_collection()
        
        if collection_key not in collection:
            logger.error(f"媒体组收集 {collection_key} 不存在")
            # 记录更多的错误信息以便诊断
            logger.error(f"当前媒体组集合包含以下键: {list(collection.keys())}")
            return
        
        # 获取媒体组信息
        group_info = collection[collection_key]

    chat_id = group_info['chat_id']
    media_group_id = group_info['media_group_id']
    user_name = group_info['user_name']
    media_items = group_info['media_items']
    source = group_info.get('source')  # 获取来源信息
    source_id = group_info.get('source_id')  # 获取来源ID
    source_link = group_info.get('source_link')  # 获取来源链接
    source_type = group_info.get('source_type')  # 获取来源类型
    
def download_with_retry(file_obj, path, retries=3):
    """带重试机制的文件下载"""
    for i in range(retries):
        try:
            file_obj.download(path)
            return True
        except Exception as e:
            if i == retries - 1:
                raise
            wait = (i + 1) * 2
            logger.warning(f"下载失败: {e}，将在 {wait}s 后进行第 {i+2} 次重试...")
            time.sleep(wait)
    return False

def process_media_group_photos(context: CallbackContext, collection_key=None):
    """处理媒体组内容 (并发下载优化版)"""
    if collection_key is None:
        collection_key = context.job.context.get('initial_key')
    
    # 优先从内存获取
    with media_group_lock:
        group_info = active_collections.get(collection_key)
        if not group_info:
            logger.error(f"媒体组收集 {collection_key} 不存在")
            return

    chat_id = group_info['chat_id']
    media_group_id = group_info['media_group_id']
    user_name = group_info['user_name']
    media_items = group_info['media_items']
    status_message_id = group_info.get('status_message_id')
    total_items = len(media_items)
    
    if total_items == 0:
        if status_message_id:
            try: context.bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text="❌ 未能处理任何媒体内容")
            except: pass
        with media_group_lock:
            if collection_key in active_collections:
                del active_collections[collection_key]
                save_media_groups_collection()
        return

    # 更新状态为开始处理
    if status_message_id:
        try:
            context.bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=f"⏳ 正在并发保存媒体组：0/{total_items}")
        except: pass

    # 准备目录
    user_id = group_info.get('user_id')
    user_obj = type('User', (), {'id': user_id, 'username': user_name, 'first_name': user_name})
    source = group_info.get('source')
    source_type = group_info.get('source_type')
    save_dir = get_save_directory(user_obj, source, source_type)
    
    start_time = time.time()
    processed_count = 0
    progress_lock = threading.Lock()
    caption = group_info.get('caption')
    skipped_duplicates = []
    
    # 状态：0-等待中(⏳), 1-成功(✅), 2-重复(♻️), 3-失败(❌), 4-下载中(⬇️)
    items_status = [0] * total_items
    item_progress = [0] * total_items # 记录每个项的下载进度(0-99)
    
    # 预生成基础文件名（时间戳）
    base_timestamp = generate_temp_filename(media_group_id)
    
    # 记录上次 UI 更新时间
    last_ui_update = {"time": 0} 

    def get_progress_bar():
        status_map = {0: "⏳", 1: "✅", 2: "♻️", 3: "❌", 4: "⬇️"}
        res = []
        for i, s in enumerate(items_status):
            if s == 4: # 正在下载，显示百分比
                res.append(f"⬇️{item_progress[i]}%")
            else:
                res.append(status_map.get(s, "❓"))
        return "".join(res)

    def update_ui_async():
        """非阻塞地更新机器人状态消息"""
        curr_time = time.time()
        # 控制更新频率，至少间隔 1.2 秒 (Bot API 有频率限制，不能太快)
        if curr_time - last_ui_update["time"] > 1.2:
            last_ui_update["time"] = curr_time
            def _do_update():
                try:
                    context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_message_id,
                        text=f"正在保存媒体组...\n进度: {get_progress_bar()} ({processed_count}/{total_items})"
                    )
                except: pass
            # 开启新线程更新，绝对不阻塞 User API 的事件循环
            threading.Thread(target=_do_update, daemon=True).start()

    def download_and_save_task(index, media_info):
        nonlocal processed_count
        try:
            file_unique_id = media_info['file_unique_id']
            
            # 下载前检查查重
            dup_info = get_duplicate_info(file_unique_id)
            if dup_info:
                with progress_lock:
                    skipped_duplicates.append({
                        'index': index,
                        'filename': dup_info['filename'],
                        'source': dup_info['source'],
                        'source_link': dup_info.get('source_link')
                    })
                    items_status[index-1] = 2 # 标记为重复
                    processed_count += 1
                    current_count = processed_count
                
                # 更新进度条
                if status_message_id and current_count % 2 == 0: 
                    try:
                        context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=status_message_id,
                            text=f"正在保存媒体组...\n进度: {get_progress_bar()} ({current_count}/{total_items})"
                        )
                    except: pass
                return True

            file_size = media_info.get('file_size', 0)
            
            # 如果启用了 User API 且文件较大 (>20MB) 或者 Bot API 明确提示无法下载
            if USER_API_ENABLED and file_size >= 20 * 1024 * 1024:
                # 使用 User API 下载
                ext = ".mp4" if media_info.get('media_type') == 'video' else ".jpg"
                final_filename = f"{media_group_id}_{index}_{base_timestamp}{ext}"
                final_path = os.path.join(save_dir, final_filename)
                
                logger.info(f"文件较大 ({file_size/1024/1024:.1f}MB)，切换至 User API 下载: {index}")
                
                with progress_lock:
                    items_status[index-1] = 4 # 标记为下载中 (⬇️)
                    item_progress[index-1] = 0 # 初始 0%

                def p_callback(current, total):
                    if total > 0:
                        percent = int(current * 100 / total)
                        # 只有百分比变了才触发 UI 更新
                        if percent != item_progress[index-1]:
                            with progress_lock:
                                item_progress[index-1] = percent
                            update_ui_async()
                    else:
                        update_ui_async()

                # 溯源修复：优先使用原始频道的 ID 和 消息 ID
                orig_chat_id = media_info.get('orig_chat_id')
                orig_msg_id = media_info.get('orig_msg_id')
                
                target_chat_id = orig_chat_id or chat_id
                target_msg_id = orig_msg_id or media_info['message_id']
                
                if not orig_chat_id:
                    # 私聊映射
                    chat_type = group_info.get('chat_type')
                    if chat_type == 'private' or source_type in ["user", "private_user"]:
                        # User API 看到自己发给机器人的消息是存放在跟机器人的对话中的
                        target_chat_id = context.bot.username or context.bot.id

                # 记录最终下载任务
                logger.info(f"媒体项 {index} User API 开始任务")
                u_start = time.time()
                success = user_api.run_download_large_file(
                    target_chat_id, 
                    target_msg_id, 
                    final_path, 
                    progress_callback=p_callback,
                    file_unique_id=media_info['file_unique_id']
                )
                
                # 如果初次尝试失败（通常是原频道无法访问），则回退到当前聊天下载
                if not success and target_chat_id != chat_id:
                    logger.warning(f"媒体项 {index} 溯源下载失败，尝试从本地聊天回退下载...")
                    fallback_chat_id = chat_id
                    chat_type = group_info.get('chat_type')
                    if chat_type == 'private' or source_type in ["user", "private_user"]:
                        fallback_chat_id = context.bot.username or context.bot.id
                    
                    success = user_api.run_download_large_file(
                        fallback_chat_id,
                        media_info['message_id'],
                        final_path,
                        progress_callback=p_callback,
                        file_unique_id=media_info['file_unique_id']
                    )
                u_end = time.time()
                logger.info(f"媒体项 {index} User API 任务结束, 用时: {u_end - u_start:.1f}秒")
                
                if success:
                    # 保存元数据 (User API 下载完后也要存库)
                    media_obj_stub = type('Media', (), {'file_id': media_info['file_id'], 'file_unique_id': media_info['file_unique_id']})
                    save_to_db(user_obj, media_obj_stub, final_filename, 
                                save_dir=save_dir,
                                media_group_id=media_group_id, 
                                media_type=media_info.get('media_type', 'photo'), 
                                caption=caption,
                                source=source, 
                                source_id=group_info.get('source_id'), 
                                source_link=group_info.get('source_link'), 
                                source_type=source_type)
                    
                    with progress_lock:
                        items_status[index-1] = 1
                        processed_count += 1
                    update_ui_async()
                    return True
                else:
                    raise Exception("User API 下载失败")

            file = context.bot.get_file(media_info['file_id'])
            # 使用预生成的 base_timestamp 和 index，保证文件名在本地排序时是有序的
            temp_path = os.path.join(save_dir, f"{base_timestamp}_temp_{index}")
            
            # 使用带重试的下载
            download_with_retry(file, temp_path)
            
            media_type = media_info.get('media_type', 'photo')
            ext = get_video_extension(temp_path) if media_type == 'video' else get_image_extension(temp_path)
            
            # 最终文件名为 媒体组ID_序号_时间戳.后缀 (实现完美垂直聚合)
            final_filename = f"{media_group_id}_{index}_{base_timestamp}{ext}"
            final_path = os.path.join(save_dir, final_filename)
            os.rename(temp_path, final_path)
            
            # 保存元数据
            media_obj_stub = type('Media', (), {'file_id': media_info['file_id'], 'file_unique_id': media_info['file_unique_id']})
            save_to_db(user_obj, media_obj_stub, final_filename, 
                        save_dir=save_dir,
                        media_group_id=media_group_id, 
                        media_type=media_type, 
                        caption=caption,
                        source=source, 
                        source_id=group_info.get('source_id'), 
                        source_link=group_info.get('source_link'), 
                        source_type=source_type)
            
            with progress_lock:
                items_status[index-1] = 1 # 标记为成功
                processed_count += 1
            update_ui_async()
            return True
        except Exception as e:
            logger.error(f"媒体项 {index} 下载失败: {e}")
            with progress_lock:
                items_status[index-1] = 3 # 标记为失败
                processed_count += 1
            return False
    futures = [download_executor.submit(download_and_save_task, i, item) for i, item in enumerate(media_items, 1)]
    results = [f.result() for f in futures]
    
    elapsed_time = time.time() - start_time
    success_count = sum(1 for r in results if r)
    actual_downloaded = success_count - len(skipped_duplicates)
    
    if status_message_id:
        try:
            finish_text = f"✅ 媒体组保存完成！({success_count}/{total_items}个项，用时{elapsed_time:.1f}秒)\n"
            finish_text += f"结果: {get_progress_bar()}\n"
            if skipped_duplicates:
                # 按照媒体在组中的原始顺序排序
                skipped_duplicates.sort(key=lambda x: x['index'])
                finish_text += f"♻️ 跳过了 {len(skipped_duplicates)} 个重复资源:\n"
                for dup in skipped_duplicates: # 移除5条限制，列出全部
                    source_display = dup['source']
                    if dup.get('source_link'):
                        source_display = f"[{dup['source']}]({dup['source_link']})"
                    finish_text += f" - 第{dup['index']}项 -> `{dup['filename']}` (来源: {source_display})\n"
            
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=finish_text,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        except: pass
    
    # 清理内存中的收集状态并同步到磁盘
    with media_group_lock:
        if collection_key in active_collections:
            del active_collections[collection_key]
            save_media_groups_collection()

@restricted
def process_photo(update: Update, context: CallbackContext) -> None:
    """处理所有照片，包括单张和媒体组中的照片"""
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 获取转发来源
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = get_forward_source_info(message)
    
    # 检查是否为媒体组的一部分
    media_group_id = message.media_group_id
    
    # 单张图片处理
    if not media_group_id:
        # 获取保存目录
        date_dir = get_save_directory(user, source, source_type)
        
        # 获取图片
        photo = message.photo[-1]
        
        # 检查是否重复
        dup_info = get_duplicate_info(photo.file_unique_id)
        if dup_info:
            current_caption = message.caption or "无"
            source_display = dup_info['source']
            if dup_info.get('source_link'):
                source_display = f"[{dup_info['source']}]({dup_info['source_link']})"
                
            reply_msg = (
                f"♻️ **检测到重复资源 (单张图片)**\n\n"
                f"文件已存在: `{dup_info['filename']}`\n"
                f"最初来源: {source_display}\n"
                f"最初描述: {dup_info['caption'] or '无'}\n"
                f"当前描述: {current_caption}"
            )
            update.message.reply_text(reply_msg, parse_mode='Markdown', disable_web_page_preview=True)
            return

        # 检查文件大小 (照片通常不会超过20MB，但为了统一逻辑加上)
        file_size = photo.file_size or 0
        if USER_API_ENABLED and file_size >= 20 * 1024 * 1024:
            update.message.reply_text(f"⏳ 检测到大图片 ({file_size/1024/1024:.1f}MB)，正在通过 User API 下载...")
            temp_filename = generate_temp_filename()
            ext = ".jpg"
            final_filename = f"{temp_filename}{ext}"
            final_path = os.path.join(date_dir, final_filename)
            
            # 溯源修复：优先使用原始频道的 ID 和 消息 ID
            target_chat_id = orig_chat_id or update.effective_chat.id
            target_msg_id = orig_msg_id or update.message.message_id
            
            success = user_api.run_download_large_file(
                target_chat_id,
                target_msg_id,
                final_path,
                file_unique_id=photo.file_unique_id
            )
            
            # 如果初次尝试失败（通常是原频道无法访问），则回退到当前聊天下载
            if not success and target_chat_id != update.effective_chat.id:
                logger.warning(f"单张图片溯源下载失败，尝试从本地聊天回退下载...")
                fallback_chat_id = update.effective_chat.id
                if update.effective_chat.type == 'private' or source_type in ["user", "private_user"]:
                    fallback_chat_id = context.bot.username or context.bot.id
                
                success = user_api.run_download_large_file(
                    fallback_chat_id,
                    update.message.message_id,
                    final_path,
                    file_unique_id=photo.file_unique_id
                )
            
            if success:
                save_to_db(user, photo, final_filename, 
                            save_dir=date_dir,
                            media_type='photo', 
                            caption=message.caption,
                            source=source, 
                            source_id=source_id, 
                            source_link=source_link, 
                            source_type=source_type)
                update.message.reply_text(f"✅ 大图片保存完成: `{final_filename}`", parse_mode='Markdown')
                return
            else:
                update.message.reply_text("❌ 大图片通过 User API 下载失败")
                return
                
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
            
            # 保存元数据到数据库
            save_to_db(user, photo, final_filename, save_dir=date_dir, caption=message.caption, source=source, source_id=source_id, source_link=source_link, source_type=source_type)
            
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
    
    # 获取转发来源
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = get_forward_source_info(message)
    
    # 检查是否为媒体组的一部分
    media_group_id = message.media_group_id
    
    # 单个视频处理
    if not media_group_id:
        # 获取保存目录
        date_dir = get_save_directory(user, source, source_type)
        
        # 获取视频
        video = message.video
        
        # 检查是否重复
        dup_info = get_duplicate_info(video.file_unique_id)
        if dup_info:
            current_caption = message.caption or "无"
            source_display = dup_info['source']
            if dup_info.get('source_link'):
                source_display = f"[{dup_info['source']}]({dup_info['source_link']})"

            reply_msg = (
                f"♻️ **检测到重复资源 (单个视频)**\n\n"
                f"文件已存在: `{dup_info['filename']}`\n"
                f"最初来源: {source_display}\n"
                f"最初描述: {dup_info['caption'] or '无'}\n"
                f"当前描述: {current_caption}"
            )
            update.message.reply_text(reply_msg, parse_mode='Markdown', disable_web_page_preview=True)
            return

        # 检查文件大小
        file_size = video.file_size or 0
        if USER_API_ENABLED and file_size >= 20 * 1024 * 1024:
            # 使用 User API 下载
            update.message.reply_text(f"⏳ 检测到大视频 ({file_size/1024/1024:.1f}MB)，正在通过 User API 下载...")
            
            temp_filename = generate_temp_filename()
            ext = ".mp4"
            final_filename = f"{temp_filename}{ext}"
            final_path = os.path.join(date_dir, final_filename)
            
            # 溯源修复：优先使用原始频道的 ID 和 消息 ID
            target_chat_id = orig_chat_id or update.effective_chat.id
            target_msg_id = orig_msg_id or update.message.message_id
            
            if not orig_chat_id:
                # 私聊映射
                if update.effective_chat.type == 'private' or source_type in ["user", "private_user"]:
                    target_chat_id = context.bot.username or context.bot.id

            success = user_api.run_download_large_file(
                target_chat_id,
                target_msg_id,
                final_path,
                file_unique_id=video.file_unique_id
            )
            
            # 如果初次尝试失败（通常是原频道无法访问），则回退到当前聊天下载
            if not success and target_chat_id != update.effective_chat.id:
                logger.warning(f"单个视频溯源下载失败，尝试从本地聊天回退下载...")
                fallback_chat_id = update.effective_chat.id
                if update.effective_chat.type == 'private' or source_type in ["user", "private_user"]:
                    fallback_chat_id = context.bot.username or context.bot.id
                
                success = user_api.run_download_large_file(
                    fallback_chat_id,
                    update.message.message_id,
                    final_path,
                    file_unique_id=video.file_unique_id
                )
            
            if success:
                save_to_db(user, video, final_filename, 
                            save_dir=date_dir,
                            media_type='video', 
                            caption=message.caption,
                            source=source, 
                            source_id=source_id, 
                            source_link=source_link, 
                            source_type=source_type)
                update.message.reply_text(f"✅ 大视频保存完成: `{final_filename}`", parse_mode='Markdown')
                return
            else:
                update.message.reply_text("❌ 大视频通过 User API 下载失败")
                return

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
            
            # 保存元数据到数据库
            save_to_db(user, video, final_filename, save_dir=date_dir, media_type='video', caption=message.caption, source=source, source_id=source_id, source_link=source_link, source_type=source_type)
            
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
    
    # 获取转发来源
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = get_forward_source_info(message)
    
    # 检查是否为图片文件
    mime_type = document.mime_type
    if not mime_type or not mime_type.startswith('image/'):
        update.message.reply_text("❌ 只支持图片文件")
        return
    
    # 获取保存目录
    date_dir = get_save_directory(user, source, source_type)
    
    # 获取单文件标识符关键字
    temp_filename_key = generate_temp_filename()
    
    # 检查是否重复
    dup_info = get_duplicate_info(document.file_unique_id)
    if dup_info:
        current_caption = message.caption or "无"
        source_display = dup_info['source']
        if dup_info.get('source_link'):
            source_display = f"[{dup_info['source']}]({dup_info['source_link']})"

        reply_msg = (
            f"♻️ **检测到重复资源 (图片文件)**\n\n"
            f"文件已存在: `{dup_info['filename']}`\n"
            f"最初来源: {source_display}\n"
            f"最初描述: {dup_info['caption'] or '无'}\n"
            f"当前描述: {current_caption}"
        )
        update.message.reply_text(reply_msg, parse_mode='Markdown', disable_web_page_preview=True)
        return
    
    # 检查文件大小，支持大图片文件 (>20MB) 通过 User API 下载
    file_size = document.file_size or 0
    if USER_API_ENABLED and file_size >= 20 * 1024 * 1024:
        update.message.reply_text(f"⏳ 检测到大图片文件 ({file_size/1024/1024:.1f}MB)，正在通过 User API 下载...")
        temp_filename = generate_temp_filename()
        # 获取原始扩展名作为备选
        ext = ".jpg"
        if document.file_name and '.' in document.file_name:
            ext = os.path.splitext(document.file_name)[1].lower()
            
        final_filename = f"{temp_filename}{ext}"
        final_path = os.path.join(date_dir, final_filename)
        
        # 溯源修复：优先使用原始频道的 ID 和 消息 ID
        target_chat_id = orig_chat_id or update.effective_chat.id
        target_msg_id = orig_msg_id or update.message.message_id
        
        success = user_api.run_download_large_file(
            target_chat_id,
            target_msg_id,
            final_path,
            file_unique_id=document.file_unique_id
        )
        
        # 如果初次尝试失败（通常是原频道无法访问），则回退到当前聊天下载
        if not success and target_chat_id != update.effective_chat.id:
            logger.warning(f"大图片文件溯源下载失败，尝试从本地聊天回退下载...")
            fallback_chat_id = update.effective_chat.id
            if update.effective_chat.type == 'private' or source_type in ["user", "private_user"]:
                fallback_chat_id = context.bot.username or context.bot.id
            
            success = user_api.run_download_large_file(
                fallback_chat_id,
                update.message.message_id,
                final_path,
                file_unique_id=document.file_unique_id
            )
        
        if success:
            save_to_db(user, document, final_filename, save_dir=date_dir, caption=message.caption, source=source, source_id=source_id, source_link=source_link, source_type=source_type)
            update.message.reply_text(f"✅ 大图片文件已保存: `{final_filename}`", parse_mode='Markdown')
            return
        else:
            update.message.reply_text(f"❌ 大图片文件通过 User API 下载失败")
            return

    # 小文件由 Bot API 处理
    file = document.get_file()
    temp_path = os.path.join(date_dir, f"{temp_filename_key}_temp")
    
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
        
        # 生成最终文件名和路径 (统一使用 single_ 前缀)
        final_filename = f"{temp_filename_key}{ext}"
        final_path = os.path.join(date_dir, final_filename)
        
        # 重命名为最终文件名
        os.rename(temp_path, final_path)
        
        # 保存元数据到数据库
        photo_obj = type('Photo', (), {
            'file_id': document.file_id,
            'file_unique_id': document.file_unique_id
        })
        save_to_db(user, photo_obj, final_filename, save_dir=date_dir, caption=message.caption, source=source, source_id=source_id, source_link=source_link, source_type=source_type)
        
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
    
    # 获取转发来源
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = get_forward_source_info(message)
    
    # GIF动画不支持媒体组，所以不需要检查media_group_id
    
    # 获取保存目录
    date_dir = get_save_directory(user, source, source_type)
    
    # 获取动画文件
    file_size = animation.file_size or 0
    if USER_API_ENABLED and file_size >= 20 * 1024 * 1024:
        update.message.reply_text(f"⏳ 检测到大动画 ({file_size/1024/1024:.1f}MB)，正在通过 User API 下载...")
        temp_filename = generate_temp_filename()
        ext = ".mp4" if animation.mime_type == 'video/mp4' else ".gif"
        final_filename = f"{temp_filename}{ext}"
        final_path = os.path.join(date_dir, final_filename)
        
        # 溯源修复
        target_chat_id = orig_chat_id or update.effective_chat.id
        target_msg_id = orig_msg_id or update.message.message_id
        
        if not orig_chat_id:
            # 私聊映射
            if update.effective_chat.type == 'private' or source_type in ["user", "private_user"]:
                target_chat_id = context.bot.username or context.bot.id

        success = user_api.run_download_large_file(
            target_chat_id,
            target_msg_id,
            final_path,
            file_unique_id=animation.file_unique_id
        )
        
        # 如果初次尝试失败（通常是原频道无法访问），则回退到当前聊天下载
        if not success and target_chat_id != update.effective_chat.id:
            logger.warning(f"动画溯源下载失败，尝试从本地聊天回退下载...")
            fallback_chat_id = update.effective_chat.id
            if update.effective_chat.type == 'private' or source_type in ["user", "private_user"]:
                fallback_chat_id = context.bot.username or context.bot.id
            
            success = user_api.run_download_large_file(
                fallback_chat_id,
                update.message.message_id,
                final_path,
                file_unique_id=animation.file_unique_id
            )
        
        if success:
            # 记录元数据
            animation_obj = type('Animation', (), {
                'file_id': animation.file_id,
                'file_unique_id': animation.file_unique_id
            })
            save_to_db(user, animation_obj, final_filename, 
                        save_dir=date_dir,
                        media_type='animation', 
                        caption=message.caption,
                        source=source, 
                        source_id=source_id, 
                        source_link=source_link, 
                        source_type=source_type)
            update.message.reply_text(f"✅ 大动画保存完成: `{final_filename}`", parse_mode='Markdown')
            return
        else:
            update.message.reply_text("❌ 大动画通过 User API 下载失败")
            return

    animation_file = animation.get_file()
    
    # 检查是否重复
    dup_info = get_duplicate_info(animation.file_unique_id)
    if dup_info:
        current_caption = message.caption or "无"
        source_display = dup_info['source']
        if dup_info.get('source_link'):
            source_display = f"[{dup_info['source']}]({dup_info['source_link']})"

        reply_msg = (
            f"♻️ **检测到重复资源 (GIF动画)**\n\n"
            f"文件已存在: `{dup_info['filename']}`\n"
            f"最初来源: {source_display}\n"
            f"最初描述: {dup_info['caption'] or '无'}\n"
            f"当前描述: {current_caption}"
        )
        update.message.reply_text(reply_msg, parse_mode='Markdown', disable_web_page_preview=True)
        return
    
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
        
        # 保存元数据到数据库
        animation_obj = type('Animation', (), {
            'file_id': animation.file_id,
            'file_unique_id': animation.file_unique_id
        })
        save_to_db(user, animation_obj, final_filename, save_dir=date_dir, media_type='animation', caption=message.caption, source=source, source_id=source_id, source_link=source_link, source_type=source_type)
        
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

def get_forward_source_info(message):
    """获取转发来源的详细信息
    
    Args:
        message: Telegram消息对象
        
    Returns:
        tuple: (source, source_id, source_link, source_type, orig_chat_id, orig_msg_id)
    """
    source = None
    source_id = None
    source_link = None
    source_type = "unknown"
    orig_chat_id = None
    orig_msg_id = None
    
    if message.forward_from_chat:
        # 如果是从频道或群组转发
        chat = message.forward_from_chat
        source = chat.title or f"chat_{chat.id}"
        source_id = str(chat.id)
        orig_chat_id = chat.id
        orig_msg_id = getattr(message, 'forward_from_message_id', None)
        
        # 确定来源类型
        if chat.type == "channel":
            source_type = "channel"
        elif chat.type == "supergroup" or chat.type == "group":
            source_type = "group"
        
        # 创建链接
        if chat.username:
            source_link = f"https://t.me/{chat.username}"
        else:
            source_link = f"https://t.me/c/{str(chat.id).replace('-100', '')}"
            
    elif message.forward_from:
        # 如果是从个人用户转发（用户隐私设置允许的情况下）
        user_from = message.forward_from
        source_id = str(user_from.id)
        orig_chat_id = user_from.id
        # 个人转发通常没有原始消息ID，除非是某些特殊的Bot转发逻辑
        orig_msg_id = getattr(message, 'forward_from_message_id', None)
        
        is_bot = getattr(user_from, 'is_bot', False)
        if is_bot:
            source_type = "bot"
            source = user_from.first_name or f"bot_{user_from.id}"
        else:
            source_type = "user"
            source = user_from.username or user_from.first_name or f"user_{user_from.id}"
            
        if user_from.username:
            source_link = f"https://t.me/{user_from.username}"
    
    elif hasattr(message, 'forward_sender_name') and message.forward_sender_name:
        source = message.forward_sender_name
        source_id = "unknown"
        source_link = ""
        source_type = "private_user"
    
    elif hasattr(message, 'forward_from_message_id') and message.forward_from_message_id:
        source = "forwarded_message"
        source_id = str(message.forward_from_message_id)
        source_link = ""
        source_type = "unknown_forward"
        orig_msg_id = message.forward_from_message_id

    if source:
        source = re.sub(r'[\\/*?:"<>|]', "_", source)
    
    return source, source_id, source_link, source_type, orig_chat_id, orig_msg_id

def main() -> None:
    """启动机器人"""
    # 确保保存目录存在
    os.makedirs(SAVE_DIR, exist_ok=True)
    
    # 创建 Updater 和传递 bot 令牌
    updater = None
    try:
        from config import TELEGRAM_BOT_TOKEN, PROXY_URL
        
        logger.info("启动机器人...")
        
        if PROXY_URL:
            logger.info(f"使用代理: {PROXY_URL}")
            request_kwargs = {'proxy_url': PROXY_URL}
            updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True, request_kwargs=request_kwargs)
        else:
            updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
            
        # 加载初始收集状态
        load_media_groups_collection()
        
        # 获取调度程序
        dispatcher = updater.dispatcher
        
        # 设置命令处理器
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(CommandHandler("help", help_command))
        
        # 设置媒体处理器
        dispatcher.add_handler(MessageHandler(Filters.photo, process_photo))
        dispatcher.add_handler(MessageHandler(Filters.video, process_video))
        dispatcher.add_handler(MessageHandler(Filters.document, download_document))
        dispatcher.add_handler(MessageHandler(Filters.animation, process_animation))
        
        # 显示重试次数
        max_retries = 5
        retry_count = 0
        connected = False
        
        while retry_count < max_retries and not connected:
            try:
                retry_count += 1
                logger.info(f"尝试连接Telegram API (尝试 {retry_count}/{max_retries})...")
                
                # 开始轮询
                updater.start_polling()
                connected = True
                logger.info("机器人已启动，正在监听消息...")
                
                # 运行直到按Ctrl-C
                updater.idle()
            except Exception as e:
                if retry_count < max_retries:
                    wait_time = retry_count * 5  # 递增等待时间
                    logger.error(f"连接失败: {e}. 将在 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.critical(f"达到最大重试次数，无法启动机器人: {e}")
                    raise
    except Exception as e:
        logger.critical(f"机器人启动失败: {e}")
        raise
    finally:
        # 无论如何都要清理资源
        if updater is not None:
            try:
                updater.stop()
                logger.info("机器人已停止")
            except:
                pass
        
        # 清理临时文件
        try:
            temp_files = [f for f in os.listdir(SAVE_DIR) if f.endswith('_temp')]
            for temp_file in temp_files:
                try:
                    os.remove(os.path.join(SAVE_DIR, temp_file))
                except:
                    pass
            logger.info(f"清理了 {len(temp_files)} 个临时文件")
        except:
            pass

# 确保在直接运行脚本时执行main函数
if __name__ == "__main__":
    main() 