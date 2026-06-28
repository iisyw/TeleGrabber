"""单条消息下载的公共逻辑：去重提示、大文件 User API 下载（含进度）、小文件 Bot API 下载。

四个 handler (photo/video/document/animation) 共用这里的函数，避免重复代码。
适配 python-telegram-bot v21：handler 为 async，bot 调用需 await；
Pyrogram (User API) 仍跑在自己的事件循环线程里，通过同步封装在 executor 中调用。
"""

import os
import time
import asyncio
import threading

from config import logger, USER_API_ENABLED
from utils import (
    get_save_directory, generate_temp_filename, get_image_extension,
    get_video_extension, save_to_db, get_duplicate_info,
)
import user_api

# 大文件阈值：超过此大小走 User API (MTProto)，因为 Bot API 限制 20MB
LARGE_FILE_THRESHOLD = 20 * 1024 * 1024

# 媒体类型的中文显示名，用于提示文案
MEDIA_LABELS = {
    'photo': '图片',
    'video': '视频',
    'animation': '动画',
    'document': '图片文件',
}


async def reply_duplicate(update, media_obj, media_type, caption):
    """检测重复资源，若重复则回复完整提示并返回 True。"""
    dup_info = get_duplicate_info(media_obj.file_unique_id)
    if not dup_info:
        return False

    label = MEDIA_LABELS.get(media_type, '资源')
    source_display = dup_info.get('source') or '未知'
    if dup_info.get('source_link'):
        source_display = f"[{dup_info['source']}]({dup_info['source_link']})"

    reply_msg = (
        f"♻️ **检测到重复资源 ({label})**\n\n"
        f"文件已存在: `{dup_info['filename']}`\n"
        f"最初来源: {source_display}\n"
        f"最初描述: {dup_info.get('caption') or '无'}\n"
        f"当前描述: {caption or '无'}"
    )
    await update.message.reply_text(
        reply_msg,
        parse_mode='Markdown',
        disable_web_page_preview=True,
        reply_to_message_id=update.message.message_id,
    )
    return True


def _make_progress_callback(bot, loop, chat_id, status_message_id, prefix):
    """生成下载进度回调 (Pyrogram 签名: current, total)。

    回调在 Pyrogram 的事件循环线程里被调用，这里通过 run_coroutine_threadsafe
    把消息编辑调度回 PTB 的主事件循环（bot.edit_message_text 是协程）。
    带节流：百分比变化且至少间隔 2 秒才更新，100% 强制更新。
    """
    st = {"last_time": 0.0, "last_percent": -1}

    def callback(current, total):
        if not total:
            return
        percent = int(current * 100 / total)
        now = time.time()
        if percent == st["last_percent"]:
            return
        if now - st["last_time"] < 2 and percent < 100:
            return
        st["last_time"] = now
        st["last_percent"] = percent

        async def _edit():
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text=f"{prefix}\n进度: {percent}%",
                )
            except Exception:
                pass
        try:
            asyncio.run_coroutine_threadsafe(_edit(), loop)
        except Exception:
            pass

    return callback


async def download_large_via_user_api(update, context, media_obj, media_type, date_dir,
                                      ext, source_info, status_message):
    """通过 User API 下载大文件（含进度、溯源、回退、存库）。返回最终文件名或 None。

    User API 调用是阻塞的，放到默认线程池执行，避免阻塞 PTB 事件循环。
    """
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = source_info

    temp_filename = generate_temp_filename()
    final_filename = f"{temp_filename}{ext}"
    final_path = os.path.join(date_dir, final_filename)

    chat = update.effective_chat
    label = MEDIA_LABELS.get(media_type, '文件')
    loop = asyncio.get_running_loop()

    progress = _make_progress_callback(
        context.bot, loop, chat.id, status_message.message_id,
        prefix=f"⏳ 正在通过 User API 下载大{label}...",
    ) if status_message else None

    # 溯源：优先用原始频道/消息 ID
    target_chat_id = orig_chat_id or chat.id
    target_msg_id = orig_msg_id or update.message.message_id
    if not orig_chat_id and (chat.type == 'private' or source_type in ["user", "private_user"]):
        target_chat_id = context.bot.username or context.bot.id

    success = await loop.run_in_executor(
        None,
        lambda: user_api.run_download_large_file(
            target_chat_id, target_msg_id, final_path,
            progress_callback=progress,
            file_unique_id=media_obj.file_unique_id,
        ),
    )

    # 溯源失败则回退到当前聊天下载
    if not success and target_chat_id != chat.id:
        logger.warning(f"大{label}溯源下载失败，尝试从本地聊天回退下载...")
        fallback_chat_id = chat.id
        if chat.type == 'private' or source_type in ["user", "private_user"]:
            fallback_chat_id = context.bot.username or context.bot.id
        success = await loop.run_in_executor(
            None,
            lambda: user_api.run_download_large_file(
                fallback_chat_id, update.message.message_id, final_path,
                progress_callback=progress,
                file_unique_id=media_obj.file_unique_id,
            ),
        )

    if not success:
        return None

    save_to_db(
        update.effective_user, media_obj, final_filename,
        save_dir=date_dir, media_type=media_type, caption=update.message.caption,
        source=source, source_id=source_id, source_link=source_link, source_type=source_type,
    )
    return final_filename


async def save_small_file(update, media_obj, media_type, date_dir, source_info, detect_ext):
    """通过 Bot API 下载小文件并存库。返回最终文件名或 None。

    v21 中 get_file() 与 file.download_to_drive() 均为协程。
    detect_ext 与 save_to_db 是同步的轻量操作，直接调用即可。
    """
    source, source_id, source_link, source_type, _, _ = source_info

    temp_filename = generate_temp_filename()
    temp_path = os.path.join(date_dir, f"{temp_filename}_temp")

    try:
        media_file = await media_obj.get_file()
        await media_file.download_to_drive(temp_path)

        ext = detect_ext(temp_path)
        final_filename = f"{temp_filename}{ext}"
        final_path = os.path.join(date_dir, final_filename)
        os.rename(temp_path, final_path)

        save_to_db(
            update.effective_user, media_obj, final_filename,
            save_dir=date_dir, media_type=media_type, caption=update.message.caption,
            source=source, source_id=source_id, source_link=source_link, source_type=source_type,
        )
        logger.info(f"已保存{MEDIA_LABELS.get(media_type, '文件')}: {final_path}")
        return final_filename
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        logger.error(f"{MEDIA_LABELS.get(media_type, '文件')}下载失败: {e}")
        return None
