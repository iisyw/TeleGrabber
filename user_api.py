#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pyrogram import Client, utils
from pyrogram.errors import ChannelInvalid, ChannelPrivate, MsgIdInvalid, PeerIdInvalid, ChatWriteForbidden
from config import API_ID, API_HASH, PROXY, logger, SAVE_DIR, DOWNLOAD_RETRIES, DATA_DIR
import os
import asyncio
import time
import threading
import mimetypes
import re
from urllib.parse import urlparse
from datetime import timezone

# --- 全局状态 ---
_app = None
_loop = None
_loop_thread = None
_init_lock = threading.Lock()
_start_lock = None  
_semaphore = None 
_restarting = False # 状态位，防止重入

def _run_loop(loop):
    asyncio.set_event_loop(loop)
    logger.info("User API 后台事件循环线程启动")
    loop.run_forever()

def _get_proxy_dict():
    if not PROXY:
        return None
    try:
        parsed = urlparse(PROXY)
        # Pyrogram 内部使用 PySocks，对于 socks5h 我们映射到 socks5，
        # 并通过传递 hostname 让其在远程（代理端）进行 DNS 解析。
        scheme = parsed.scheme
        if scheme == "socks5h":
            scheme = "socks5"
        elif scheme == "socks4a":
            scheme = "socks4"
            
        return {
            "scheme": scheme,
            "hostname": parsed.hostname,
            "port": parsed.port
        }
    except Exception as e:
        logger.error(f"解析代理失败: {e}")
        return None

async def _init_client_task():
    """在 loop 中初始化并启动客户端"""
    global _app, _start_lock, _semaphore
    if _app is None:
        _start_lock = asyncio.Lock()
        _semaphore = asyncio.Semaphore(1) # 强制 User API 顺序下载，这是 MTProto 单会话的最稳模式
        
        _app = Client(
            "telegrabber_user",
            api_id=API_ID,
            api_hash=API_HASH,
            proxy=_get_proxy_dict(),
            workdir=DATA_DIR,
            workers=10,  # 降低工作线程数，提高 MTProto 会话稳定性
            sleep_threshold=60
        )
        logger.info("User API 客户端实例初始化完成")
    
    async with _start_lock:
        if not _app.is_connected:
            logger.info("User API 正在启动长期会话...")
            await _app.start()
            logger.info("User API 会话已就绪")
    return _app

def get_pyrogram_client():
    """线程安全地获取客户端"""
    global _app, _loop, _loop_thread
    if _app is None:
        with _init_lock:
            if _app is None:
                if _loop is None:
                    _loop = asyncio.new_event_loop()
                    _loop_thread = threading.Thread(target=_run_loop, args=(_loop,), daemon=True)
                    _loop_thread.start()
                    time.sleep(0.3)
                
                future = asyncio.run_coroutine_threadsafe(_init_client_task(), _loop)
                _app = future.result(timeout=180)  # 首次登录可能较慢，但避免永久阻塞
    return _app

async def _reset_client():
    """在 asyncio 循环中重置客户端"""
    global _app, _start_lock, _restarting
    if _restarting: return
    _restarting = True
    try:
        if _app:
            logger.warning("检测到连接状态异常，正在强制重置 User API 客户端...")
            try:
                await _app.stop()
            except: pass
            _app = None
            # 重新初始化逻辑
            await _init_client_task()
            logger.info("User API 客户端已完成重置并重新连接")
    finally:
        _restarting = False

def _normalize_chat_ref(chat_ref):
    chat_ref = str(chat_ref).strip()
    if not chat_ref:
        return None
    if chat_ref.startswith('@'):
        return chat_ref[1:]
    try:
        chat_id = int(chat_ref)
        if chat_id > 0:
            return utils.get_channel_id(chat_id)
        return chat_id
    except ValueError:
        return chat_ref


def parse_message_link(link):
    """解析 Telegram 消息链接，返回 (chat_id, message_id)。"""
    try:
        parsed = urlparse(link.strip())
        host = (parsed.netloc or '').lower()
        if host.startswith('www.'):
            host = host[4:]
        if host not in ('t.me', 'telegram.me', 'telegram.dog'):
            return None

        parts = [part for part in parsed.path.split('/') if part]
        if len(parts) == 2 and parts[0] != 'c':
            return parts[0], int(parts[1])
        if len(parts) == 3 and parts[0] == 'c':
            return utils.get_channel_id(int(parts[1])), int(parts[2])
        if len(parts) == 3 and parts[0] != 'c':
            return parts[0], int(parts[2])
        if len(parts) == 4 and parts[0] == 'c':
            return utils.get_channel_id(int(parts[1])), int(parts[3])
    except (TypeError, ValueError):
        return None
    return None


def parse_message_ref(args):
    """解析 /link 参数，支持完整链接或 chat_id/username + message_id。"""
    if not args:
        return None
    if len(args) == 1:
        return parse_message_link(args[0])
    try:
        chat_id = _normalize_chat_ref(args[0])
        message_id = int(args[1])
        if chat_id is None or message_id <= 0:
            return None
        return chat_id, message_id
    except (TypeError, ValueError):
        return None


def _enum_value(value, default='unknown'):
    if value is None:
        return default
    raw = getattr(value, 'value', value)
    return str(raw).lower()


def _is_media_document(document):
    """判断 document 是否为视频/图片源文件（用于决定是否优先选它）。"""
    if document is None:
        return False
    doc_mime = getattr(document, 'mime_type', '') or ''
    doc_name = getattr(document, 'file_name', '') or ''
    doc_ext = os.path.splitext(doc_name)[1].lower()
    return (
        doc_mime.startswith('video/') or doc_mime.startswith('image/')
        or doc_ext in ('.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v',
                       '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.heic')
    )


def _message_media_info(message):
    if not message or not message.media:
        return None
    media_type = message.media.value
    media_obj = getattr(message, media_type, None)
    if not media_obj:
        return None

    # 同一条消息可能同时带压缩版 (video) 和原始源文件 (document)。
    # 仅当 document 本身是视频/图片源文件时才优先选它（无损、体积大），
    # 否则维持原媒体类型，避免把音频/压缩包等非媒体 document 误当成媒体下载。
    is_source_file = False
    document = getattr(message, 'document', None)
    if media_type != 'document' and _is_media_document(document):
        media_obj = document
        media_type = 'document'
        is_source_file = True

    file_name = getattr(media_obj, 'file_name', None) or ''
    ext = os.path.splitext(file_name)[1].lower() if file_name else ''
    mime_type = getattr(media_obj, 'mime_type', None)
    if not ext and mime_type:
        ext = mimetypes.guess_extension(mime_type) or ''
    if not ext:
        defaults = {
            'photo': '.jpg',
            'video': '.mp4',
            'animation': '.gif',
            'document': '.bin',
            'audio': '.mp3',
            'voice': '.ogg',
            'video_note': '.mp4',
            'sticker': '.webp',
        }
        # document 源文件优先按 mime 猜，再退回到通用默认
        if media_type == 'document' and mime_type and mime_type.startswith('video/'):
            ext = '.mp4'
        else:
            ext = defaults.get(media_type, '.bin')

    chat = message.chat
    source_name = getattr(chat, 'title', None) or getattr(chat, 'username', None) or getattr(chat, 'first_name', None) or str(getattr(chat, 'id', 'unknown'))
    source_name = re.sub(r'[\\/*?:"<>|]', "_", source_name)
    source_username = getattr(chat, 'username', None) or ''
    source_link1 = getattr(message, 'link', None)
    if not source_link1 and source_username:
        source_link1 = f"https://t.me/{source_username}/{message.id}"
    if getattr(chat, 'id', None):
        source_link2 = f"https://t.me/c/{chat.id}/{message.id}"
    else:
        source_link2 = ''

    # 若 document 实际是视频源文件，归类为 video 以便 Web 端正确展示，
    # 但仍下载原始 document 对象（is_source_file 标记真实大小来源）。
    stored_media_type = media_type
    if media_type == 'document' and mime_type:
        if mime_type.startswith('video/'):
            stored_media_type = 'video'
        elif mime_type.startswith('image/'):
            stored_media_type = 'photo'

    # 获取原始消息时间（转发消息使用原消息时间），转为本地时间
    msg_date = message.forward_date or message.date
    if msg_date:
        msg_date = msg_date.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)

    return {
        'message': message,
        'media_type': stored_media_type,
        'file_id': getattr(media_obj, 'file_id', None) or f"user_api:{getattr(chat, 'id', 'unknown')}:{message.id}",
        'file_unique_id': getattr(media_obj, 'file_unique_id', None) or f"user_api:{getattr(chat, 'id', 'unknown')}:{message.id}",
        'file_size': getattr(media_obj, 'file_size', 0) or 0,
        'is_source_file': is_source_file,
        'caption': message.caption or '',
        'ext': ext,
        'source_name': source_name,
        'source_username': source_username,
        'source_id': str(getattr(chat, 'id', '')),
        'source_link1': source_link1,
        'source_link2': source_link2,
        'source_type': _enum_value(getattr(chat, 'type', None)),
        'media_group_id': str(getattr(message, 'media_group_id', '') or ''),
        'message_id': message.id,
        'message_date': msg_date.isoformat() if msg_date else None,
    }


async def _get_message_media_info(chat_id, message_id):
    client = get_pyrogram_client()
    message = await client.get_messages(chat_id, message_id)
    return _message_media_info(message)


async def _get_link_media_items(chat_id, message_id):
    client = get_pyrogram_client()
    message = await client.get_messages(chat_id, message_id)
    if not message or not message.media:
        return []

    messages = [message]
    if getattr(message, 'media_group_id', None):
        try:
            messages = await message.get_media_group()
        except Exception as e:
            logger.warning(f"获取链接媒体组失败，回退为单条消息: {e}")
            messages = [message]

    items = []
    for item_message in sorted(messages, key=lambda m: m.id):
        info = _message_media_info(item_message)
        if info:
            items.append(info)
    return items


async def _download_message_media(chat_id, message_id, final_path, progress_callback=None):
    async with _semaphore:
        client = get_pyrogram_client()
        message = await client.get_messages(chat_id, message_id)
        if not message or not message.media:
            return None
        # 优先下载原始 document 源文件（与 _message_media_info 选择保持一致）：
        # 仅当 document 是视频/图片源文件时才用它，否则下载消息本身的主媒体。
        document = getattr(message, 'document', None)
        target = document if _is_media_document(document) else message
        return await client.download_media(target, file_name=final_path, progress=progress_callback)


async def _do_download(chat_id, message_id, final_path, progress_callback=None, file_unique_id=None):
    # 使用信号量强制排队，匹配用户观察到的物理串行特性，UI 表现也最整齐
    # 将信号量范围扩大到包含重试过程，确保恢复过程中 Slot 不会被抢占
    async with _semaphore:
        attempts = 0
        max_attempts = max(1, DOWNLOAD_RETRIES + 1) # 总尝试次数 = 重试次数 + 1
        
        while attempts < max_attempts:
            attempts += 1
            client = get_pyrogram_client()
            try:
                if attempts > 1:
                    logger.info(f"正在进行第 {attempts-1} 次重试: {final_path}")
                else:
                    logger.info(f"User API 占用执行槽位: {final_path}")
                
                # 为了确保下载文件的完整性，每次重试下载前都先删除可能存在的残留文件
                # 同时清理 Pyrogram 可能遗留的 .temp 或 .part 临时文件，彻底防止错误续传
                for p in [final_path, final_path + ".temp", final_path + ".part"]:
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception as e:
                            logger.warning(f"无法清理旧文件 {p}: {e}")
                
                logger.info(f"DEBUG: 正在获取消息 {chat_id}/{message_id}")
                msg = await client.get_messages(chat_id, message_id)
                if not msg:
                    logger.error(f"User API 获取消息失败: {chat_id}/{message_id}")
                    if attempts < max_attempts: continue
                    return False
                
                # 诊断媒体内容
                media_type = "None"
                if msg.media:
                    media_type = msg.media.value
                logger.info(f"DEBUG: 消息内容 - ID: {msg.id}, Media: {media_type}, From: {msg.chat.id if msg.chat else 'Unknown'}")
                
                # --- 智能搜索回退 ---
                # 在私聊中，Bot API 的 message_id 可能与 MTProto (User API) 的不一致
                # 如果获取到的消息没有媒体，或者媒体不匹配我们的预期，尝试在最近的 20 条消息中寻找
                
                def get_msg_file_unique_id(m):
                    if not m.media: return None
                    media_attr = getattr(m, m.media.value) if m.media else None
                    return getattr(media_attr, 'file_unique_id', None)

                curr_unique_id = get_msg_file_unique_id(msg)
                
                if not msg.media or (file_unique_id and curr_unique_id != file_unique_id):
                    if msg.media:
                        logger.info(f"DEBUG: 消息 {chat_id}/{message_id} 属性不匹配 (预期: {file_unique_id}, 实际: {curr_unique_id})。转入搜索模式...")
                    else:
                        logger.info(f"DEBUG: 消息 {chat_id}/{message_id} 无媒体内容。转入搜索模式...")
                        
                    found_msg = None
                    async for history_msg in client.get_chat_history(chat_id, limit=150):
                        h_unique_id = get_msg_file_unique_id(history_msg)
                        if history_msg.media:
                            if file_unique_id:
                                if h_unique_id == file_unique_id:
                                    logger.info(f"DEBUG: 在历史记录中找到了匹配项 - ID: {history_msg.id}")
                                    found_msg = history_msg
                                    break
                            else:
                                logger.info(f"DEBUG: 在历史记录中找到了潜在媒体 - ID: {history_msg.id}")
                                found_msg = history_msg
                                break
                    
                    if found_msg:
                        msg = found_msg
                        # 重要：更新 message_id，使得如果下载报错重试时使用正确的 ID
                        message_id = found_msg.id
                    else:
                        logger.info(f"DEBUG: 在最近历史记录中未找到匹配的媒体。")
                        # 如果搜索也无果，且 ID 不对，直接返回失败以便外层进入回退下载逻辑，不再浪费重试
                        return False

                t_start = time.time()
                downloaded_path = await client.download_media(
                    msg, 
                    file_name=final_path,
                    progress=progress_callback
                )
                t_end = time.time()
                
                if downloaded_path and os.path.exists(downloaded_path):
                    # --- 完整性验证 ---
                    actual_size = os.path.getsize(downloaded_path)
                    expected_size = 0
                    
                    # 尽可能从全量媒体属性中提取预期大小
                    media_attr = getattr(msg, msg.media.value) if msg.media else None
                    if media_attr and hasattr(media_attr, 'file_size'):
                        expected_size = media_attr.file_size
                    elif msg.video: expected_size = msg.video.file_size
                    elif msg.document: expected_size = msg.document.file_size
                    elif msg.photo: 
                        # 照片如果是列表，取最后一个（最大的）
                        if isinstance(msg.photo, list): 
                            expected_size = msg.photo[-1].file_size
                        else:
                            expected_size = msg.photo.file_size
                    elif msg.animation: expected_size = msg.animation.file_size
                    
                    if expected_size > 0:
                        if actual_size < expected_size:
                            logger.error(f"⚠️ 下载文件完整性校验失败: {final_path}")
                            logger.error(f"预期大小: {expected_size} 字节, 实际大小: {actual_size} 字节 (偏小)")
                            try: os.remove(downloaded_path)
                            except: pass
                            if attempts < max_attempts: continue
                            return False
                        else:
                            logger.info(f"✅ 文件完整性通过: {actual_size} / {expected_size} 字节")
                    else:
                        logger.warning(f"❓ 无法确定媒体预期大小，跳过严格校验: {final_path} (当前大小: {actual_size})")

                    if attempts > 1:
                        logger.info(f"User API 重试下载成功 [{t_end-t_start:.1f}s]: {final_path}")
                    else:
                        logger.info(f"User API 下载完成 [{t_end-t_start:.1f}s]: {final_path}")
                    return True
                
                # 如果返回空但没抛异常，也触发重试
                if attempts < max_attempts: continue
                return False
                
            except Exception as e:
                err_str = str(e)
                # 捕获 BadMsgNotification 或由此引发的解析错误，这些通常需要重置 Session
                is_mtproto_error = "BadMsgNotification" in err_str or "attribute 'users'" in err_str or "attribute 'bytes'" in err_str
                
                if attempts < max_attempts:
                    # 识别不可重试的永久性错误 (通常是权限、Peer 异常或消息丢失)
                    if isinstance(e, (ChannelInvalid, ChannelPrivate, MsgIdInvalid, PeerIdInvalid, ChatWriteForbidden)) or \
                       "CHANNEL_INVALID" in err_str or "CHANNEL_PRIVATE" in err_str or "MSG_ID_INVALID" in err_str:
                        logger.error(f"User API 遇到不可重试的错误: {e}。这通常意味着当前 User API 账号没有该频道/群组的访问权限，或者消息已被删除。")
                        return False

                    if is_mtproto_error:
                        logger.warning(f"触发 MTProto 同步错误: {e}，正在强制重置客户端并重试...")
                        await _reset_client()
                    else:
                        logger.warning(f"下载过程中发生异常: {e}，正在尝试第 {attempts} 次重试...")
                    
                    # 等待一下让网络或其他状态稳定
                    await asyncio.sleep(1.5)
                    continue
                else:
                    # 最后一次尝试也失败了
                    if is_mtproto_error:
                        # 记录详细堆栈
                        logger.error(f"User API 连续 {max_attempts} 次触发 MTProto 错误，任务失败: {e}", exc_info=True)
                    else:
                        logger.error(f"User API 下载任务最终失败 (已重试 {attempts-1} 次): {e}", exc_info=True)
                    return False
        return False

def start_user_api():
    """API 入口：预连接"""
    try:
        get_pyrogram_client()
        return True
    except Exception as e:
        logger.error(f"User API 预启动失败: {e}")
        return False

def run_download_large_file(chat_id, message_id, final_path, progress_callback=None, file_unique_id=None):
    """同步封装器"""
    get_pyrogram_client() 
    future = asyncio.run_coroutine_threadsafe(
        _do_download(chat_id, message_id, final_path, progress_callback, file_unique_id), 
        _loop
    )
    try:
        # 大文件下载允许较长时间，但设置上限以防永久挂死 (默认 1 小时)
        return future.result(timeout=3600)
    except Exception as e:
        logger.error(f"User API 任务执行抛出异常: {e}", exc_info=True)
        return False


def run_get_message_media_info(chat_id, message_id):
    """同步获取 User API 可见消息的媒体信息。"""
    get_pyrogram_client()
    future = asyncio.run_coroutine_threadsafe(
        _get_message_media_info(chat_id, message_id),
        _loop
    )
    try:
        return future.result(timeout=120)
    except Exception as e:
        logger.error(f"User API 获取链接消息失败: {e}", exc_info=True)
        return None


def run_get_link_media_items(chat_id, message_id):
    """同步获取链接消息对应的媒体列表；媒体组会展开为整组。"""
    get_pyrogram_client()
    future = asyncio.run_coroutine_threadsafe(
        _get_link_media_items(chat_id, message_id),
        _loop
    )
    try:
        return future.result(timeout=120)
    except Exception as e:
        logger.error(f"User API 获取链接媒体列表失败: {e}", exc_info=True)
        return []


def run_download_message_media(chat_id, message_id, final_path, progress_callback=None):
    """同步下载 User API 可见消息中的媒体。"""
    get_pyrogram_client()
    future = asyncio.run_coroutine_threadsafe(
        _download_message_media(chat_id, message_id, final_path, progress_callback),
        _loop
    )
    try:
        downloaded_path = future.result(timeout=3600)
        return bool(downloaded_path and os.path.exists(downloaded_path))
    except Exception as e:
        logger.error(f"User API 链接下载任务失败: {e}", exc_info=True)
        return False

async def _get_chat_pinned_message(chat_id):
    """获取对话的置顶消息文本。"""
    try:
        client = get_pyrogram_client()
        chat = await client.get_chat(chat_id)
        if chat.pinned_message and chat.pinned_message.text:
            return chat.pinned_message.text
        return None
    except Exception as e:
        logger.warning(f"获取置顶消息失败 {chat_id}: {e}")
        return None


def run_get_chat_pinned_message(chat_id):
    """同步获取对话置顶消息文本。"""
    get_pyrogram_client()
    future = asyncio.run_coroutine_threadsafe(
        _get_chat_pinned_message(chat_id),
        _loop
    )
    try:
        return future.result(timeout=30)
    except Exception as e:
        logger.error(f"获取置顶消息失败: {e}")
        return None


def stop_user_api():
    """停止 User API 客户端 (优雅退出)"""
    global _app, _loop
    if _app and _app.is_connected:
        try:
            logger.info("正在停止 User API 客户端...")
            future = asyncio.run_coroutine_threadsafe(_app.stop(), _loop)
            future.result(timeout=5)
            logger.info("User API 客户端已安全停止")
        except Exception as e:
            logger.error(f"停止 User API 客户端失败: {e}")


async def build_pyrogram_client():
    """为一次性脚本（如回填）创建独立的 Client 实例，不走单例。"""
    app = Client(
        "telegrabber_user",
        api_id=API_ID,
        api_hash=API_HASH,
        proxy=_get_proxy_dict(),
        workdir=DATA_DIR,
        sleep_threshold=60,
    )
    await app.start()
    return app
