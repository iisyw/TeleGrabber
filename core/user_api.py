#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pyrogram import Client, utils
from pyrogram.errors import (
    ChannelInvalid, ChannelPrivate, MsgIdInvalid, PeerIdInvalid,
    ChatWriteForbidden, FloodWait, ChatForwardsRestricted,
)
from .config import (
    API_ID, API_HASH, PROXY, logger, DOWNLOAD_RETRIES, DATA_DIR,
    DOWNLOAD_TIMEOUT, DOWNLOAD_STALL_TIMEOUT, MIN_FREE_MB,
    USER_API_ENABLED,
)
import os
import asyncio
import time
import threading
import mimetypes
import random
import re
import shutil
from urllib.parse import urlparse
from datetime import timezone

# --- 全局状态 ---
_app = None
_loop = None
_loop_thread = None
_init_lock = threading.Lock()
# 已确认开启“内容保护/禁止转发”的会话，避免每次重复尝试转发
_protected_chats = set()
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


def get_own_user_id():
    """返回 User API 登录账号的 user id；未启用/未登录时返回 None。"""
    try:
        client = get_pyrogram_client()
        me = getattr(client, 'me', None) if client else None
        return getattr(me, 'id', None)
    except Exception as e:
        logger.debug(f"获取 User API 账号 ID 失败: {e}")
        return None


def get_status():
    """返回 User API 当前运行状态，供状态页展示（不触发登录）。"""
    client = _app
    me = getattr(client, 'me', None) if client else None
    return {
        "enabled": USER_API_ENABLED,
        "connected": bool(client and getattr(client, 'is_connected', False)),
        "user_id": getattr(me, 'id', None),
        "username": getattr(me, 'username', None),
        "protected_chat_count": len(_protected_chats),
    }


def is_chat_protected(chat_id):
    """该会话是否已确认开启内容保护/禁止转发。"""
    if chat_id is None:
        return False
    return str(chat_id) in _protected_chats


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
        'width': getattr(media_obj, 'width', None),
        'height': getattr(media_obj, 'height', None),
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
        'source_type': _enum_value(getattr(chat, 'type', None)),
        'media_group_id': str(getattr(message, 'media_group_id', '') or ''),
        'message_id': message.id,
        'message_date': msg_date.isoformat() if msg_date else None,
    }


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


def _expected_media_size(message):
    """尽量提取媒体预期大小；无法确定时返回 0。"""
    media_attr = getattr(message, message.media.value) if getattr(message, 'media', None) else None
    if media_attr and hasattr(media_attr, 'file_size'):
        return int(media_attr.file_size or 0)
    if getattr(message, 'video', None):
        return int(message.video.file_size or 0)
    if getattr(message, 'document', None):
        return int(message.document.file_size or 0)
    if getattr(message, 'photo', None):
        photos = message.photo if isinstance(message.photo, list) else [message.photo]
        return int(photos[-1].file_size or 0)
    if getattr(message, 'animation', None):
        return int(message.animation.file_size or 0)
    return 0


def _is_permanent_download_error(exc):
    """权限、消息丢失、文件过大等重试也不会成功的错误。"""
    if isinstance(exc, (ChannelInvalid, ChannelPrivate, MsgIdInvalid, PeerIdInvalid, ChatWriteForbidden)):
        return True
    if isinstance(exc, ChatForwardsRestricted):
        return True
    err = str(exc).upper()
    markers = (
        "CHANNEL_INVALID", "CHANNEL_PRIVATE", "MSG_ID_INVALID", "PEER_ID_INVALID",
        "FILE_TOO_BIG", "CHAT_FORWARDS_RESTRICTED", "AUTH_KEY_UNREGISTERED",
        "USER_DEACTIVATED",
    )
    return any(marker in err for marker in markers)


async def _download_media_with_limits(client, target, final_path, progress_callback=None, expected_size=0):
    """下载到 .part，校验完整性后原子改名；同时做总超时和“无进度”卡死检测。"""
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(final_path))).free
    required = int((expected_size or 0) * 1.05) + MIN_FREE_MB * 1024 * 1024
    if free < required:
        raise OSError(
            f"磁盘空间不足：需要约 {required // (1024 * 1024)}MB，"
            f"当前剩余 {free // (1024 * 1024)}MB"
        )

    part_path = final_path + ".part"
    for path in (part_path, part_path + ".temp", final_path + ".temp"):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    progress_state = {"last": time.monotonic()}

    def _progress(current, total):
        progress_state["last"] = time.monotonic()
        if progress_callback:
            try:
                progress_callback(current, total)
            except Exception:
                pass

    dl_task = asyncio.create_task(
        client.download_media(target, file_name=part_path, progress=_progress)
    )

    async def _watchdog():
        while True:
            await asyncio.sleep(10)
            if time.monotonic() - progress_state["last"] > DOWNLOAD_STALL_TIMEOUT:
                dl_task.cancel()
                raise asyncio.TimeoutError(
                    f"下载连续 {DOWNLOAD_STALL_TIMEOUT} 秒无进度"
                )

    watchdog_task = asyncio.create_task(_watchdog())
    try:
        done, _ = await asyncio.wait(
            {dl_task, watchdog_task},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=DOWNLOAD_TIMEOUT,
        )
        if not done:
            dl_task.cancel()
            raise asyncio.TimeoutError(f"下载超过 {DOWNLOAD_TIMEOUT} 秒")

        if watchdog_task in done:
            dl_task.cancel()
            exc = watchdog_task.exception()
            raise exc or asyncio.TimeoutError("下载卡死")

        downloaded_path = dl_task.result()
        if not downloaded_path or not os.path.exists(part_path):
            raise RuntimeError("下载未生成完整的临时文件")

        actual_size = os.path.getsize(part_path)
        if expected_size and actual_size < expected_size:
            raise RuntimeError(
                f"文件完整性校验失败: 预期 {expected_size} 字节，实际 {actual_size} 字节"
            )

        os.replace(part_path, final_path)
        return final_path, actual_size
    finally:
        for task in (dl_task, watchdog_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(dl_task, watchdog_task, return_exceptions=True)
        for path in (part_path, part_path + ".temp", final_path + ".temp"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


async def _download_message_media(chat_id, message_id, final_path, progress_callback=None):
    async with _semaphore:
        client = get_pyrogram_client()
        message = await client.get_messages(chat_id, message_id)
        if not message or not message.media:
            return None
        document = getattr(message, 'document', None)
        target = document if _is_media_document(document) else message

        max_attempts = max(1, DOWNLOAD_RETRIES + 1)
        for attempt in range(1, max_attempts + 1):
            try:
                downloaded_path, _ = await _download_media_with_limits(
                    client, target, final_path, progress_callback,
                    expected_size=_expected_media_size(message),
                )
                return downloaded_path
            except Exception as e:
                if _is_permanent_download_error(e) or attempt >= max_attempts:
                    logger.error(f"User API 链接下载失败 (第 {attempt} 次): {e}")
                    return None
                delay = min(30, 2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(f"User API 链接下载异常: {e}，{delay:.1f}s 后重试...")
                await asyncio.sleep(delay)
        return None


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
                expected_size = _expected_media_size(msg)
                downloaded_path, actual_size = await _download_media_with_limits(
                    client, msg, final_path, progress_callback,
                    expected_size=expected_size,
                )
                t_end = time.time()

                if expected_size:
                    logger.info(f"✅ 文件完整性通过: {actual_size} / {expected_size} 字节")
                else:
                    logger.warning(f"❓ 无法确定媒体预期大小，跳过严格校验: {final_path} (当前大小: {actual_size})")

                if attempts > 1:
                    logger.info(f"User API 重试下载成功 [{t_end-t_start:.1f}s]: {final_path}")
                else:
                    logger.info(f"User API 下载完成 [{t_end-t_start:.1f}s]: {final_path}")
                return True
                
            except Exception as e:
                err_str = str(e)
                # 捕获 BadMsgNotification 或由此引发的解析错误，这些通常需要重置 Session
                is_mtproto_error = "BadMsgNotification" in err_str or "attribute 'users'" in err_str or "attribute 'bytes'" in err_str

                if _is_permanent_download_error(e):
                    logger.error(f"User API 遇到不可重试的错误: {e}。这通常意味着账号没有访问权限、消息已删除或文件不允许下载。")
                    return False

                if attempts < max_attempts:
                    if isinstance(e, FloodWait):
                        wait_seconds = int(getattr(e, 'value', 0) or 0) + 1
                        logger.warning(f"触发 FloodWait，等待 {wait_seconds}s 后重试...")
                        await asyncio.sleep(wait_seconds)
                    elif is_mtproto_error:
                        logger.warning(f"触发 MTProto 同步错误: {e}，正在强制重置客户端并重试...")
                        await _reset_client()
                        await asyncio.sleep(1.5)
                    else:
                        delay = min(30, 2 ** (attempts - 1)) + random.uniform(0, 1)
                        logger.warning(f"下载过程中发生异常: {e}，{delay:.1f}s 后尝试第 {attempts} 次重试...")
                        await asyncio.sleep(delay)
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
        # 大文件下载允许较长时间，但设置上限以防永久挂死
        return future.result(timeout=DOWNLOAD_TIMEOUT + 120)
    except Exception as e:
        logger.error(f"User API 任务执行抛出异常: {e}", exc_info=True)
        return False


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
        downloaded_path = future.result(timeout=DOWNLOAD_TIMEOUT + 120)
        return bool(downloaded_path and os.path.exists(downloaded_path))
    except Exception as e:
        logger.error(f"User API 链接下载任务失败: {e}", exc_info=True)
        return False


def _is_forwards_restricted(exc):
    """判断异常是否为“来源禁止转发”类错误。"""
    if isinstance(exc, ChatForwardsRestricted):
        return True
    return "CHAT_FORWARDS_RESTRICTED" in str(exc).upper()


async def _forward_to_bot(bot_target, from_chat_id, message_id):
    """把来源消息（含所属媒体组）转发到与 bot 的会话，交由常规下载流程处理。

    Returns:
        dict: {"ok": True, "count": N} 成功；失败时 {"ok": False, "reason": ...}，
              reason 取值 not_found / no_media / protected / 其他错误串。
    """
    chat_key = str(from_chat_id)
    if chat_key in _protected_chats:
        return {"ok": False, "reason": "protected"}

    client = get_pyrogram_client()
    message = await client.get_messages(from_chat_id, message_id)
    if not message:
        return {"ok": False, "reason": "not_found"}

    chat = getattr(message, 'chat', None)
    if getattr(chat, 'has_protected_content', False):
        _protected_chats.add(chat_key)
        if getattr(chat, 'id', None) is not None:
            _protected_chats.add(str(chat.id))
        return {"ok": False, "reason": "protected"}

    if not message.media:
        return {"ok": False, "reason": "no_media"}

    message_ids = [message_id]
    if getattr(message, 'media_group_id', None):
        try:
            group = await message.get_media_group()
            message_ids = sorted(m.id for m in group)
        except Exception as e:
            logger.warning(f"获取媒体组失败，仅转发单条: {e}")
            message_ids = [message_id]

    try:
        await client.forward_messages(
            chat_id=bot_target,
            from_chat_id=from_chat_id,
            message_ids=message_ids,
        )
        numeric_chat_id = getattr(chat, 'id', None)
        username = getattr(chat, 'username', None)
        return {
            "ok": True,
            "count": len(message_ids),
            "numeric_chat_id": numeric_chat_id,
            "username": username,
            "message_ids": message_ids,
        }
    except Exception as e:
        if _is_forwards_restricted(e):
            _protected_chats.add(chat_key)
            if getattr(chat, 'id', None) is not None:
                _protected_chats.add(str(chat.id))
            return {"ok": False, "reason": "protected"}
        logger.warning(f"转发消息到 bot 失败: {e}")
        return {"ok": False, "reason": str(e)}


def run_forward_to_bot(bot_target, from_chat_id, message_id):
    """同步封装：把来源消息转发到 bot 会话。"""
    get_pyrogram_client()
    future = asyncio.run_coroutine_threadsafe(
        _forward_to_bot(bot_target, from_chat_id, message_id),
        _loop
    )
    try:
        return future.result(timeout=150)
    except Exception as e:
        logger.error(f"转发任务执行异常: {e}", exc_info=True)
        return {"ok": False, "reason": str(e)}


def stop_user_api():
    """停止 User API 客户端 (优雅退出)"""
    if _app and _app.is_connected:
        try:
            logger.info("正在停止 User API 客户端...")
            future = asyncio.run_coroutine_threadsafe(_app.stop(), _loop)
            future.result(timeout=5)
            logger.info("User API 客户端已安全停止")
        except Exception as e:
            logger.error(f"停止 User API 客户端失败: {e}")
    if _loop and _loop.is_running():
        try:
            _loop.call_soon_threadsafe(_loop.stop)
        except Exception as e:
            logger.error(f"停止 User API 事件循环失败: {e}")
