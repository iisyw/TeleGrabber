import importlib.util
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import utils

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
if FASTAPI_AVAILABLE:
    from webapp.api_response import BusinessError, VALIDATION_FAILED
    from webapp.app import app as webapp_app  # noqa: F401  (确保 app 可正常组装)
    from webapp.routers import media as media_api
    from webapp.routers import sources as sources_api
    from webapp.routers import tasks as tasks_api
    from core import task_manager
else:
    sources_api = None


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class WebAppTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "telegrabber.db")
        self.utils_db_patch = patch.object(utils, "DB_PATH", self.db_path)
        self.utils_db_patch.start()
        utils.init_db()

    def tearDown(self):
        self.utils_db_patch.stop()
        self.temp_dir.cleanup()

    def _save(self, unique_id, source_name, source_type, media_group_id=""):
        user = SimpleNamespace(id=1, username="tester", first_name="Tester")
        media = SimpleNamespace(file_id=unique_id, file_unique_id=unique_id)
        self.assertTrue(
            utils.save_to_db(
                user,
                media,
                f"{unique_id}.jpg",
                source_name=source_name,
                source_type=source_type,
                media_group_id=media_group_id,
            )
        )

    def test_sources_returns_counts_and_totals_in_one_response(self):
        self._save("a", "channel-a", "channel", "album-1")
        self._save("b", "channel-a", "channel", "album-1")
        self._save("c", "channel-b", "channel")

        payload = sources_api.get_sources("channel")

        self.assertEqual(payload["code"], 10000)
        data = payload["data"]
        by_name = {item["source_name"]: item for item in data["sources"]}
        self.assertEqual(by_name["channel-a"]["media_count"], 2)
        self.assertEqual(by_name["channel-a"]["message_count"], 1)
        self.assertEqual(by_name["channel-b"]["message_count"], 1)
        self.assertEqual(data["totals"], {"media_count": 3, "message_count": 2})

    def test_delete_media_group_rejects_empty_id(self):
        with self.assertRaises(BusinessError) as ctx:
            media_api.delete_media_group("")
        self.assertEqual(ctx.exception.code, VALIDATION_FAILED)

        with self.assertRaises(BusinessError) as ctx2:
            media_api.delete_media_group("   ")
        self.assertEqual(ctx2.exception.code, VALIDATION_FAILED)

    def test_tasks_filter_by_batch_id(self):
        task_manager.create_task(
            file_unique_id="f1",
            batch_id="batch-100",
            source_name="chan",
        )
        task_manager.create_task(
            file_unique_id="f2",
            batch_id="batch-200",
            source_name="chan",
        )

        res_100 = tasks_api.get_tasks(limit=50, offset=0, batch_id="batch-100")
        self.assertEqual(res_100["code"], 10000)
        self.assertEqual(len(res_100["data"]["tasks"]), 1)
        self.assertEqual(res_100["data"]["tasks"][0]["file_unique_id"], "f1")

        res_200 = tasks_api.get_tasks(limit=50, offset=0, batch_id="batch-200")
        self.assertEqual(res_200["code"], 10000)
        self.assertEqual(len(res_200["data"]["tasks"]), 1)
        self.assertEqual(res_200["data"]["tasks"][0]["file_unique_id"], "f2")

    def test_duplicates_returns_skipped_tasks(self):
        tid = task_manager.create_task(
            file_unique_id="dup-unique-1",
            filename="dup_image.jpg",
            source_name="chan-dup",
            total_bytes=1048576,
        )
        task_manager.update_task(tid, status="skipped", error="检测到重复文件已跳过")

        res = media_api.get_duplicates(limit=50)
        self.assertEqual(res["code"], 10000)
        data = res["data"]
        self.assertTrue(any(item["file_unique_id"] == "dup-unique-1" for item in data))
        dup_entry = next(item for item in data if item["file_unique_id"] == "dup-unique-1")
        self.assertEqual(dup_entry["count"], 1)
        self.assertEqual(dup_entry["total_bytes"], 1048576)
        self.assertIn("dup_image.jpg", dup_entry["filenames"])
        self.assertIn("chan-dup", dup_entry["sources"])

    def test_task_prune_scheduler_lifecycle(self):
        task_manager.start_task_prune_scheduler(retain_days=30, interval_seconds=3600)
        self.assertIsNotNone(task_manager._prune_thread)
        self.assertTrue(task_manager._prune_thread.is_alive())
        task_manager.stop_task_prune_scheduler()
        task_manager._prune_thread.join(timeout=1)
        self.assertFalse(task_manager._prune_thread.is_alive())

    def test_api_response_envelope(self):
        from webapp.api_response import RESOURCE_NOT_FOUND, error_payload, ok, set_request_id

        set_request_id("rid-123")
        self.assertEqual(
            ok({"value": 1}),
            {"code": 10000, "msg": "成功", "data": {"value": 1}, "requestId": "rid-123"},
        )
        self.assertEqual(
            error_payload(RESOURCE_NOT_FOUND, "没有记录"),
            {"code": RESOURCE_NOT_FOUND, "msg": "没有记录", "requestId": "rid-123"},
        )


if __name__ == "__main__":
    unittest.main()
