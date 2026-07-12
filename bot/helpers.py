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
    """获取转发来源的详细信息 (适配 Bot API 7.0 / PTB v21 的 forward_origin)。

    Bot API 7.0 将旧的 forward_from / forward_from_chat / forward_sender_name
    等字段统一为 message.forward_origin，类型为以下之一：
      - MessageOriginChannel    (.chat, .message_id)
      - MessageOriginChat       (.sender_chat)
      - MessageOriginUser       (.sender_user)
      - MessageOriginHiddenUser (.sender_user_name)

    Returns:
        tuple: (source_name, source_id, source_link, source_type, orig_chat_id, orig_msg_id)
    """
    import re

    source_name = None
    source_id = None
    source_link = None
    source_type = "unknown"
    orig_chat_id = None
    orig_msg_id = None

    origin = getattr(message, 'forward_origin', None)
    origin_type = getattr(origin, 'type', None) if origin else None

    if origin_type == "channel":
        chat = origin.chat
        source_name = chat.title or f"chat_{chat.id}"
        source_id = str(chat.id)
        source_type = "channel"
        orig_chat_id = chat.id
        orig_msg_id = getattr(origin, 'message_id', None)
        if chat.username:
            source_link = f"https://t.me/{chat.username}/{orig_msg_id}"
        else:
            source_link = f"https://t.me/c/{str(chat.id).replace('-100', '')}/{orig_msg_id}"

    elif origin_type == "chat":
        chat = origin.sender_chat
        source_name = chat.title or f"chat_{chat.id}"
        source_id = str(chat.id)
        source_type = "group"
        orig_chat_id = chat.id
        if chat.username:
            source_link = f"https://t.me/{chat.username}"
        else:
            source_link = f"https://t.me/c/{str(chat.id).replace('-100', '')}"

    elif origin_type == "user":
        user_from = origin.sender_user
        source_id = str(user_from.id)
        orig_chat_id = user_from.id
        is_bot = getattr(user_from, 'is_bot', False)
        if is_bot:
            source_type = "bot"
            source_name = user_from.first_name or f"bot_{user_from.id}"
        else:
            source_type = "private_user"
            source_name = user_from.username or user_from.first_name or f"user_{user_from.id}"
        if user_from.username:
            source_link = f"https://t.me/{user_from.username}"

    elif origin_type == "hidden_user":
        source_name = getattr(origin, 'sender_user_name', None) or "hidden_user"
        source_id = "unknown"
        source_link = ""
        source_type = "private_user"

    if source_name:
        source_name = re.sub(r'[\\/*?:"<>|]', "_", source_name)

    return source_name, source_id, source_link, source_type, orig_chat_id, orig_msg_id
