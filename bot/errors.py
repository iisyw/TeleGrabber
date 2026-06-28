"""全局错误处理器：捕获 handler 中未处理的异常，记录日志并尽量通知用户。"""

from config import logger


async def error_handler(update, context) -> None:
    """注册到 Application 的全局错误回调。

    PTB v21 中，handler 抛出的异常会被传到这里；不注册则只打印
    "No error handlers are registered" 且用户侧无任何反馈。
    """
    logger.error("处理 update 时发生异常", exc_info=context.error)

    # 尽量给用户一个友好提示（失败也不再抛，避免二次异常）
    try:
        if update is not None and getattr(update, "effective_message", None):
            await update.effective_message.reply_text("❌ 处理时发生错误，请稍后重试。")
    except Exception:
        pass
