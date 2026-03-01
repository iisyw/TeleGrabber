#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging
from dotenv import load_dotenv

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 降低APScheduler的日志级别，减少输出
logging.getLogger('apscheduler').setLevel(logging.WARNING)
# 针对 Pyrogram 内部一些会自动记录但我们已经通过重试机制处理的错误，降低其日志级别
logging.getLogger('pyrogram').setLevel(logging.WARNING)

# 数据和配置目录
DATA_DIR = 'data'
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 加载环境变量
# 优先从 data/.env 加载，如果不存在则回退到根目录 .env (为了兼容性)
env_path = os.path.join(DATA_DIR, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
    logger.info(f"从 {env_path} 加载配置")
else:
    load_dotenv()

# Telegram机器人配置
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SAVE_DIR = os.getenv('SAVE_DIR', 'downloads')
PROXY = os.getenv('PROXY_URL')  # 可选的代理设置
TIMEOUT = int(os.getenv('CONNECTION_TIMEOUT', '30'))  # 连接超时设置，默认30秒
DOWNLOAD_RETRIES = int(os.getenv('DOWNLOAD_RETRIES', '3'))  # 下载失败重试次数，默认3次
WEB_PORT = int(os.getenv('WEB_PORT', '5000'))  # Web 管理后台端口，默认 5000

# 允许使用机器人的用户列表
# 格式为逗号分隔的用户名或用户ID列表，例如: user1,user2,123456789
ALLOWED_USERS_STR = os.getenv('ALLOWED_USERS', '')
ALLOWED_USERS = [user.strip() for user in ALLOWED_USERS_STR.split(',') if user.strip()]

# 是否启用用户限制功能，如果ALLOWED_USERS为空，则默认不启用
ENABLE_USER_RESTRICTION = bool(ALLOWED_USERS)

# Telegram API (MTProto) 配置
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
# 是否启用 User API (只有当提供 ID 和 HASH 时才启用)
USER_API_ENABLED = bool(API_ID and API_HASH)

if USER_API_ENABLED:
    logger.info("User API (MTProto) 已配置，支持大文件下载 (>20MB)")
else:
    logger.warning("User API (MTProto) 未配置，无法下载超过 20MB 的文件")

# GitHub仓库地址
GITHUB_REPO = "https://github.com/iisyw/TeleGrabber"

# 确保下载目录存在
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)
    logger.info(f"已创建下载目录: {SAVE_DIR}")

def get_connection_args():
    """获取连接参数设置"""
    connection_args = {
        'connect_timeout': TIMEOUT, 
        'read_timeout': TIMEOUT
    }
    
    # 如果设置了代理，就使用代理
    if PROXY:
        connection_args['proxy_url'] = PROXY
        logger.info(f"使用代理: {PROXY}")
    
    return connection_args 