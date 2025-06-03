#!/usr/bin/env python
# -*- coding: utf-8 -*-

# 在所有导入之前过滤警告
import warnings
warnings.filterwarnings("ignore", message="python-telegram-bot is using upstream urllib3")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

import sys
import time
import logging
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import telegram.error

from config import TOKEN, logger, get_connection_args
import bot

def main() -> None:
    """主程序入口"""
    if not TOKEN:
        logger.error("请在.env文件中设置TELEGRAM_BOT_TOKEN环境变量")
        return
        
    # 重试机制
    max_retries = 5
    retry_delay = 5  # 初始延迟5秒
    
    for attempt in range(max_retries):
        try:
            logger.info(f"尝试连接Telegram API (尝试 {attempt + 1}/{max_retries})...")
            
            # 使用配置的连接参数创建Updater
            updater = Updater(TOKEN, request_kwargs=get_connection_args())
            dispatcher = updater.dispatcher
    
            # 注册命令处理器
            dispatcher.add_handler(CommandHandler("start", bot.start))
            dispatcher.add_handler(CommandHandler("help", bot.help_command))
    
            # 注册消息处理器
            # 所有图片由一个处理器处理，在函数内部区分单张和媒体组
            dispatcher.add_handler(MessageHandler(Filters.photo, bot.process_photo))
            # 添加视频处理器
            dispatcher.add_handler(MessageHandler(Filters.video, bot.process_video))
            # 添加动画(GIF)处理器
            dispatcher.add_handler(MessageHandler(Filters.animation, bot.process_animation))
            # 处理文档类型
            dispatcher.add_handler(MessageHandler(Filters.document.image, bot.download_document))
    
            # 启动机器人
            logger.info("启动机器人...")
            updater.start_polling()
            logger.info("机器人已启动，正在监听消息...")
            
            # 持续运行，直到按Ctrl-C停止
            updater.idle()
            
            # 如果正常运行到这里，就跳出重试循环
            break
            
        except telegram.error.NetworkError as e:
            if attempt < max_retries - 1:
                logger.error(f"连接失败: {str(e)}. 将在 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
                # 指数退避策略，每次重试增加延迟时间
                retry_delay = min(retry_delay * 2, 60)  # 最大延迟60秒
            else:
                logger.error(f"经过 {max_retries} 次尝试后仍无法连接。请检查网络或代理设置。")
                logger.error(f"错误详情: {str(e)}")
                # 可以在这里提供使用代理的提示
                logger.info("提示：如果您在中国大陆或网络受限区域，请考虑设置代理。")
                logger.info("您可以在.env文件中添加PROXY_URL环境变量，例如：")
                logger.info("PROXY_URL=socks5h://127.0.0.1:7890")
                break
        except Exception as e:
            logger.error(f"发生未知错误: {str(e)}")
            break

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
        sys.exit(0) 