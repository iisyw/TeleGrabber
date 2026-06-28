"""按钮回调处理：媒体组 + 单条消息的重试、刷新、删除等操作 (python-telegram-bot v21, async)。"""

import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import logger
from utils import get_save_directory, delete_media_records, get_duplicate_info
from bot import state
from bot.media_group import process_media_group
from bot.download import (
    MEDIA_LABELS, _single_buttons,
    download_large_from_record, download_small_from_record,
)


async def handle_callback_query(update, context) -> None:
    """处理按钮点击回调"""
    query = update.callback_query
    data = query.data

    logger.info(f"收到回调查询: {data} (用户: {update.effective_user.id})")

    try:
        if data.startswith("mg_"):
            action, collection_key = data.split(":", 1)
            logger.info(f"媒体组动作: {action}, 键: {collection_key}")

            if action == "mg_retry_this":
                await query.answer("正在安全重新下载本次项目...")
                await process_media_group(context, collection_key, is_retry=True, retry_type="this")
            elif action == "mg_retry_all":
                await query.answer("⚠️ 正在强制重新下载全部项目（含存量）...")
                await process_media_group(context, collection_key, is_retry=True, retry_type="all")
            elif action == "mg_retry_failed":
                await query.answer("正在重试失败项目...")
                await process_media_group(context, collection_key, is_retry=True, retry_type="failed")
            elif action == "mg_refresh":
                await _handle_refresh(query, collection_key)
            elif action == "mg_delete":
                await _handle_delete(query, collection_key)

        elif data.startswith("sg_"):
            action, single_key = data.split(":", 1)
            logger.info(f"单条动作: {action}, 键: {single_key}")
            await _handle_single_action(query, context, action, single_key)

        else:
            await query.answer("未知操作")

    except Exception as e:
        logger.error(f"处理回调查询出错: {e}")
        try:
            await query.answer("处理请求时出错", show_alert=True)
        except Exception:
            pass


# ---------------- 单条消息按钮 ----------------

async def _handle_single_action(query, context, action, single_key):
    record = state.get_single_record(single_key)
    if not record:
        await query.answer("⚠️ 找不到该记录，可能已过期或重启。", show_alert=True)
        return

    if action == "sg_delete":
        await _single_delete(query, record, single_key)
    elif action == "sg_redownload":
        # 重新下载：先删本次已存的，再下一遍
        await query.answer("正在重新下载...")
        await _single_redownload(query, context, record, single_key, force=False)
    elif action == "sg_force":
        # 强制重下（重复场景）：删掉库中已存在的同 file_unique_id 记录后重新下载
        await query.answer("⚠️ 正在强制重下（将覆盖已存在记录）...")
        await _single_redownload(query, context, record, single_key, force=True)
    else:
        await query.answer("未知操作")


def _delete_existing(record):
    """删除该 file_unique_id 在库中的记录及物理文件（用于重下前清理）。"""
    try:
        delete_media_records([record['file_unique_id']])
    except Exception as e:
        logger.error(f"清理已存在记录失败: {e}")


async def _single_delete(query, record, single_key):
    await query.answer("正在删除本次内容...")
    deleted = 0
    try:
        deleted = delete_media_records([record['file_unique_id']])
    except Exception as e:
        logger.error(f"删除单条记录失败: {e}")

    # 与媒体组一致：删除后保留记录与"重新下载"按钮，方便用户删了再下回来
    record['final_filename'] = None
    state.put_single_record(single_key, record)
    retry_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("♻️ 重新下载", callback_data=f"sg_redownload:{single_key}")
    ]])

    if deleted > 0:
        await query.edit_message_text(
            "🗑️ 已从本地磁盘和数据库中删除本次内容。", reply_markup=retry_keyboard,
        )
    else:
        await query.edit_message_text(
            "ℹ️ 没有可删除的记录（可能已被删除）。", reply_markup=retry_keyboard,
        )


async def _single_redownload(query, context, record, single_key, force):
    """重新下载单条；force=True 时先删库中已存在记录（覆盖语义）。

    全程在原消息上编辑（不新发消息），与媒体组行为一致。
    """
    bot = context.bot
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    label = MEDIA_LABELS.get(record['media_type'], '文件')

    # 清理旧记录：force 删任何已存在的同 unique_id；普通重下删本次已存的
    if force or record.get('final_filename'):
        _delete_existing(record)

    # 在原消息上显示"重下中"（先去掉按钮，避免下载中被重复点击）
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=f"⏳ 正在重新下载{label}...",
        )
    except Exception:
        pass

    is_large = record.get('file_size', 0) >= 20 * 1024 * 1024
    if is_large:
        # 大文件进度回调也更新这条原消息
        final_filename = await download_large_from_record(bot, record, chat_id, message_id)
    else:
        final_filename = await download_small_from_record(bot, record)

    record['is_dup'] = False  # 重下后不再是"重复"态
    state.put_single_record(single_key, record)

    text = f"✅ {label}已重新保存" if final_filename else f"❌ {label}重新下载失败"
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text,
            reply_markup=_single_buttons(single_key, is_dup=False, has_failed=not final_filename),
        )
    except Exception as e:
        logger.error(f"更新重下结果消息失败: {e}")


# ---------------- 媒体组按钮 ----------------


async def _handle_refresh(query, collection_key):
    await query.answer("正在刷新状态...")
    with state.media_group_lock:
        group_info = state.active_collections.get(collection_key) or state.processed_groups_history.get(collection_key)
        if not group_info:
            await query.answer("⚠️ 找不到该记录，无法刷新", show_alert=True)
            return
        media_items = group_info['media_items']
        items_status = [item.get('status', 0) for item in media_items]

    processed_count = sum(1 for s in items_status if s in [1, 2, 3])
    total_count = len(items_status)

    # 与 media_group.get_progress_bar 保持一致：小文件/大文件两套 emoji
    small_map = {0: "⏳", 1: "✅", 2: "♻️", 3: "❌"}
    large_map = {0: "🕓", 1: "🟢", 2: "♻️", 3: "🔴"}
    bar = []
    for i, s in enumerate(items_status):
        is_large = (media_items[i].get('file_size', 0) or 0) >= 20 * 1024 * 1024
        bar.append((large_map if is_large else small_map).get(s, "❓"))
    progress_bar = "".join(bar)
    status_text = "保存完成 (已手动刷新)" if processed_count >= total_count else "正在保存媒体组..."
    new_text = f"**{status_text}**\n进度: {progress_bar} ({processed_count}/{total_count})"

    button_list = [[
        InlineKeyboardButton("♻️ 重新下载本次", callback_data=f"mg_retry_this:{collection_key}"),
        InlineKeyboardButton("🔥 强制重下全部", callback_data=f"mg_retry_all:{collection_key}")
    ]]
    if processed_count < total_count:
        button_list.append([
            InlineKeyboardButton("🔄 刷新状态", callback_data=f"mg_refresh:{collection_key}"),
            InlineKeyboardButton("🗑️ 删除本次内容", callback_data=f"mg_delete:{collection_key}")
        ])
    else:
        row_last = [InlineKeyboardButton("🗑️ 删除本次内容", callback_data=f"mg_delete:{collection_key}")]
        if any(s == 3 for s in items_status):
            row_last.insert(0, InlineKeyboardButton("❌ 重试失败项", callback_data=f"mg_retry_failed:{collection_key}"))
        button_list.append(row_last)

    try:
        await query.edit_message_text(new_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(button_list))
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"刷新 UI 报错: {e}")
        await query.answer("当前已是最新状态")


async def _handle_delete(query, collection_key):
    await query.answer("正在删除本地内容...")
    with state.media_group_lock:
        group_info = state.processed_groups_history.get(collection_key) or state.active_collections.get(collection_key)
        if not group_info:
            logger.warning(f"删除失败：未找到媒体组信息 {collection_key}")
            await query.edit_message_text("⚠️ 错误：找不到该下载记录，可能已被清理或重启。")
            return

        media_items = group_info.get('media_items', [])
        # 仅删除本次下载成功的记录 (status=1)，不删除重复项 (status=2)
        file_unique_ids = [item['file_unique_id'] for item in media_items if item.get('status') == 1]

        deleted_count = delete_media_records(file_unique_ids) if file_unique_ids else 0

        # 清理内存中的保存标记，防止僵死
        with state.saving_lock:
            for item in media_items:
                fid = item['file_unique_id']
                if fid in state.saving_unique_ids:
                    state.saving_unique_ids.remove(fid)

        # 通过预测文件名尝试物理删除未入库文件
        base_timestamp = group_info.get('base_timestamp')
        media_group_id = group_info.get('media_group_id')
        user_stub = type('User', (), {
            'id': group_info.get('user_id'),
            'username': group_info.get('user_name'),
            'first_name': group_info.get('user_name')
        })
        save_dir = get_save_directory(user_stub, group_info.get('source'), group_info.get('source_type'))

        extra_deleted = 0
        if base_timestamp and media_group_id:
            for i, item in enumerate(media_items, 1):
                ext = ".mp4" if item.get('media_type') == 'video' else ".jpg"
                for fname in (f"{media_group_id}_{i}_{base_timestamp}{ext}", f"{base_timestamp}_temp_{i}"):
                    fpath = os.path.join(save_dir, fname)
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                            extra_deleted += 1
                        except Exception:
                            pass

    retry_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("♻️ 重新下载本次", callback_data=f"mg_retry_this:{collection_key}"),
        InlineKeyboardButton("🔥 强制重下全部", callback_data=f"mg_retry_all:{collection_key}")
    ]])

    if deleted_count > 0 or extra_deleted > 0:
        await query.edit_message_text(
            f"🗑️ 已从本地磁盘和数据库中删除了 {deleted_count + extra_deleted} 个相关文件/记录。",
            reply_markup=retry_keyboard,
        )
    else:
        await query.edit_message_text("ℹ️ 本次下载没有产生任何有效文件或记录。", reply_markup=retry_keyboard)
