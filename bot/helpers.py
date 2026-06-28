"""通用辅助函数：访问控制装饰器、转发溯源、带重试下载。"""

import time
import functools

from config import logger, ALLOWED_USERS, ENABLE_USER_RESTRICTION, GITHUB_REPO
from bot import state


def is_user_allowed(update) -> bool:
    """检查用户是否被允许使用机器人"""
    if not ENABLE_USER_RESTRICTION:
        return True

    user = update.effective_user
    if not user:
        return False

    username = user.username
    user_id = str(user.id)

    is_allowed = (username in ALLOWED_USERS) or (user_id in ALLOWED_USERS)

    if not is_allowed:
        logger.warning(f"用户验证失败: {username} (ID: {user_id}) 尝试使用机器人")

    return is_allowed


def restricted(func):
    """装饰器：仅允许特定用户访问 (适配 async handler)"""
    @functools.wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        if not is_user_allowed(update):
            user_id = update.effective_user.id
            current_time = time.time()

            # 检查是否在冷却时间内已经提示过
            if current_time - state.user_notification_cache.get(user_id, 0) > state.NOTIFICATION_COOLDOWN:
                unauthorized_message = (
                    f"⛔ 访问受限\n\n"
                    f"此机器人是私有实例，仅供特定用户使用。媒体文件将被下载到部署服务器的本地存储中，而不是转发给其他用户。\n\n"
                    f"由于这是一个私人存储工具，只有授权用户才能使用此功能。\n\n"
                    f"您可以在GitHub上部署自己的TeleGrabber实例：\n"
                    f"{GITHUB_REPO}"
                )
                await update.message.reply_text(unauthorized_message)
                state.user_notification_cache[user_id] = current_time
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


def get_forward_source_info(message):
    """获取转发来源的详细信息

    Returns:
        tuple: (source, source_id, source_link, source_type, orig_chat_id, orig_msg_id)
    """
    import re

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

        if chat.type == "channel":
            source_type = "channel"
        elif chat.type == "supergroup" or chat.type == "group":
            source_type = "group"

        if chat.username:
            source_link = f"https://t.me/{chat.username}"
        else:
            source_link = f"https://t.me/c/{str(chat.id).replace('-100', '')}"

    elif message.forward_from:
        # 如果是从个人用户转发（用户隐私设置允许的情况下）
        user_from = message.forward_from
        source_id = str(user_from.id)
        orig_chat_id = user_from.id
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
