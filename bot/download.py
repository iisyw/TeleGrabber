"""单条消息下载的公共逻辑：去重提示、大文件 User API 下载（含进度）、小文件 Bot API 下载。

四个 handler (photo/video/document/animation) 共用这里的函数，避免重复代码。
适配 python-telegram-bot v21：handler 为 async，bot 调用需 await；
Pyrogram (User API) 仍跑在自己的事件循环线程里，通过同步封装在 executor 中调用。
"""

import os
import time
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import logger, USER_API_ENABLED
from utils import (
    get_save_directory, generate_temp_filename, get_image_extension,
    get_video_extension, save_to_db, get_duplicate_info, delete_media_records,
    get_message_date, get_message_id, utc_to_local,
)
import user_api
from bot import state

# 大文件阈值：超过此大小走 User API (MTProto)，因为 Bot API 限制 20MB
LARGE_FILE_THRESHOLD = 20 * 1024 * 1024

# 媒体类型的中文显示名，用于提示文案
MEDIA_LABELS = {
    'photo': '图片',
    'video': '视频',
    'animation': '动画',
    'document': '文件',
}

DOWNLOAD_METHOD_BOT = 'bot_api'
DOWNLOAD_METHOD_USER = 'user_api'


def get_media_label(media_type):
    return MEDIA_LABELS.get(media_type, media_type or '媒体')


def get_media_ext(media_info):
    ext = media_info.get('ext')
    if ext:
        return ext
    media_type = media_info.get('media_type')
    if media_type == 'video':
        return '.mp4'
    if media_type == 'animation':
        return '.gif'
    if media_type == 'document':
        return '.jpg'
    return '.jpg'


def build_download_filename(media_info, index=None, media_group_id=None, group_prefix=None):
    ext = get_media_ext(media_info)
    if media_group_id and index is not None:
        prefix = group_prefix or generate_temp_filename(media_group_id)
        return f"{media_group_id}_{index}_{prefix}{ext}"
    return f"{generate_temp_filename()}{ext}"


def build_progress_bar(media_items, items_status, item_progress):
    bot_map = {0: "⏳", 1: "✅", 2: "♻️", 3: "❌"}
    user_map = {0: "🕓", 1: "🟢", 2: "♻️", 3: "🔴"}
    parts = []
    for i, status in enumerate(items_status):
        method = media_items[i].get('download_method', DOWNLOAD_METHOD_BOT)
        is_user_api = method == DOWNLOAD_METHOD_USER
        if status == 4:
            parts.append(f"{'☁️' if is_user_api else '🔽'}{item_progress[i]}%")
        else:
            parts.append((user_map if is_user_api else bot_map).get(status, "❓"))
    return "".join(parts)


def save_media_metadata(user, media_info, final_filename, save_dir, media_group_id=None, fallback_link1=None, message_time=None):
    media_obj_stub = type('Media', (), {
        'file_id': media_info['file_id'],
        'file_unique_id': media_info['file_unique_id'],
    })
    return save_to_db(
        user, media_obj_stub, final_filename,
        save_dir=save_dir, media_group_id=media_group_id,
        media_type=media_info.get('media_type', 'photo'),
        caption=media_info.get('caption'),
        source_name=media_info.get('source_name'), source_id=media_info.get('source_id'),
        source_link1=media_info.get('source_link1') or fallback_link1,
        source_link2=media_info.get('source_link2'),
        source_username=media_info.get('source_username'),
        source_type=media_info.get('source_type'),
        message_time=message_time,
        message_id=media_info.get('message_id'),
    )


def _single_buttons(single_key, is_dup, has_failed):
    """构造单条消息的操作按钮。

    - 重复(is_dup): 只给 🔥 强制重下 (覆盖库中已存在记录)
    - 成功/失败:    ♻️ 重新下载 + 🗑️ 删除本次内容
    """
    if is_dup:
        rows = [[InlineKeyboardButton("🔥 强制重下", callback_data=f"sg_force:{single_key}")]]
    else:
        rows = [[
            InlineKeyboardButton("♻️ 重新下载", callback_data=f"sg_redownload:{single_key}"),
            InlineKeyboardButton("🗑️ 删除本次内容", callback_data=f"sg_delete:{single_key}"),
        ]]
    return InlineKeyboardMarkup(rows)


def build_single_record(media_obj, media_type, date_dir, source_info, ext_for_large,
                        chat, message, final_filename=None):
    """构造一条可脱离原始 update 复用的单张下载记录。"""
    return {
        'file_id': media_obj.file_id,
        'file_unique_id': media_obj.file_unique_id,
        'media_type': media_type,
        'date_dir': date_dir,
        'ext_for_large': ext_for_large,
        'final_filename': final_filename,
        'caption': message.caption,
        'file_size': getattr(media_obj, 'file_size', 0) or 0,
        'source_name': source_info['source_name'],
        'source_id': source_info['source_id'],
        'source_link1': source_info['source_link1'],
        'source_link2': source_info['source_link2'],
        'source_username': source_info['source_username'],
        'source_type': source_info['source_type'],
        'orig_chat_id': source_info['orig_chat_id'],
        'orig_msg_id': source_info['orig_msg_id'],
        'chat_id': chat.id,
        'chat_type': chat.type,
        'message_id': get_message_id(message),
        'user_id': message.from_user.id if message.from_user else None,
        'user_name': (message.from_user.username or message.from_user.first_name) if message.from_user else None,
        'message_time': utc_to_local(get_message_date(message)).isoformat() if message and message.date else None,
    }


async def reply_duplicate(update, media_obj, media_type, caption):
    """检测重复资源，若重复则回复完整提示（带强制重下按钮）并返回 True。"""
    dup_info = get_duplicate_info(media_obj.file_unique_id)
    if not dup_info:
        return False

    label = MEDIA_LABELS.get(media_type, '资源')
    source_display = dup_info.get('source_name') or '未知'
    if dup_info.get('source_link1'):
        source_display = f"[{dup_info['source_name']}]({dup_info['source_link1']})"

    reply_msg = (
        f"♻️ 检测到重复资源 ({label})\n\n"
        f"文件已存在: `{dup_info['filename']}`\n"
        f"最初来源: {source_display}\n"
        f"最初描述: {dup_info.get('caption') or '无'}\n"
        f"当前描述: {caption or '无'}"
    )
    return reply_msg


def _make_progress_callback(bot, loop, chat_id, status_message_id, prefix, header=None):
    """生成下载进度回调 (Pyrogram 签名: current, total)。

    回调在 Pyrogram 的事件循环线程里被调用，这里通过 run_coroutine_threadsafe
    把消息编辑调度回 PTB 的主事件循环（bot.edit_message_text 是协程）。
    带节流：百分比变化且至少间隔 2 秒才更新，100% 强制更新。
    header 可选，若提供则显示在进度文本上方。
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
                text = f"{prefix}\n进度: {percent}%"
                if header:
                    text = f"{header}\n\n{text}"
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text=text,
                )
            except Exception:
                pass
        try:
            asyncio.run_coroutine_threadsafe(_edit(), loop)
        except Exception:
            pass

    return callback


def _stub_user(record):
    """从 record 重建一个供 save_to_db 使用的轻量 user 对象。"""
    return type('User', (), {
        'id': record.get('user_id'),
        'username': record.get('user_name'),
        'first_name': record.get('user_name'),
    })


async def download_large_from_record(bot, record, status_chat_id, status_message_id, header=None):
    """基于 record 通过 User API 下载大文件（用于按钮重下，脱离原始 update）。

    返回最终文件名或 None。
    """
    media_type = record['media_type']
    date_dir = record['date_dir']
    label = MEDIA_LABELS.get(media_type, '文件')
    loop = asyncio.get_running_loop()

    temp_filename = generate_temp_filename()
    final_filename = f"{temp_filename}{record['ext_for_large']}"
    final_path = os.path.join(date_dir, final_filename)

    progress = _make_progress_callback(
        bot, loop, status_chat_id, status_message_id,
        prefix=f"⏳ 正在通过 User API 下载大{label}...",
        header=header,
    )

    link_chat_id = record.get('link_chat_id')
    link_msg_id = record.get('link_message_id')
    orig_chat_id = record.get('orig_chat_id')
    orig_msg_id = record.get('orig_msg_id')
    chat_id = record['chat_id']
    chat_type = record.get('chat_type')
    source_type = record.get('source_type')

    target_chat_id = link_chat_id or orig_chat_id or chat_id
    target_msg_id = link_msg_id or orig_msg_id or record['message_id']
    if not link_chat_id and not orig_chat_id and (chat_type == 'private' or source_type in ["user", "private_user"]):
        target_chat_id = bot.username or bot.id

    file_unique_id = record['file_unique_id']
    if link_chat_id:
        success = await loop.run_in_executor(
            None,
            lambda: user_api.run_download_message_media(
                target_chat_id, target_msg_id, final_path,
                progress_callback=progress,
            ),
        )
    else:
        success = await loop.run_in_executor(
            None,
            lambda: user_api.run_download_large_file(
                target_chat_id, target_msg_id, final_path,
                progress_callback=progress, file_unique_id=file_unique_id,
            ),
        )
    if not success and not link_chat_id and target_chat_id != chat_id:
        logger.warning(f"大{label}溯源重下失败，尝试从本地聊天回退下载...")
        fallback_chat_id = chat_id
        if chat_type == 'private' or source_type in ["user", "private_user"]:
            fallback_chat_id = bot.username or bot.id
        success = await loop.run_in_executor(
            None,
            lambda: user_api.run_download_large_file(
                fallback_chat_id, record['message_id'], final_path,
                progress_callback=progress, file_unique_id=file_unique_id,
            ),
        )
    if not success:
        return None

    media_obj_stub = type('Media', (), {'file_id': record['file_id'], 'file_unique_id': file_unique_id})
    save_to_db(
        _stub_user(record), media_obj_stub, final_filename,
        save_dir=date_dir, media_type=media_type, caption=record.get('caption'),
        source_name=record.get('source_name'), source_id=record.get('source_id'),
        source_link1=record.get('source_link1'),
        source_link2=record.get('source_link2'),
        source_username=record.get('source_username'),
        source_type=source_type,
        message_time=record.get('message_time'),
        message_id=record.get('link_message_id'),
    )
    record['final_filename'] = final_filename
    return final_filename


async def download_small_from_record(bot, record):
    """基于 record 通过 Bot API 重新下载小文件。返回最终文件名或 None。"""
    media_type = record['media_type']
    date_dir = record['date_dir']
    temp_filename = generate_temp_filename()
    temp_path = os.path.join(date_dir, f"{temp_filename}_temp")
    try:
        tg_file = await bot.get_file(record['file_id'])
        await tg_file.download_to_drive(temp_path)

        if media_type == 'video':
            ext = get_video_extension(temp_path)
        else:
            ext = get_image_extension(temp_path)
        final_filename = f"{temp_filename}{ext}"
        final_path = os.path.join(date_dir, final_filename)
        os.rename(temp_path, final_path)

        media_obj_stub = type('Media', (), {'file_id': record['file_id'], 'file_unique_id': record['file_unique_id']})
        save_to_db(
            _stub_user(record), media_obj_stub, final_filename,
            save_dir=date_dir, media_type=media_type, caption=record.get('caption'),
            source_name=record.get('source_name'), source_id=record.get('source_id'),
            source_link1=record.get('source_link1'),
            source_link2=record.get('source_link2'),
            source_username=record.get('source_username'),
            source_type=record.get('source_type'),
            message_time=record.get('message_time'),
            message_id=record.get('link_message_id'),
        )
        record['final_filename'] = final_filename
        return final_filename
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        logger.error(f"{MEDIA_LABELS.get(media_type, '文件')}重新下载失败: {e}")
        return None


async def download_large_via_user_api(update, context, media_obj, media_type, date_dir,
                                      ext, source_info, status_message, header=None):
    """通过 User API 下载大文件（含进度、溯源、回退、存库）。返回最终文件名或 None。

    User API 调用是阻塞的，放到默认线程池执行，避免阻塞 PTB 事件循环。
    """
    message_time = utc_to_local(get_message_date(update.message)).isoformat() if update.message and update.message.date else None

    temp_filename = generate_temp_filename()
    final_filename = f"{temp_filename}{ext}"
    final_path = os.path.join(date_dir, final_filename)

    chat = update.effective_chat
    label = MEDIA_LABELS.get(media_type, '文件')
    loop = asyncio.get_running_loop()

    progress = _make_progress_callback(
        context.bot, loop, chat.id, status_message.message_id,
        prefix=f"⏳ 正在通过 User API 下载大{label}...",
        header=header,
    ) if status_message else None

    # 溯源：优先用原始频道/消息 ID
    target_chat_id = source_info['orig_chat_id'] or chat.id
    target_msg_id = source_info['orig_msg_id'] or update.message.message_id
    if not source_info['orig_chat_id'] and (chat.type == 'private' or source_info['source_type'] in ["user", "private_user"]):
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
        if chat.type == 'private' or source_info['source_type'] in ["user", "private_user"]:
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
        source_name=source_info['source_name'], source_id=source_info['source_id'],
        source_link1=source_info['source_link1'], source_link2=source_info['source_link2'],
        source_username=source_info['source_username'], source_type=source_info['source_type'],
        message_time=message_time,
        message_id=get_message_id(update.message),
    )
    return final_filename


async def save_small_file(update, media_obj, media_type, date_dir, source_info, detect_ext):
    """通过 Bot API 下载小文件并存库。返回最终文件名或 None。

    v21 中 get_file() 与 file.download_to_drive() 均为协程。
    detect_ext 与 save_to_db 是同步的轻量操作，直接调用即可。
    """
    message_time = utc_to_local(get_message_date(update.message)).isoformat() if update.message and update.message.date else None

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
            source_name=source_info['source_name'], source_id=source_info['source_id'],
            source_link1=source_info['source_link1'], source_link2=source_info['source_link2'],
            source_username=source_info['source_username'], source_type=source_info['source_type'],
            message_time=message_time,
            message_id=get_message_id(update.message),
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


def get_archive_ext(file_path):
    """通过文件头检测压缩包/文档类型，返回扩展名。"""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(8)
        if header[:2] == b'PK':
            return '.zip'
        if header[:4] == b'Rar!':
            return '.rar'
        if header[:6] == b'7z\xbc\xaf\x27\x1c':
            return '.7z'
        if header[:2] == b'\x1f\x8b':
            return '.gz'
        if header[:5] == b'\xfd7zXZ':
            return '.xz'
        if header[:4] == b'\x25\x50\x44\x46':
            return '.pdf'
        if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            return '.doc'  # OLE2 format (doc/xls/ppt)
        return None
    except Exception:
        return None
