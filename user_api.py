#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pyrogram import Client
from pyrogram.errors import ChannelInvalid, ChannelPrivate, MsgIdInvalid, PeerIdInvalid, ChatWriteForbidden
from config import API_ID, API_HASH, PROXY, logger, SAVE_DIR, DOWNLOAD_RETRIES, DATA_DIR
import os
import asyncio
import time
import threading

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
        from urllib.parse import urlparse
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
                _app = future.result() 
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
                    logger.warning(f"DEBUG: 消息 {chat_id}/{message_id} 属性不匹配 (expected_uid: {file_unique_id}, actual: {curr_unique_id})! 尝试在历史记录中进行搜索回退...")
                    found_msg = None
                    async for history_msg in client.get_chat_history(chat_id, limit=30):
                        h_unique_id = get_msg_file_unique_id(history_msg)
                        if history_msg.media:
                            if file_unique_id:
                                # 如果提供了 file_unique_id，则进行精确匹配
                                if h_unique_id == file_unique_id:
                                    logger.info(f"DEBUG: 在历史记录中找到了精确匹配的媒体消息 - ID: {history_msg.id}")
                                    found_msg = history_msg
                                    break
                            else:
                                # 如果没提供，则退而求其次寻找任何可用的媒体（通常是单次任务）
                                logger.info(f"DEBUG: 在历史记录中找到了潜在的媒体消息 - ID: {history_msg.id}")
                                found_msg = history_msg
                                break
                    
                    if found_msg:
                        msg = found_msg
                    else:
                        logger.warning(f"DEBUG: 在最近历史记录中未找到匹配的媒体，下载失败。")
                        if attempts < max_attempts: continue
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
        return future.result()
    except Exception as e:
        logger.error(f"User API 任务执行抛出异常: {e}", exc_info=True)
        return False

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
