#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import signal
import asyncio
import threading

from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
)
import telegram.error

from config import TOKEN, logger, get_connection_args, USER_API_ENABLED, WEB_PORT
import bot
from utils import init_db
import user_api
import web_backend


def build_application():
    """根据配置构造 python-telegram-bot v21 的 Application。"""
    builder = ApplicationBuilder().token(TOKEN)

    # 并发处理 update：否则一个耗时 handler（如大文件下载）会阻塞所有后续消息/回调。
    # PTB v21 默认串行处理，必须显式开启。
    builder = builder.concurrent_updates(True)

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
    app.add_handler(CommandHandler("stats", bot.stats_command))

    # 媒体处理器
    app.add_handler(MessageHandler(filters.PHOTO, bot.process_photo))
    app.add_handler(MessageHandler(filters.VIDEO, bot.process_video))
    app.add_handler(MessageHandler(filters.ANIMATION, bot.process_animation))
    app.add_handler(MessageHandler(filters.Document.IMAGE, bot.download_document))

    # 兜底：其他消息提示不支持
    app.add_handler(MessageHandler(filters.ALL, bot.handle_unsupported))

    # 回调处理器 (媒体组按钮)
    app.add_handler(CallbackQueryHandler(bot.handle_callback_query))

    # 全局错误处理器
    app.add_error_handler(bot.error_handler)

    return app


async def run_bot():
    """在显式管理的事件循环中启动并常驻运行机器人。

    不使用 Application.run_polling()，因为它会自行创建/关闭事件循环，
    与 user_api (Pyrogram) 后台线程的事件循环管理存在冲突，
    导致 'Updater.start_polling was never awaited'。这里手动管理生命周期。
    """
    app = build_application()

    # 带重试地连接 Telegram（网络/代理问题给出友好提示，而非直接崩溃）
    max_retries = 5
    retry_delay = 5
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"尝试连接 Telegram API (尝试 {attempt}/{max_retries})...")
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            break
        except telegram.error.NetworkError as e:
            # 连接失败需要回滚已初始化的部分，避免下次 initialize 报错
            try:
                await app.shutdown()
            except Exception:
                pass
            if attempt < max_retries:
                logger.error(f"连接 Telegram 失败: {e}. 将在 {retry_delay} 秒后重试...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)
            else:
                logger.critical("=" * 60)
                logger.critical(f"经过 {max_retries} 次尝试仍无法连接 Telegram。")
                logger.critical(f"错误详情: {e}")
                logger.critical("如果你在网络受限区域，请在 data/.env 中配置代理，例如：")
                logger.critical("    PROXY_URL=socks5h://127.0.0.1:1080")
                logger.critical("    或 PROXY_URL=http://127.0.0.1:8123")
                logger.critical("=" * 60)
                return

    logger.info("机器人已启动，正在监听消息...")

    # 用一个永不完成的事件挂起，直到收到停止信号
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # Windows 或非主线程不支持 add_signal_handler，忽略
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("正在停止机器人...")
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.error(f"停止机器人时出错: {e}")


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
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("程序被用户中断")
    except Exception:
        logger.exception("机器人运行时发生未捕获异常")


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("程序被用户中断")
    finally:
        if USER_API_ENABLED:
            user_api.stop_user_api()
        sys.exit(0)

