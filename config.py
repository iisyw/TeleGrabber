#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging

from config_loader import ConfigError, load_config

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def mask_proxy_url(url):
    """隐藏代理 URL 中的用户名/密码，避免明文写入日志"""
    if not url:
        return url
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.password or parsed.username:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc += f":{parsed.port}"
            return f"{parsed.scheme}://***:***@{netloc}"
        return url
    except Exception:
        return "***"


# 降低APScheduler的日志级别，减少输出
logging.getLogger('apscheduler').setLevel(logging.WARNING)
# 针对 Pyrogram 内部一些会自动记录但我们已经通过重试机制处理的错误，降低其日志级别
logging.getLogger('pyrogram').setLevel(logging.WARNING)
# 压制 httpx 轮询日志（getUpdates 每 1-2 秒一条，太吵）
logging.getLogger('httpx').setLevel(logging.WARNING)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get(
    "TELEGRABBER_CONFIG", os.path.join(BASE_DIR, "conf", "config.toml")
)

if not os.path.exists(CONFIG_PATH):
    logger.warning(
        "未找到配置文件 %s，使用默认配置。"
        "请复制 conf/config.example.toml 为 conf/config.toml 并填写。",
        CONFIG_PATH,
    )

try:
    _config = load_config(CONFIG_PATH)
except ConfigError as exc:
    logger.error("配置加载失败: %s", exc)
    raise

if os.path.exists(CONFIG_PATH):
    logger.info("从 %s 加载配置", CONFIG_PATH)

_telegram = _config["telegram"]
_storage = _config["storage"]
_web = _config["web"]
_tasks = _config["tasks"]
_audit = _config["audit"]

# Telegram 机器人配置
TOKEN = _telegram["bot_token"] or None
BOT_ID = int(TOKEN.split(':')[0]) if TOKEN and ':' in TOKEN else None

# 存储目录
SAVE_DIR = _storage["save_dir"]
DATA_DIR = _storage["data_dir"]

# 连接与下载
PROXY = _telegram["proxy_url"] or None
TIMEOUT = _telegram["connection_timeout"]
DOWNLOAD_RETRIES = _telegram["download_retries"]
DOWNLOAD_TIMEOUT = _telegram["download_timeout"]
DOWNLOAD_STALL_TIMEOUT = _telegram["download_stall_timeout"]

# Web 管理后台
WEB_HOST = _web["host"]
WEB_PORT = _web["port"]

# 任务中心
TASK_RETAIN_DAYS = _tasks["retain_days"]
TASK_RETRY_CONCURRENCY = _tasks["retry_concurrency"]
TASK_MIN_FREE_MB = _tasks["min_free_mb"]

# 用户访问限制
ALLOWED_USERS = _telegram["allowed_users"]
ENABLE_USER_RESTRICTION = bool(ALLOWED_USERS)

# Telegram API (MTProto)
API_ID = _telegram["api_id"] or None
API_HASH = _telegram["api_hash"] or None
USER_API_ENABLED = bool(API_ID and API_HASH)

if USER_API_ENABLED:
    logger.info("User API (MTProto) 已配置，支持大文件下载 (>20MB)")
else:
    logger.warning("User API (MTProto) 未配置，无法下载超过 20MB 的文件")

# 通用文件下载白名单
ALLOWED_FILE_EXTENSIONS = _telegram["allowed_file_extensions"]

# 审计日志
AUDIT_LOG = _audit["enabled"]

# GitHub 仓库地址
GITHUB_REPO = "https://github.com/iisyw/TeleGrabber"

# 确保目录存在
for _dir in (DATA_DIR, SAVE_DIR):
    if not os.path.exists(_dir):
        os.makedirs(_dir)
        logger.info("已创建目录: %s", _dir)


def get_connection_args():
    """获取连接参数 (适配 python-telegram-bot v21 的 ApplicationBuilder)。

    返回一个 dict，键对应 ApplicationBuilder 的方法名，main.py 据此链式配置。
    """
    args = {
        'connect_timeout': TIMEOUT,
        'read_timeout': TIMEOUT,
    }
    if PROXY:
        # v21 用 httpx，代理通过 proxy=/get_updates_proxy= 传入
        args['proxy'] = PROXY
        args['get_updates_proxy'] = PROXY
        logger.info("使用代理: %s", mask_proxy_url(PROXY))
    return args
