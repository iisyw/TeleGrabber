#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import threading

from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
)

from config import TOKEN, logger, get_connection_args, USER_API_ENABLED, WEB_PORT
import bot
from utils import init_db
import user_api
import web_backend


def build_application():
    """根据配置构造 python-telegram-bot v21 的 Application。"""
    builder = ApplicationBuilder().token(TOKEN)

    conn = get_connection_args()
    if 'connect_timeout' in conn:
        builder = builder.connect_timeout(conn['connect_timeout'])
    if 'read_timeout' in conn:
        builder = builder.read_timeout(conn['read_timeout'])
    if conn.get('proxy'):
        builder = builder.proxy(conn['proxy']).get_updates_proxy(conn['get_updates_proxy'])

    app = builder.build()

    # 命令处理器
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help_command))

    # 媒体处理器
    app.add_handler(MessageHandler(filters.PHOTO, bot.process_photo))
    app.add_handler(MessageHandler(filters.VIDEO, bot.process_video))
    app.add_handler(MessageHandler(filters.ANIMATION, bot.process_animation))
    app.add_handler(MessageHandler(filters.Document.IMAGE, bot.download_document))

    # 兜底：其他消息提示不支持
    app.add_handler(MessageHandler(filters.ALL, bot.handle_unsupported))

    # 回调处理器 (媒体组按钮)
    app.add_handler(CallbackQueryHandler(bot.handle_callback_query))

    return app


def main() -> None:
    """主程序入口"""
    if not TOKEN:
        logger.error("请在 data/.env 文件中设置 TELEGRAM_BOT_TOKEN 环境变量")
        return

    # 初始化数据库与媒体组状态
    init_db()
    bot.load_media_groups_collection()

    # 预启动 User API (MTProto)；放后台线程，避免首次登录阻塞
    if USER_API_ENABLED:
        logger.info("检测到 API 凭据，准备初始化 User API (MTProto)...")
        threading.Thread(target=user_api.start_user_api, daemon=True).start()
        logger.info("User API 初始化已在后台启动，如需登录请关注终端提示")

    # 启动 Web 管理后台 (独立线程，自带 uvicorn 事件循环)
    logger.info(f"正在启动 Web 管理后台 (http://0.0.0.0:{WEB_PORT})...")
    threading.Thread(target=web_backend.run_server, args=(WEB_PORT,), daemon=True).start()

    logger.info("启动机器人...")
    app = build_application()
    # run_polling 自行管理事件循环，并在 SIGINT/SIGTERM 时优雅退出
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("程序被用户中断")
    finally:
        if USER_API_ENABLED:
            user_api.stop_user_api()
        sys.exit(0)
