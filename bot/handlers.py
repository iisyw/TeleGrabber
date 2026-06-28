"""单条消息处理器：照片、视频、文档(图片)、GIF动画 (python-telegram-bot v21, async)。

下载相关的公共逻辑（去重提示、大文件 User API 下载、小文件 Bot API 下载）
统一放在 bot/download.py，这里只负责各媒体类型的差异处理与用户交互。
"""

import os
import uuid

from config import logger, USER_API_ENABLED
from utils import get_image_extension, get_video_extension, get_save_directory, get_library_stats
from bot import state
from bot.helpers import restricted, get_forward_source_info
from bot.media_group import (
    add_photo_to_collection, add_video_to_collection,
    schedule_media_group_processing,
)
from bot.download import (
    LARGE_FILE_THRESHOLD, MEDIA_LABELS,
    reply_duplicate, download_large_via_user_api, save_small_file,
    build_single_record, _single_buttons,
)


@restricted
async def start(update, context) -> None:
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
        f"⚠️ 注意：超过 20MB 的文件会自动通过 User API 下载（需配置）。\n\n"
        f"发送 /help 查看更多帮助信息。"
    )
    await update.message.reply_text(welcome_message)


@restricted
async def help_command(update, context) -> None:
    """发送帮助信息"""
    help_message = (
        f"💡 TeleGrabber 使用指南:\n\n"
        f"直接发送以下内容给我，我会自动保存：\n"
        f"• 单张图片\n"
        f"• 单个视频\n"
        f"• GIF 动画\n"
        f"• 媒体组（相册）\n"
        f"• 图片文件\n\n"

        f"📁 文件保存路径：\n"
        f"• 媒体文件按来源自动分类存储（统一媒体库）\n"
        f"• 格式：downloads/来源名称/文件名\n\n"

        f"🔍 额外信息：\n"
        f"• 所有媒体元数据会保存到 SQLite 数据库中并记录用户信息\n"
        f"• 自动检测重复资源并跳过，节省磁盘空间\n"
        f"• 大文件下载时会显示实时进度\n"
        f"• 发送 /stats 查看媒体库统计\n"
        f"• 支持断网重连和代理设置\n"
    )
    await update.message.reply_text(help_message)


@restricted
async def stats_command(update, context) -> None:
    """/stats：显示媒体库统计概况。"""
    try:
        s = get_library_stats()
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        await update.message.reply_text("❌ 获取统计信息失败")
        return

    type_labels = {'photo': '图片', 'video': '视频', 'animation': '动画', 'document': '文档'}
    type_lines = "\n".join(
        f"  • {type_labels.get(t, t)}: {c}" for t, c in sorted(s['by_type'].items(), key=lambda x: -x[1])
    ) or "  • 暂无"
    source_lines = "\n".join(
        f"  {i+1}. {src} ({cnt})" for i, (src, cnt) in enumerate(s['top_sources'])
    ) or "  暂无"

    msg = (
        f"📊 **媒体库统计**\n\n"
        f"总数: {s['total']}\n"
        f"今日新增: {s['today']}\n\n"
        f"📁 按类型:\n{type_lines}\n\n"
        f"🔝 来源 Top5:\n{source_lines}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


@restricted
async def handle_unsupported(update, context) -> None:
    """兜底处理：收到不支持的消息类型时给出提示，避免机器人沉默。"""
    message = update.message
    if message is None:
        return
    await message.reply_text(
        "🤔 我只能保存图片、视频、GIF 动画和图片文档。\n请直接发送或转发这些媒体给我。",
        reply_to_message_id=message.message_id,
    )


async def _reply(update, text):
    """统一回复到原消息，便于刷屏时对应。返回发出的消息对象。"""
    return await update.message.reply_text(text, reply_to_message_id=update.message.message_id)


async def _edit_or_reply(context, update, status_message, text, reply_markup=None):
    """优先编辑已有状态消息；编辑失败则退化为新回复。"""
    if status_message:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=status_message.message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            pass
    await update.message.reply_text(
        text, reply_to_message_id=update.message.message_id, reply_markup=reply_markup,
    )


async def _handle_single_media(update, context, media_obj, media_type, ext_for_large, detect_ext):
    """处理单条媒体（非媒体组）的通用流程：去重 -> 大文件 / 小文件。

    完成后附带操作按钮，并登记 single_record 供按钮回调使用。
    """
    message = update.message
    source_info = get_forward_source_info(message)
    source_type = source_info[3]
    date_dir = get_save_directory(update.effective_user, source_info[0], source_type)
    label = MEDIA_LABELS.get(media_type, '文件')
    chat = update.effective_chat

    single_key = uuid.uuid4().hex[:12]

    # 1. 去重检查：重复则给"强制重下"按钮（覆盖库中已有记录）
    dup_text = await reply_duplicate(update, media_obj, media_type, message.caption)
    if dup_text:
        record = build_single_record(media_obj, media_type, date_dir, source_info, ext_for_large, chat, message)
        record['is_dup'] = True
        state.put_single_record(single_key, record)
        await update.message.reply_text(
            dup_text, parse_mode='Markdown', disable_web_page_preview=True,
            reply_to_message_id=message.message_id,
            reply_markup=_single_buttons(single_key, is_dup=True, has_failed=False),
        )
        return

    file_size = getattr(media_obj, 'file_size', 0) or 0

    # 2. 大文件走 User API（带进度）
    if USER_API_ENABLED and file_size >= LARGE_FILE_THRESHOLD:
        status_message = await _reply(update, f"⏳ 检测到大{label} ({file_size/1024/1024:.1f}MB)，正在通过 User API 下载...")
        final_filename = await download_large_via_user_api(
            update, context, media_obj, media_type, date_dir,
            ext_for_large, source_info, status_message,
        )
    else:
        # 3. 小文件走 Bot API
        status_message = await _reply(update, f"⏳ 正在保存{label}...")
        final_filename = await save_small_file(update, media_obj, media_type, date_dir, source_info, detect_ext)

    # 登记记录并附带按钮
    record = build_single_record(media_obj, media_type, date_dir, source_info, ext_for_large,
                                 chat, message, final_filename=final_filename)
    record['is_dup'] = False
    state.put_single_record(single_key, record)

    if final_filename:
        result_text = f"✅ {label}已保存"
    else:
        result_text = f"❌ {label}保存失败"
    await _edit_or_reply(
        context, update, status_message, result_text,
        reply_markup=_single_buttons(single_key, is_dup=False, has_failed=not final_filename),
    )


@restricted
async def process_photo(update, context) -> None:
    """处理所有照片，包括单张和媒体组中的照片"""
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id
    media_group_id = message.media_group_id

    if not media_group_id:
        photo = message.photo[-1]
        await _handle_single_media(
            update, context, photo, 'photo',
            ext_for_large='.jpg', detect_ext=get_image_extension,
        )
        return

    # 媒体组处理（收集需 await，因首条会发送状态消息）
    photo = message.photo[-1]
    _, is_first_media = await add_photo_to_collection(media_group_id, chat_id, user, photo, context, message)
    if is_first_media:
        schedule_media_group_processing(context, media_group_id, chat_id)


@restricted
async def process_video(update, context) -> None:
    """处理所有视频，包括单个和媒体组中的视频"""
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id
    media_group_id = message.media_group_id

    if not media_group_id:
        await _handle_single_media(
            update, context, message.video, 'video',
            ext_for_large='.mp4', detect_ext=get_video_extension,
        )
        return

    video = message.video
    _, is_first_media = await add_video_to_collection(media_group_id, chat_id, user, video, context, message)
    if is_first_media:
        schedule_media_group_processing(context, media_group_id, chat_id)


@restricted
async def download_document(update, context) -> None:
    """下载用户发送的文件（针对图片文件）"""
    message = update.message
    document = message.document

    mime_type = document.mime_type
    if not mime_type or not mime_type.startswith('image/'):
        await message.reply_text("❌ 只支持图片文件", reply_to_message_id=message.message_id)
        return

    # 大文件优先使用原始文件名的扩展名，小文件则按内容检测
    large_ext = '.jpg'
    if document.file_name and '.' in document.file_name:
        large_ext = os.path.splitext(document.file_name)[1].lower()

    def detect_ext(temp_path):
        if document.file_name and '.' in document.file_name:
            name_ext = os.path.splitext(document.file_name)[1].lower()
            detected = get_image_extension(temp_path)
            if name_ext.lower() != detected.lower():
                logger.warning(f"文件扩展名不匹配: 原始={name_ext}, 检测={detected}, 使用检测结果")
                return detected
            return name_ext
        return get_image_extension(temp_path)

    await _handle_single_media(
        update, context, document, 'document',
        ext_for_large=large_ext, detect_ext=detect_ext,
    )


@restricted
async def process_animation(update, context) -> None:
    """处理GIF动画"""
    message = update.message
    animation = message.animation

    large_ext = ".mp4" if animation.mime_type == 'video/mp4' else ".gif"

    def detect_ext(_temp_path):
        ext = '.gif'
        mime_type = getattr(animation, 'mime_type', None)
        if mime_type == 'video/mp4':
            ext = '.mp4'
        elif mime_type and '/' in mime_type:
            fmt = mime_type.split('/')[-1]
            if fmt:
                ext = f'.{fmt}'
        file_name = getattr(animation, 'file_name', '')
        if file_name and '.' in file_name:
            name_ext = os.path.splitext(file_name)[1].lower()
            if name_ext:
                ext = name_ext
        return ext

    await _handle_single_media(
        update, context, animation, 'animation',
        ext_for_large=large_ext, detect_ext=detect_ext,
    )
