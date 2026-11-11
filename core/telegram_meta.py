"""Telegram 消息元数据与链接工具。"""

from datetime import timezone


def get_message_date(message):
    """从 PTB Message 对象获取原始消息时间（转发消息使用原消息时间）"""
    if message.forward_origin and message.forward_origin.date:
        return message.forward_origin.date
    return message.date


def get_message_id(message):
    """从 PTB Message 对象获取原始转发消息 ID；非转发消息返回 None。"""
    if message.forward_origin:
        return getattr(message.forward_origin, 'message_id', None)
    return None


def telegram_internal_chat_id(chat_id):
    """将 Telegram 频道/超级群内部 ID 转成 t.me/c 链接使用的正数 ID。"""
    try:
        raw = int(chat_id)
    except (TypeError, ValueError):
        return None
    text = str(abs(raw))
    if text.startswith('100') and len(text) > 3:
        text = text[3:]
    return text or None


def build_private_message_link(chat_id, message_id=None):
    """构造私有频道或超级群的 t.me/c 链接。"""
    internal_id = telegram_internal_chat_id(chat_id)
    if not internal_id:
        return ''
    base = f"https://t.me/c/{internal_id}"
    return f"{base}/{message_id}" if message_id is not None else base


def utc_to_local(dt):
    """将 naive UTC datetime 转为本地 naive datetime"""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
