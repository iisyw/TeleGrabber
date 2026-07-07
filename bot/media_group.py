"""媒体组收集、持久化与并发下载处理。

适配 python-telegram-bot v21：
- 媒体组收集仅做同步内存/磁盘操作，由 handler 在收到首条消息时发送状态消息后传入。
- JobQueue 回调为 async；实际的并发下载仍跑在 ThreadPoolExecutor 里（路线 A），
  线程内对 bot 的调用通过 run_coroutine_threadsafe 调度回主事件循环。
"""

import os
import json
import time
import asyncio
import threading
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import logger, USER_API_ENABLED
from utils import (
    get_save_directory, generate_temp_filename, get_image_extension,
    get_video_extension, save_to_db, get_duplicate_info, delete_media_records,
    append_audit,
)
import user_api
from bot import state
from bot.helpers import get_forward_source_info
from bot.download import DOWNLOAD_METHOD_BOT, DOWNLOAD_METHOD_USER, build_progress_bar, _stub_user


def load_media_groups_collection():
    """从文件加载媒体组收集状态（仅在启动时调用一次）"""
    try:
        if not os.path.exists(state.MEDIA_GROUP_COLLECTION_FILE):
            return {}

        with open(state.MEDIA_GROUP_COLLECTION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            state.active_collections = data
            logger.info(f"已从磁盘恢复了 {len(state.active_collections)} 个媒体组收集状态")
            return data
    except Exception as e:
        logger.error(f"加载媒体组收集状态失败: {e}")
        return {}


def save_media_groups_collection(collection=None):
    """保存媒体组收集状态到文件（异步持久化）"""
    if collection is None:
        collection = state.active_collections

    try:
        os.makedirs(os.path.dirname(state.MEDIA_GROUP_COLLECTION_FILE), exist_ok=True)
        temp_file = f"{state.MEDIA_GROUP_COLLECTION_FILE}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            serializable_collection = {}
            for key, value in collection.items():
                serializable_collection[key] = {
                    'chat_id': value['chat_id'],
                    'user_id': value['user_id'],
                    'user_name': value['user_name'],
                    'media_group_id': value['media_group_id'],
                    'media_items': value['media_items'],
                    'first_time': value['first_time'],
                    'status_message_id': value.get('status_message_id'),
                    'source': value.get('source'),
                    'source_id': value.get('source_id'),
                    'source_link': value.get('source_link'),
                    'source_type': value.get('source_type'),
                    'caption': value.get('caption')
                }
            json.dump(serializable_collection, f, ensure_ascii=False, indent=2)

        os.replace(temp_file, state.MEDIA_GROUP_COLLECTION_FILE)
        logger.debug("已将媒体组状态异步持久化到磁盘")
    except Exception as e:
        logger.error(f"保存媒体组收集状态失败: {e}")


async def add_photo_to_collection(media_group_id, chat_id, user, photo, context=None, message=None):
    """将照片添加到媒体组收集中"""
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = get_forward_source_info(message)

    if media_group_id:
        return await add_media_to_collection(
            media_group_id, chat_id, user, photo, 'photo', context, message,
            source, source_id, source_link, source_type,
            chat_type=message.chat.type if message else None,
            orig_chat_id=orig_chat_id,
            orig_msg_id=orig_msg_id
        )


async def add_video_to_collection(media_group_id, chat_id, user, video, context=None, message=None):
    """将视频添加到媒体组收集中"""
    source, source_id, source_link, source_type, orig_chat_id, orig_msg_id = get_forward_source_info(message)

    if media_group_id:
        return await add_media_to_collection(
            media_group_id, chat_id, user, video, 'video', context, message,
            source, source_id, source_link, source_type,
            chat_type=message.chat.type if message else None,
            orig_chat_id=orig_chat_id,
            orig_msg_id=orig_msg_id
        )


async def add_media_to_collection(media_group_id, chat_id, user, media_obj, media_type, context=None, message=None,
                                  source=None, source_id=None, source_link=None, source_type=None,
                                  chat_type=None, orig_chat_id=None, orig_msg_id=None):
    """将媒体（照片或视频）添加到媒体组收集中 (优化版：优先操作内存)。

    并发安全：开启 concurrent_updates 后，同一媒体组的多张图会并发进入本函数。
    必须在锁内原子地"占座建组"——只有第一个能建组并成为首条，其余只追加；
    否则会出现每张图都判定自己是首条、各发一条"正在收集"消息的竞态。
    """
    collection_key = f"{chat_id}_{media_group_id}"

    media_info = {
        'file_id': media_obj.file_id,
        'file_unique_id': media_obj.file_unique_id,
        'media_type': media_type,
        'message_id': message.message_id if message else None,
        'file_size': getattr(media_obj, 'file_size', 0),
        'orig_chat_id': orig_chat_id,
        'orig_msg_id': orig_msg_id
    }

    # 锁内原子操作：判定首条 + 占座建组 / 追加
    with state.media_group_lock:
        is_first_media = collection_key not in state.active_collections
        if is_first_media:
            # 立刻占座（status_message_id 先留空，发完消息再回填）
            state.active_collections[collection_key] = {
                'chat_id': chat_id,
                'user_id': user.id,
                'user_name': user.username or user.first_name,
                'media_group_id': media_group_id,
                'media_items': [media_info],
                'first_time': datetime.now().isoformat(),
                'status_message_id': None,
                'source': source,
                'source_id': source_id,
                'source_link': source_link,
                'source_type': source_type,
                'chat_type': chat_type or (message.chat.type if message else None),
                'caption': message.caption if message else None,
                'raw_message': message.to_dict() if message and hasattr(message, 'to_dict') else None,
            }
            need_queue_hint = state.is_processing_media_group or bool(state.pending_media_groups)
        else:
            existing_items = state.active_collections[collection_key]['media_items']
            # 二次更新去重：同一条消息被 Telegram 多次推送 (如先发后改) 时，
            # message_id 相同则视为同一项，仅更新不重复追加，避免组内出现重复/错位。
            duplicate = False
            if media_info['message_id'] is not None:
                for existing in existing_items:
                    if existing.get('message_id') == media_info['message_id']:
                        existing.update(media_info)
                        duplicate = True
                        break
            if not duplicate:
                existing_items.append(media_info)
            if not state.active_collections[collection_key].get('caption') and message and message.caption:
                state.active_collections[collection_key]['caption'] = message.caption
            logger.debug(f"媒体组 {media_group_id} 追加{media_type}，总数: {len(existing_items)}")
        count = len(state.active_collections[collection_key]['media_items'])

    # 仅首条发送状态消息（await 放在锁外），发完回填 message_id
    if is_first_media and context and message:
        text = "⏳ 媒体组已加入队列，请稍候..." if need_queue_hint else "⏳ 正在收集媒体组内容，请稍候..."
        try:
            status_message = await message.reply_text(text, reply_to_message_id=message.message_id)
            with state.media_group_lock:
                grp = state.active_collections.get(collection_key)
                if grp is not None:
                    grp['status_message_id'] = status_message.message_id
            logger.info(f"开始收集媒体组 {media_group_id}，消息ID: {status_message.message_id}")
            save_media_groups_collection()
        except Exception as e:
            logger.warning(f"回复消息失败: {e}")

    return count, is_first_media


def schedule_media_group_processing(context, media_group_id, chat_id):
    """安排媒体组处理任务 (同步：仅入队 + 注册 JobQueue 回调)"""
    collection_key = f"{chat_id}_{media_group_id}"

    with state.media_group_lock:
        state.pending_media_groups.append(collection_key)
        logger.debug(f"媒体组 {media_group_id} 已添加到处理队列，当前队列长度: {len(state.pending_media_groups)}")

    context.job_queue.run_once(
        process_next_media_group,
        state.MEDIA_GROUP_COLLECT_TIME,
        data={'initial_key': collection_key},
    )
    logger.debug(f"已安排媒体组 {media_group_id} 的处理任务")


async def process_next_media_group(context):
    """处理队列中的下一个媒体组 (JobQueue async 回调)"""
    with state.media_group_lock:
        if not state.pending_media_groups:
            state.is_processing_media_group = False
            return
        if state.is_processing_media_group:
            return
        collection_key = state.pending_media_groups.popleft()
        state.is_processing_media_group = True

    try:
        await process_media_group(context, collection_key)
    except Exception as e:
        logger.error(f"处理媒体组 {collection_key} 出错: {e}")
    finally:
        with state.media_group_lock:
            state.is_processing_media_group = False
            still_pending = bool(state.pending_media_groups)
        if still_pending:
            context.job_queue.run_once(process_next_media_group, 0.5, data={})


def _edit_status_threadsafe(bot, loop, chat_id, message_id, text, reply_markup=None):
    """从下载线程把一次消息编辑调度回主事件循环（不等待结果）。"""
    async def _edit():
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, reply_markup=reply_markup,
                parse_mode='Markdown', disable_web_page_preview=True,
            )
        except Exception:
            pass
    try:
        asyncio.run_coroutine_threadsafe(_edit(), loop)
    except Exception:
        pass


async def process_media_group(context, collection_key=None, is_retry=False, retry_type=None):
    """处理媒体组：在线程池中并发下载，下载完成后回主循环刷新 UI。

    本协程负责准备工作和最终汇总；真正的阻塞下载放到线程池执行。
    """
    if collection_key is None and getattr(context, 'job', None):
        collection_key = context.job.data.get('initial_key')

    with state.media_group_lock:
        group_info = state.active_collections.get(collection_key)
        if not group_info and is_retry:
            group_info = state.processed_groups_history.get(collection_key)
        if not group_info:
            logger.error(f"媒体组收集 {collection_key} 不存在")
            return

    loop = asyncio.get_running_loop()
    bot = context.bot
    bot_username = context.bot.username

    append_audit('media_group', group_info=group_info)

    media_items = group_info.get('media_items', [])
    total = len(media_items)
    for item in media_items:
        item.setdefault('download_method', DOWNLOAD_METHOD_USER if item.get('file_size', 0) >= 20 * 1024 * 1024 else DOWNLOAD_METHOD_BOT)
    photo_count = sum(1 for m in media_items if m.get('media_type') == 'photo')
    video_count = sum(1 for m in media_items if m.get('media_type') == 'video')
    doc_count = total - photo_count - video_count
    user_api_indices = [i+1 for i, m in enumerate(media_items) if m.get('download_method') == DOWNLOAD_METHOD_USER]
    user_api_count = len(user_api_indices)

    header_parts = [f"📁 检测到媒体组 ({total}项)"]
    if photo_count:
        header_parts.append(f"🖼️ 图片: {photo_count}张")
    if video_count:
        header_parts.append(f"🎬 视频: {video_count}个")
    if doc_count:
        header_parts.append(f"📄 文件: {doc_count}个")
    if user_api_count == total:
        header_parts.append(f"📡 全部通过 User API 下载")
    elif user_api_count:
        idx_str = '、'.join(str(i) for i in user_api_indices)
        header_parts.append(f"☁️ 第{idx_str}项通过 User API 下载")
    else:
        header_parts.append(f"📡 全部通过 Bot API 下载")
    header = "\n".join(header_parts)

    group_info['_mg_header'] = header

    await context.bot.edit_message_text(
        chat_id=group_info['chat_id'],
        message_id=group_info['status_message_id'],
        text=f"{header}\n\n⏳ 正在下载媒体组...",
        parse_mode='Markdown',
    )

    # 把阻塞的下载与汇总整体丢到线程池，内部对 bot 的调用通过 loop 桥接
    await loop.run_in_executor(
        None,
        lambda: _run_media_group_blocking(
            bot, loop, bot_username, collection_key, group_info, is_retry, retry_type
        ),
    )



def _run_media_group_blocking(bot, loop, bot_username, collection_key, group_info, is_retry, retry_type):
    """媒体组下载的阻塞主体，运行在线程池中。"""
    chat_id = group_info['chat_id']
    media_group_id = group_info['media_group_id']
    user_name = group_info['user_name']
    media_items = group_info['media_items']
    status_message_id = group_info.get('status_message_id')
    total_items = len(media_items)

    if total_items == 0:
        if status_message_id:
            _edit_status_threadsafe(bot, loop, chat_id, status_message_id, "❌ 未能处理任何媒体内容")
        with state.media_group_lock:
            if collection_key in state.active_collections:
                del state.active_collections[collection_key]
                save_media_groups_collection()
        return

    # 清理残留查重标记
    with state.saving_lock:
        for item in media_items:
            fid = item.get('file_unique_id')
            if fid in state.saving_unique_ids:
                state.saving_unique_ids.remove(fid)

    # 重试处理
    if is_retry:
        if retry_type == "all":
            all_ids = [item['file_unique_id'] for item in media_items]
            if all_ids:
                logger.info(f"媒体组 {collection_key} 开始强制重下：正在清理 {len(all_ids)} 条记录...")
                delete_media_records(all_ids)
            for item in media_items:
                item['status'] = 0
        elif retry_type == "this":
            to_delete = [item['file_unique_id'] for item in media_items if item.get('status') == 1]
            if to_delete:
                logger.info(f"媒体组 {collection_key} 重新下载本次：正在清理 {len(to_delete)} 条新记录...")
                delete_media_records(to_delete)
            for item in media_items:
                item['status'] = 0
        elif retry_type == "failed":
            for item in media_items:
                if item.get('status') == 3:
                    item['status'] = 0

    mg_header = group_info.get('_mg_header', '')
    items_status = [item.get('status', 0) for item in media_items]

    if status_message_id:
        progress_text = f"正在保存媒体组...\n进度: {build_progress_bar(media_items, items_status, [0] * total_items)} (0/{total_items})"
        if mg_header:
            progress_text = f"{mg_header}\n\n{progress_text}"
        _edit_status_threadsafe(bot, loop, chat_id, status_message_id, progress_text)

    # 准备目录
    user_id = group_info.get('user_id')
    user_obj = _stub_user({'user_id': user_id, 'user_name': user_name})
    source = group_info.get('source')
    source_type = group_info.get('source_type')
    save_dir = get_save_directory(user_obj, source, source_type)

    start_time = time.time()
    progress_lock = threading.Lock()
    caption = group_info.get('caption')
    skipped_duplicates = []

    item_progress = [0] * total_items
    for item in media_items:
        item.setdefault('download_method', DOWNLOAD_METHOD_BOT)

    base_timestamp = group_info.get('base_timestamp')
    if not base_timestamp:
        base_timestamp = generate_temp_filename(media_group_id)
        group_info['base_timestamp'] = base_timestamp

    last_ui_update = {"time": 0}
    is_finished = {"value": False}
    processed_count = {"value": sum(1 for s in items_status if s in [1, 2])}

    def get_progress_bar():
        # emoji 按实际下载通道区分：Bot API 用 ⏳/🔽/✅/❌，User API 用 🕓/☁️/🟢/🔴。
        return build_progress_bar(media_items, items_status, item_progress)

    def update_ui_async():
        if is_finished["value"] or not status_message_id:
            return
        curr_time = time.time()
        if curr_time - last_ui_update["time"] <= 1.2:
            return
        last_ui_update["time"] = curr_time
        button_list = [
            [
                InlineKeyboardButton("♻️ 重新下载本次", callback_data=f"mg_retry_this:{collection_key}"),
                InlineKeyboardButton("🔥 强制重下全部", callback_data=f"mg_retry_all:{collection_key}")
            ],
            [
                InlineKeyboardButton("🔄 刷新状态", callback_data=f"mg_refresh:{collection_key}"),
                InlineKeyboardButton("🗑️ 删除本次内容", callback_data=f"mg_delete:{collection_key}")
            ]
        ]
        progress_text = f"正在保存媒体组...\n进度: {get_progress_bar()} ({processed_count['value']}/{total_items})"
        if mg_header:
            progress_text = f"{mg_header}\n\n{progress_text}"
        _edit_status_threadsafe(
            bot, loop, chat_id, status_message_id,
            progress_text,
            reply_markup=InlineKeyboardMarkup(button_list),
        )

    def download_and_save_task(index, media_info):
        is_internally_saving = False
        file_unique_id = media_info['file_unique_id']
        try:
            if items_status[index - 1] in [1, 2]:
                return True

            dup_info = get_duplicate_info(file_unique_id)
            with state.saving_lock:
                if file_unique_id in state.saving_unique_ids:
                    is_internally_saving = True
                else:
                    state.saving_unique_ids.add(file_unique_id)

            if dup_info or is_internally_saving:
                with progress_lock:
                    fname = dup_info['filename'] if dup_info else "当前组内重复项"
                    src = dup_info['source'] if dup_info else "本消息"
                    skipped_duplicates.append({
                        'index': index, 'filename': fname, 'source': src,
                        'source_link': dup_info.get('source_link') if dup_info else "",
                        'caption': (dup_info.get('caption') if dup_info else '无') or '无'
                    })
                    items_status[index - 1] = 2
                    media_info['status'] = 2
                    processed_count['value'] += 1
                update_ui_async()
                return True
        except Exception as e:
            logger.error(f"查重逻辑检查出错: {e}")

        try:
            file_size = media_info.get('file_size', 0)
            media_info['download_method'] = media_info.get('download_method', DOWNLOAD_METHOD_BOT)
            force_user_api = media_info.get('download_method') == DOWNLOAD_METHOD_USER

            # 大文件或 /link 来源走 User API (本身就是同步阻塞调用，线程里直接调)
            if force_user_api or (USER_API_ENABLED and file_size >= 20 * 1024 * 1024):
                media_info['download_method'] = DOWNLOAD_METHOD_USER
                ext = media_info.get('ext') or (".mp4" if media_info.get('media_type') == 'video' else ".jpg")
                final_filename = f"{media_group_id}_{index}_{base_timestamp}{ext}"
                final_path = os.path.join(save_dir, final_filename)
                if force_user_api:
                    logger.info(f"链接媒体组项使用 User API 下载: {index}")
                else:
                    logger.info(f"文件较大 ({file_size/1024/1024:.1f}MB)，切换至 User API 下载: {index}")

                with progress_lock:
                    items_status[index - 1] = 4
                    item_progress[index - 1] = 0

                def p_callback(current, total, idx=index):
                    if total > 0:
                        percent = int(current * 100 / total)
                        if percent != item_progress[idx - 1]:
                            with progress_lock:
                                item_progress[idx - 1] = percent
                            update_ui_async()
                    else:
                        update_ui_async()

                link_chat_id = media_info.get('link_chat_id')
                link_msg_id = media_info.get('link_message_id')
                orig_chat_id = media_info.get('orig_chat_id')
                orig_msg_id = media_info.get('orig_msg_id')
                target_chat_id = link_chat_id or orig_chat_id or chat_id
                target_msg_id = link_msg_id or orig_msg_id or media_info['message_id']
                if not link_chat_id and not orig_chat_id:
                    chat_type = group_info.get('chat_type')
                    if chat_type == 'private' or source_type in ["user", "private_user"]:
                        target_chat_id = bot_username or chat_id

                if link_chat_id:
                    success = user_api.run_download_message_media(
                        target_chat_id, target_msg_id, final_path,
                        progress_callback=p_callback,
                    )
                else:
                    success = user_api.run_download_large_file(
                        target_chat_id, target_msg_id, final_path,
                        progress_callback=p_callback, file_unique_id=file_unique_id,
                    )
                if not success and not link_chat_id and target_chat_id != chat_id:
                    logger.warning(f"媒体项 {index} 溯源下载失败，尝试从本地聊天回退下载...")
                    fallback_chat_id = chat_id
                    chat_type = group_info.get('chat_type')
                    if chat_type == 'private' or source_type in ["user", "private_user"]:
                        fallback_chat_id = bot_username or chat_id
                    success = user_api.run_download_large_file(
                        fallback_chat_id, media_info['message_id'], final_path,
                        progress_callback=p_callback, file_unique_id=file_unique_id,
                    )

                if success:
                    media_obj_stub = type('Media', (), {'file_id': media_info['file_id'], 'file_unique_id': file_unique_id})
                    save_to_db(user_obj, media_obj_stub, final_filename,
                               save_dir=save_dir, media_group_id=media_group_id,
                               media_type=media_info.get('media_type', 'photo'),
                               caption=media_info.get('caption') or caption,
                               source=source, source_id=group_info.get('source_id'),
                               source_link=media_info.get('source_link') or group_info.get('source_link'),
                               source_type=source_type)
                    with progress_lock:
                        items_status[index - 1] = 1
                        media_info['status'] = 1
                        processed_count['value'] += 1
                    update_ui_async()
                    return True
                raise Exception("User API 下载失败")

            # 小文件走 Bot API：在主事件循环里 await 下载，线程这里阻塞等结果
            media_type = media_info.get('media_type', 'photo')
            temp_path = os.path.join(save_dir, f"{base_timestamp}_temp_{index}")

            async def _bot_download():
                tg_file = await bot.get_file(media_info['file_id'])
                await tg_file.download_to_drive(temp_path)

            fut = asyncio.run_coroutine_threadsafe(_bot_download(), loop)
            # 设超时兜底：正常不会触发，仅防极端情况下主循环异常导致本线程永久挂起；
            # 超时会抛 TimeoutError，被下方 except 捕获，该项标记为失败，不拖垮整组。
            fut.result(timeout=300)

            ext = get_video_extension(temp_path) if media_type == 'video' else get_image_extension(temp_path)
            final_filename = f"{media_group_id}_{index}_{base_timestamp}{ext}"
            final_path = os.path.join(save_dir, final_filename)
            os.rename(temp_path, final_path)

            media_obj_stub = type('Media', (), {'file_id': media_info['file_id'], 'file_unique_id': file_unique_id})
            db_success = save_to_db(user_obj, media_obj_stub, final_filename,
                                    save_dir=save_dir, media_group_id=media_group_id,
                                    media_type=media_type,
                                    caption=media_info.get('caption') or caption,
                                    source=source, source_id=group_info.get('source_id'),
                                    source_link=media_info.get('source_link') or group_info.get('source_link'),
                                    source_type=source_type)
            if not db_success:
                raise Exception("元数据保存数据库失败 (可能数据库被锁定)")

            with progress_lock:
                items_status[index - 1] = 1
                media_info['status'] = 1
                processed_count['value'] += 1
            update_ui_async()
            return True
        except Exception as e:
            logger.error(f"媒体项 {index} 下载失败: {e}")
            with progress_lock:
                items_status[index - 1] = 3
                media_info['status'] = 3
                processed_count['value'] += 1
            update_ui_async()
            return False
        finally:
            with state.saving_lock:
                if not is_internally_saving and file_unique_id in state.saving_unique_ids:
                    state.saving_unique_ids.remove(file_unique_id)

    futures = [state.download_executor.submit(download_and_save_task, i, item) for i, item in enumerate(media_items, 1)]
    for f in futures:
        f.result()

    elapsed_time = time.time() - start_time
    is_finished["value"] = True

    if status_message_id:
        has_failed = any(s == 3 for s in items_status)
        success_count = sum(1 for s in items_status if s == 1)
        dup_count = sum(1 for s in items_status if s == 2)
        total_success = success_count + dup_count

        finish_text = f"{mg_header}\n\n✅ 媒体组保存完成！({total_success}/{total_items}个项，用时{elapsed_time:.1f}秒)\n"
        finish_text += f"结果: {get_progress_bar()}\n"
        if skipped_duplicates:
            skipped_duplicates.sort(key=lambda x: x['index'])
            finish_text += f"♻️ 跳过了 {len(skipped_duplicates)} 个重复资源:\n"
            for dup in skipped_duplicates:
                source_display = dup['source']
                if dup.get('source_link'):
                    source_display = f"[{dup['source']}]({dup['source_link']})"
                finish_text += f" - 第{dup['index']}项 -> `{dup['filename']}` (来源: {source_display}，原标题: {dup['caption']})\n"
        failed_count = sum(1 for s in items_status if s == 3)
        if has_failed:
            finish_text += f"\n⚠️ 有 {failed_count} 项下载失败，点击「❌ 重试失败项」仅重试这些失败项。"

        keyboard = [[
            InlineKeyboardButton("♻️ 重新下载本次", callback_data=f"mg_retry_this:{collection_key}"),
            InlineKeyboardButton("🔥 强制重下全部", callback_data=f"mg_retry_all:{collection_key}")
        ]]
        row2 = [InlineKeyboardButton("🗑️ 删除本次内容", callback_data=f"mg_delete:{collection_key}")]
        if has_failed:
            row2.insert(0, InlineKeyboardButton(f"❌ 重试失败项({failed_count})", callback_data=f"mg_retry_failed:{collection_key}"))
        keyboard.append(row2)

        _edit_status_threadsafe(
            bot, loop, chat_id, status_message_id, finish_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # 清理内存收集状态并移入历史
    with state.media_group_lock:
        if collection_key in state.active_collections:
            state.processed_groups_history[collection_key] = state.active_collections[collection_key]
            if len(state.processed_groups_history) > 100:
                oldest_key = next(iter(state.processed_groups_history))
                del state.processed_groups_history[oldest_key]
            del state.active_collections[collection_key]
            save_media_groups_collection()
