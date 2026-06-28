"""bot 模块的全局可变状态与运行时常量。

集中管理机器人逻辑中分散的模块级状态，便于各子模块共享。
"""

import os
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from config import SAVE_DIR

# 媒体组状态文件
MEDIA_GROUP_STATE_FILE = os.path.join(SAVE_DIR, "media_groups_state.json")
# 媒体组收集状态文件
MEDIA_GROUP_COLLECTION_FILE = os.path.join(SAVE_DIR, "media_groups_collection.json")
# 媒体组收集等待时间（秒）
MEDIA_GROUP_COLLECT_TIME = 2

# 存储最近提示过的用户，格式为 {user_id: last_notification_time}
user_notification_cache = defaultdict(int)
# 设置提示冷却时间（秒）
NOTIFICATION_COOLDOWN = 60

# 添加全局锁，确保同一时间只处理一个媒体组
media_group_lock = threading.Lock()
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
saving_lock = threading.Lock()
