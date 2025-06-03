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

# 加载环境变量
load_dotenv()

# Telegram机器人配置
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SAVE_DIR = os.getenv('SAVE_DIR', 'downloads')
PROXY = os.getenv('PROXY_URL')  # 可选的代理设置
TIMEOUT = int(os.getenv('CONNECTION_TIMEOUT', '30'))  # 连接超时设置，默认30秒

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