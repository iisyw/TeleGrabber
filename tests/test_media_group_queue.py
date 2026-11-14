import unittest
from unittest.mock import MagicMock, patch
import os
import tempfile
import json
import threading

from bot import state
from core import utils
from bot.media_group import (
    load_media_groups_collection,
    save_media_groups_collection,
    ensure_media_group_worker,
    process_next_media_group,
    start_pending_media_groups,
)


class TestMediaGroupQueue(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "telegrabber_test.db")
        self.utils_db_patch = patch.object(utils, "DB_PATH", self.db_path)
        self.utils_db_patch.start()
        utils.init_db()

        self.mg_file = os.path.join(self.temp_dir.name, "media_groups_test.json")
        self.old_mg_file = state.MEDIA_GROUP_COLLECTION_FILE
        state.MEDIA_GROUP_COLLECTION_FILE = self.mg_file

        state.pending_media_groups.clear()
        state.active_collections.clear()
        state.processed_groups_history.clear()
        state.is_processing_media_group = False

    def tearDown(self):
        state.MEDIA_GROUP_COLLECTION_FILE = self.old_mg_file
        self.utils_db_patch.stop()
        self.temp_dir.cleanup()

    def test_reentrant_lock_prevents_deadlock(self):
        """测试 state.media_group_lock 在同线程嵌套获取时不发生死锁"""
        acquired_twice = False
        with state.media_group_lock:
            with state.media_group_lock:
                acquired_twice = True
        self.assertTrue(acquired_twice)

    def test_save_collection_under_lock(self):
        """测试持有 media_group_lock 时调用 save_media_groups_collection 不会自锁死"""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
        old_file = state.MEDIA_GROUP_COLLECTION_FILE
        try:
            state.MEDIA_GROUP_COLLECTION_FILE = tmp_path
            state.active_collections["123_456"] = {
                'chat_id': 123,
                'user_id': 456,
                'user_name': 'test',
                'media_group_id': '456',
                'media_items': [],
                'first_time': '2026-11-12T00:00:00',
            }
            # 外部持有锁，内部函数也获取锁 -> 必须在 1 秒内无死锁完成
            done = []
            def target():
                with state.media_group_lock:
                    save_media_groups_collection()
                done.append(True)

            t = threading.Thread(target=target)
            t.start()
            t.join(timeout=2.0)
            self.assertTrue(done, "调用 save_media_groups_collection 发生死锁")
        finally:
            state.MEDIA_GROUP_COLLECTION_FILE = old_file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_ensure_media_group_worker_singleton(self):
        """测试同一时刻只有一个 mg_queue_worker 排队"""
        job_queue = MagicMock()
        job_queue.get_jobs_by_name.return_value = ()
        ensure_media_group_worker(job_queue, delay=1.0)
        job_queue.run_once.assert_called_once_with(
            process_next_media_group, 1.0, name="mg_queue_worker"
        )

        # 第二次调用时已有同名 job，不再重复添加
        job_queue.reset_mock()
        job_queue.get_jobs_by_name.return_value = (MagicMock(),)
        ensure_media_group_worker(job_queue, delay=0.5)
        job_queue.run_once.assert_not_called()

    def test_load_media_groups_collection_recovers_pending(self):
        """测试从磁盘加载时未完成组恢复到 pending_media_groups，已完成组归档到 history"""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as tmp:
            mock_data = {
                "chat1_group_done": {
                    "chat_id": 100,
                    "user_id": 200,
                    "user_name": "u1",
                    "media_group_id": "group_done",
                    "media_items": [
                        {"file_unique_id": "fuid_done_1", "status": 1},
                        {"file_unique_id": "fuid_done_2", "status": 2},
                    ],
                    "first_time": "2026-11-12T01:00:00",
                },
                "chat1_group_pending": {
                    "chat_id": 100,
                    "user_id": 200,
                    "user_name": "u1",
                    "media_group_id": "group_pending",
                    "media_items": [
                        {"file_unique_id": "fuid_pend_1", "status": 1},
                        {"file_unique_id": "fuid_pend_2", "status": None},
                    ],
                    "first_time": "2026-11-12T01:05:00",
                }
            }
            json.dump(mock_data, tmp)
            tmp_path = tmp.name

        old_file = state.MEDIA_GROUP_COLLECTION_FILE
        try:
            state.MEDIA_GROUP_COLLECTION_FILE = tmp_path
            with patch("bot.media_group.get_duplicate_info", return_value=None):
                load_media_groups_collection()

            self.assertIn("chat1_group_done", state.processed_groups_history)
            self.assertNotIn("chat1_group_done", state.active_collections)

            self.assertIn("chat1_group_pending", state.active_collections)
            self.assertIn("chat1_group_pending", state.pending_media_groups)
        finally:
            state.MEDIA_GROUP_COLLECTION_FILE = old_file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_run_media_group_blocking_does_not_early_return(self):
        """测试 _run_media_group_blocking 在有媒体项时不被错误提前 return"""
        from bot.media_group import _run_media_group_blocking
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
        old_file = state.MEDIA_GROUP_COLLECTION_FILE
        try:
            state.MEDIA_GROUP_COLLECTION_FILE = tmp_path
            bot = MagicMock()
            loop = MagicMock()
            group_info = {
                'chat_id': 123,
                'user_id': 456,
                'user_name': 'test',
                'media_group_id': 'mg_test',
                'media_items': [
                    {'file_id': 'fid1', 'file_unique_id': 'fuid1', 'media_type': 'photo', 'status': 0}
                ],
                'status_message_id': 999,
            }
            state.active_collections['123_mg_test'] = group_info

            submitted = []
            def fake_submit(fn, idx, item):
                submitted.append((idx, item))
                fut = MagicMock()
                fut.result.return_value = True
                return fut

            with patch.object(state.download_executor, 'submit', side_effect=fake_submit):
                with patch('bot.media_group.get_save_directory', return_value='/tmp'):
                    _run_media_group_blocking(
                        bot, loop, 'bot', '123_mg_test', group_info, False, None
                    )

            self.assertEqual(len(submitted), 1, "媒体项任务应当被提交执行，而不是被提前 return")
            self.assertNotIn('123_mg_test', state.active_collections)
            self.assertIn('123_mg_test', state.processed_groups_history)
        finally:
            state.MEDIA_GROUP_COLLECTION_FILE = old_file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_link_forward_registry_lifecycle(self):
        """测试链接抓取挂起登记与匹配消耗生命周期"""
        state.pending_link_forwards.clear()

        # 登记一条链接转发
        state.register_link_forward(
            mid=888,
            ref_text="https://t.me/test_chan/888",
            chat_id=-1001234567,
            username="test_chan",
            status_chat_id=12345,
            status_msg_id=9999,
        )

        # 匹配非目标消息应为 None
        self.assertIsNone(state.match_link_forward(-1001234567, 999))

        # 匹配目标消息应成功并返回对应元数据
        matched = state.match_link_forward(-1001234567, 888, orig_username="test_chan")
        self.assertIsNotNone(matched)
        self.assertEqual(matched['url'], "https://t.me/test_chan/888")
        self.assertEqual(matched['status_msg_id'], 9999)

        # 再次匹配应为 None (已一次性消耗)
        self.assertIsNone(state.match_link_forward(-1001234567, 888))



if __name__ == "__main__":
    unittest.main()
