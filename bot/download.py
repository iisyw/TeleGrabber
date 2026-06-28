"""单条消息下载的公共逻辑：去重提示、大文件 User API 下载（含进度）、小文件 Bot API 下载。

四个 handler (photo/video/document/animation) 共用这里的函数，避免重复代码。
"""

import os
import time
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


def reply_duplicate(update, media_obj, media_type, caption):
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
    update.message.reply_text(
        reply_msg,
        parse_mode='Markdown',
        disable_web_page_preview=True,
        reply_to_message_id=update.message.message_id,
    )
    return True


def _make_progress_callback(context, chat_id, status_message_id, prefix):
    """生成一个带节流的下载进度回调 (Pyrogram 签名: current, total)。

    Telegram 对消息编辑有频率限制，故至少间隔 2 秒、且百分比变化时才更新；
    更新在独立线程中进行，不阻塞下载。
    """
    state = {"last_time": 0.0, "last_percent": -1}

    def callback(current, total):
        if not total:
            return
        percent = int(current * 100 / total)
        now = time.time()
        if percent == state["last_percent"]:
            return
        if now - state["last_time"] < 2 and percent < 100:
            return
        state["last_time"] = now
        state["last_percent"] = percent

        def _edit():
            try:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text=f"{prefix}\n进度: {percent}%",
                )
            except Exception:
                pass
        threading.Thread(target=_edit, daemon=True).start()

    return callback


def download_large_via_user_api(update, context, media_obj, media_type, date_dir,
                                ext, source_info, status_message):
    """通过 User API 下载大文件（含进度、溯源、回退、存库）。返回最终文件名或 None。

    media_obj: 带 file_id / file_unique_id 的对象
    source_info: (source, source_id, source_link, source_type, orig_chat_id, orig_msg_id)
    status_message: 已发送的"正在下载"消息对象，用于刷新进度
    """
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = source_info

    temp_filename = generate_temp_filename()
    final_filename = f"{temp_filename}{ext}"
    final_path = os.path.join(date_dir, final_filename)

    chat = update.effective_chat
    label = MEDIA_LABELS.get(media_type, '文件')

    progress = _make_progress_callback(
        context, chat.id, status_message.message_id,
        prefix=f"⏳ 正在通过 User API 下载大{label}...",
    ) if status_message else None

    # 溯源：优先用原始频道/消息 ID
    target_chat_id = orig_chat_id or chat.id
    target_msg_id = orig_msg_id or update.message.message_id
    if not orig_chat_id and (chat.type == 'private' or source_type in ["user", "private_user"]):
        target_chat_id = context.bot.username or context.bot.id

    success = user_api.run_download_large_file(
        target_chat_id, target_msg_id, final_path,
        progress_callback=progress,
        file_unique_id=media_obj.file_unique_id,
    )

    # 溯源失败则回退到当前聊天下载
    if not success and target_chat_id != chat.id:
        logger.warning(f"大{label}溯源下载失败，尝试从本地聊天回退下载...")
        fallback_chat_id = chat.id
        if chat.type == 'private' or source_type in ["user", "private_user"]:
            fallback_chat_id = context.bot.username or context.bot.id
        success = user_api.run_download_large_file(
            fallback_chat_id, update.message.message_id, final_path,
            progress_callback=progress,
            file_unique_id=media_obj.file_unique_id,
        )

    if not success:
        return None

    save_to_db(
        update.effective_user, media_obj, final_filename,
        save_dir=date_dir, media_type=media_type, caption=update.message.caption,
        source=source, source_id=source_id, source_link=source_link, source_type=source_type,
    )
    return final_filename


def save_small_file(update, media_obj, media_type, date_dir, source_info,
                    detect_ext, status_message=None):
    """通过 Bot API 下载小文件并存库。返回最终文件名或 None。

    detect_ext: 接收临时文件路径、返回扩展名的回调（不同媒体类型检测方式不同）
    status_message: 可选的"处理中"消息，完成后会被编辑为结果
    """
    source, source_id, source_link, source_type, _, _ = source_info

    temp_filename = generate_temp_filename()
    temp_path = os.path.join(date_dir, f"{temp_filename}_temp")

    try:
        media_file = media_obj.get_file()
        media_file.download(temp_path)

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
