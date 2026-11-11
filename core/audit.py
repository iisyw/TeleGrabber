"""可选审计日志：把收到的消息源信息和原始数据写入 data/audit_*.json。"""

import os
import json
import threading
import logging
from datetime import datetime

from .config import DATA_DIR, AUDIT_LOG

logger = logging.getLogger(__name__)

AUDIT_DIR = DATA_DIR
_audit_lock = threading.Lock()

_source_type_labels = {
    'channel': '频道',
    'bot': '机器人',
    'group': '群组',
    'private': '用户',
    'other': '其他',
}


def _audit_source_type(entry):
    st = entry.get('source_type')
    if st in ('channel', 'bot', 'group'):
        return st
    if st in ('user', 'private', 'private_user'):
        return 'private'

    raw = entry.get('raw')
    if isinstance(raw, dict):
        fo = raw.get('forward_origin') or {}
        fo_type = fo.get('type')
        if fo_type == 'channel':
            return 'channel'
        if fo_type in ('chat', 'supergroup'):
            return 'group'
        if fo_type == 'hidden_user':
            return 'private'
        if fo_type == 'user':
            sender = fo.get('sender_user') or {}
            return 'bot' if sender.get('is_bot') else 'private'

        chat_type = raw.get('chat', {}).get('type')
        if chat_type == 'channel':
            return 'channel'
        if chat_type in ('supergroup', 'group'):
            return 'group'
        if chat_type == 'private':
            from_user = raw.get('from_user') or {}
            return 'bot' if from_user.get('is_bot') else 'private'
        if chat_type == 'bot':
            return 'bot'

    return 'other'


def _audit_path(source_type):
    return os.path.join(AUDIT_DIR, f'audit_{source_type}.json')


def append_audit(msg_type, message=None, group_info=None, raw_dict=None, note=None):
    """记录收到的消息到审计日志，便于分析消息来源和模式。"""
    if not AUDIT_LOG:
        return

    entry = {
        'time': datetime.now().isoformat(),
        'type': msg_type,
    }

    if message is not None:
        try:
            if hasattr(message, 'to_dict'):
                entry['raw'] = message.to_dict()
            elif isinstance(message, dict):
                entry['raw'] = message
        except Exception:
            pass

        try:
            if hasattr(message, 'chat') and message.chat:
                entry['chat_id'] = message.chat.id
                entry['chat_type'] = message.chat.type
            if hasattr(message, 'from_user') and message.from_user:
                entry['user_id'] = message.from_user.id
            if hasattr(message, 'caption') and message.caption:
                entry['caption'] = message.caption[:500]
            if hasattr(message, 'media_group_id') and message.media_group_id:
                entry['media_group_id'] = message.media_group_id
            fo = getattr(message, 'forward_origin', None)
            if fo:
                msg_id = getattr(fo, 'message_id', None) or getattr(message, 'message_id', None)
                msg_date = getattr(fo, 'date', None)
            else:
                msg_id = message.message_id
                msg_date = getattr(message, 'date', None)
            if msg_id is not None:
                entry['message_id'] = msg_id
            if msg_date is not None:
                try:
                    entry['message_time'] = msg_date.isoformat() if hasattr(msg_date, 'isoformat') else str(msg_date)
                except Exception:
                    pass
        except Exception:
            pass

    if group_info is not None:
        try:
            entry['chat_id'] = group_info.get('chat_id')
            entry['media_group_id'] = group_info.get('media_group_id')
            entry['user_id'] = group_info.get('user_id')
            entry['source_name'] = group_info.get('source_name')
            entry['source_link1'] = group_info.get('source_link1')
            entry['source_type'] = group_info.get('source_type')
            entry['caption'] = (group_info.get('caption') or '')[:500]
            entry['chat_type'] = group_info.get('chat_type')
            items = group_info.get('media_items', [])
            entry['item_count'] = len(items)
            entry['item_types'] = [m.get('media_type') for m in items]
            if items:
                first = items[0]
                if first.get('message_date'):
                    entry['message_time'] = first['message_date']
                elif first.get('message_time'):
                    entry['message_time'] = first['message_time']
                if first.get('message_id') is not None:
                    entry['message_id'] = first['message_id']
            raw_msg = group_info.get('raw_message')
            if isinstance(raw_msg, dict):
                entry['raw'] = raw_msg
            else:
                entry['raw'] = {k: v for k, v in group_info.items() if k != 'raw_message'}
        except Exception:
            pass

    if raw_dict is not None:
        entry['raw'] = raw_dict

    if note:
        entry['note'] = note

    try:
        st = _audit_source_type(entry)
        entry['source_type'] = st
        path = _audit_path(st)
        with _audit_lock:
            entries = []
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                    if isinstance(existing, list):
                        entries = existing
                except Exception:
                    entries = []
            entries.append(entry)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"写入审计日志失败: {e}")
