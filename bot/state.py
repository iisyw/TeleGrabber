"""bot 模块的全局可变状态与运行时常量。

集中管理机器人逻辑中分散的模块级状态，便于各子模块共享。
"""

import os
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from core.config import DATA_DIR

# 媒体组收集状态文件（存储于运行数据目录）
MEDIA_GROUP_COLLECTION_FILE = os.path.join(DATA_DIR, "media_groups_collection.json")
# 媒体组收集等待时间（秒）
MEDIA_GROUP_COLLECT_TIME = 2

# 存储最近提示过的用户，格式为 {user_id: last_notification_time}
user_notification_cache = defaultdict(int)
# 设置提示冷却时间（秒）
NOTIFICATION_COOLDOWN = 60

# 添加全局可重入锁，确保同一时间只处理一个媒体组且允许同线程安全嵌套调用
media_group_lock = threading.RLock()
# 添加待处理媒体组队列
pending_media_groups = deque()
# 标记是否有正在处理的媒体组
is_processing_media_group = False

# --- 内存缓存优化 ---
# 在内存中存储当前正在收集的媒体组，减少磁盘 I/O
# 格式: {collection_key: group_info_dict}
active_collections = {}
# 存储已完成处理的媒体组历史，用于支持"重新下载"、"重试失败项目"功能
# 格式: {collection_key: processed_info_dict}
processed_groups_history = {}
# 下载执行器：限制为 5 个并发，既能保证速度也能避免触发 Telegram 限制或代理过载
download_executor = ThreadPoolExecutor(max_workers=5)
# 用于防止同一媒体组内多个相同文件同时保存导致的查重冲突
saving_unique_ids = set()
saving_lock = threading.RLock()

# --- 单条消息下载记录 ---
# 支持单张消息的"重新下载/强制重下/删除"按钮回调。
# 格式: {single_key: record_dict}，record 含 file_id/file_unique_id/media_type/
#       date_dir/final_filename/caption/source.../chat_id/message_id/file_size/is_dup
single_records = {}
single_lock = threading.RLock()
# 历史上限，防止内存无限增长（保留最近 N 条）
SINGLE_RECORDS_LIMIT = 200


def put_single_record(key, record):
    """登记一条单张下载记录，超出上限时淘汰最旧的。"""
    with single_lock:
        single_records[key] = record
        while len(single_records) > SINGLE_RECORDS_LIMIT:
            oldest = next(iter(single_records))
            del single_records[oldest]


def get_single_record(key):
    with single_lock:
        return single_records.get(key)


def drop_single_record(key):
    with single_lock:
        single_records.pop(key, None)


# --- 链接抓取待匹配队列 (Pending Link Registry) ---
# 记录通过链接指令触发转发的消息元信息，用于匹配识别自动转存消息。
pending_link_forwards = {}
pending_link_lock = threading.RLock()
PENDING_LINKS_LIMIT = 100


def register_link_forward(mid, ref_text, chat_id=None, username=None, status_chat_id=None, status_msg_id=None):
    """登记一条通过链接指令触发转发的消息元信息。"""
    import time
    with pending_link_lock:
        now = time.time()
        # 清理 5 分钟前的过期条目
        expired = [k for k, v in pending_link_forwards.items() if now - v.get('time', now) > 300]
        for k in expired:
            del pending_link_forwards[k]

        key = int(mid)
        pending_link_forwards[key] = {
            'url': ref_text,
            'chat_id': str(chat_id) if chat_id is not None else None,
            'username': username.lower() if username else None,
            'status_chat_id': status_chat_id,
            'status_msg_id': status_msg_id,
            'time': now,
        }
        while len(pending_link_forwards) > PENDING_LINKS_LIMIT:
            oldest = next(iter(pending_link_forwards))
            del pending_link_forwards[oldest]


def match_link_forward(orig_chat_id, orig_msg_id, orig_username=None):
    """匹配并消耗一条挂起的链接转发记录。"""
    with pending_link_lock:
        if orig_msg_id is None:
            return None
        key = int(orig_msg_id)
        if key in pending_link_forwards:
            info = pending_link_forwards.get(key)
            target_cid = info.get('chat_id')
            target_user = info.get('username')
            # 若双方都有明确的 chat_id 或 username，验证一致性避免误匹配
            if target_cid and orig_chat_id and str(target_cid) != str(orig_chat_id):
                if not (target_user and orig_username and target_user == orig_username.lower()):
                    return None
            return pending_link_forwards.pop(key)
        return None




