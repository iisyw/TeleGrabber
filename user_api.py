#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pyrogram import Client
from config import API_ID, API_HASH, PROXY, logger, SAVE_DIR
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
_semaphore = None # 用于强制顺序下载

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
        return {
            "scheme": parsed.scheme,
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
            workdir=os.getcwd(),
            workers=60, 
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

async def _do_download(chat_id, message_id, final_path, progress_callback=None):
    client = get_pyrogram_client()
    try:
        # 使用信号量强制排队，匹配用户观察到的物理串行特性，UI 表现也最整齐
        async with _semaphore:
            logger.info(f"User API 占用执行槽位: {final_path}")
            
            msg = await client.get_messages(chat_id, message_id)
            if not msg:
                logger.error(f"User API 获取消息失败: {chat_id}/{message_id}")
                return False
                
            t_start = time.time()
            downloaded_path = await client.download_media(
                msg, 
                file_name=final_path,
                progress=progress_callback
            )
            t_end = time.time()
            
            if downloaded_path:
                logger.info(f"User API 下载完成 [{t_end-t_start:.1f}s]: {final_path}")
                return True
            return False
    except Exception as e:
        logger.error(f"User API 下载异常: {e}")
        return False

def start_user_api():
    """API 入口：预连接"""
    try:
        get_pyrogram_client()
        return True
    except Exception as e:
        logger.error(f"User API 预启动失败: {e}")
        return False

def run_download_large_file(chat_id, message_id, final_path, progress_callback=None):
    """同步封装器"""
    get_pyrogram_client() 
    future = asyncio.run_coroutine_threadsafe(
        _do_download(chat_id, message_id, final_path, progress_callback), 
        _loop
    )
    try:
        return future.result()
    except Exception as e:
        logger.error(f"User API 任务执行抛出异常: {e}")
        return False
