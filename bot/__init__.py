"""bot 子包：聚合各 handler 与媒体组逻辑，供 main.py 注册。"""

from .handlers import (
    start,
    help_command,
    process_photo,
    process_video,
    download_document,
    process_animation,
)
from .callbacks import handle_callback_query
from .media_group import load_media_groups_collection

__all__ = [
    "start",
    "help_command",
    "process_photo",
    "process_video",
    "download_document",
    "process_animation",
    "handle_callback_query",
    "load_media_groups_collection",
]
