"""单条消息处理器：照片、视频、文档(图片)、GIF动画。

下载相关的公共逻辑（去重提示、大文件 User API 下载、小文件 Bot API 下载）
统一放在 bot/download.py，这里只负责各媒体类型的差异处理与用户交互。
"""

import os

from config import logger, USER_API_ENABLED
from utils import get_save_directory, get_image_extension, get_video_extension
from bot.helpers import restricted, get_forward_source_info
from bot.media_group import (
    add_photo_to_collection, add_video_to_collection,
    schedule_media_group_processing,
)
from bot.download import (
    LARGE_FILE_THRESHOLD, MEDIA_LABELS,
    reply_duplicate, download_large_via_user_api, save_small_file,
)


@restricted
def start(update, context) -> None:
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
    update.message.reply_text(welcome_message)


@restricted
def help_command(update, context) -> None:
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
        f"• 支持断网重连和代理设置\n"
    )
    update.message.reply_text(help_message)


def _reply(update, text):
    """统一回复到原消息，便于刷屏时对应。"""
    return update.message.reply_text(text, reply_to_message_id=update.message.message_id)


def _handle_single_media(update, context, media_obj, media_type, ext_for_large, detect_ext):
    """处理单条媒体（非媒体组）的通用流程：去重 -> 大文件 / 小文件。

    ext_for_large: 大文件走 User API 时使用的固定扩展名
    detect_ext: 小文件下载后用于检测扩展名的回调 (temp_path -> ext)
    """
    message = update.message
    source_info = get_forward_source_info(message)
    source_type = source_info[3]
    date_dir = get_save_directory(update.effective_user, source_info[0], source_type)
    label = MEDIA_LABELS.get(media_type, '文件')

    # 1. 去重检查（统一完整提示）
    if reply_duplicate(update, media_obj, media_type, message.caption):
        return

    file_size = getattr(media_obj, 'file_size', 0) or 0

    # 2. 大文件走 User API（带进度）
    if USER_API_ENABLED and file_size >= LARGE_FILE_THRESHOLD:
        status_message = _reply(update, f"⏳ 检测到大{label} ({file_size/1024/1024:.1f}MB)，正在通过 User API 下载...")
        final_filename = download_large_via_user_api(
            update, context, media_obj, media_type, date_dir,
            ext_for_large, source_info, status_message,
        )
        if final_filename:
            _edit_or_reply(context, update, status_message, f"✅ 大{label}已保存: {final_filename}")
        else:
            _edit_or_reply(context, update, status_message, f"❌ 大{label}通过 User API 下载失败")
        return

    # 3. 小文件走 Bot API（先发处理中提示，完成后编辑为结果）
    status_message = _reply(update, f"⏳ 正在保存{label}...")
    final_filename = save_small_file(update, media_obj, media_type, date_dir, source_info, detect_ext)
    if final_filename:
        _edit_or_reply(context, update, status_message, f"✅ {label}已保存")
    else:
        _edit_or_reply(context, update, status_message, f"❌ {label}保存失败")


def _edit_or_reply(context, update, status_message, text):
    """优先编辑已有状态消息；编辑失败则退化为新回复。"""
    if status_message:
        try:
            context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=status_message.message_id,
                text=text,
            )
            return
        except Exception:
            pass
    _reply(update, text)


@restricted
def process_photo(update, context) -> None:
    """处理所有照片，包括单张和媒体组中的照片"""
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id
    media_group_id = message.media_group_id

    if not media_group_id:
        photo = message.photo[-1]
        _handle_single_media(
            update, context, photo, 'photo',
            ext_for_large='.jpg', detect_ext=get_image_extension,
        )
        return

    # 媒体组处理
    photo = message.photo[-1]
    _, is_first_media = add_photo_to_collection(media_group_id, chat_id, user, photo, context, message)
    if is_first_media:
        schedule_media_group_processing(context, media_group_id, chat_id)


@restricted
def process_video(update, context) -> None:
    """处理所有视频，包括单个和媒体组中的视频"""
    message = update.message
    user = update.effective_user
    chat_id = update.effective_chat.id
    media_group_id = message.media_group_id

    if not media_group_id:
        _handle_single_media(
            update, context, message.video, 'video',
            ext_for_large='.mp4', detect_ext=get_video_extension,
        )
        return

    # 媒体组处理
    video = message.video
    _, is_first_media = add_video_to_collection(media_group_id, chat_id, user, video, context, message)
    if is_first_media:
        schedule_media_group_processing(context, media_group_id, chat_id)


@restricted
def download_document(update, context) -> None:
    """下载用户发送的文件（针对图片文件）"""
    message = update.message
    document = message.document

    mime_type = document.mime_type
    if not mime_type or not mime_type.startswith('image/'):
        update.message.reply_text("❌ 只支持图片文件", reply_to_message_id=message.message_id)
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

    _handle_single_media(
        update, context, document, 'document',
        ext_for_large=large_ext, detect_ext=detect_ext,
    )


@restricted
def process_animation(update, context) -> None:
    """处理GIF动画"""
    message = update.message
    animation = message.animation

    # 大文件扩展名按 mime 判断
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

    _handle_single_media(
        update, context, animation, 'animation',
        ext_for_large=large_ext, detect_ext=detect_ext,
    )
