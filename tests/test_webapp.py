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

    def test_duplicates_returns_empty_when_no_duplicates(self):
        self._save("unique-1", "channel-a", "channel")
        res = media_api.get_duplicates(limit=50)
        self.assertEqual(res["code"], 10000)
        self.assertEqual(res["data"], [])

    def test_media_range_requests(self):
        from fastapi.testclient import TestClient
        client = TestClient(webapp_app)

        test_file_rel = "test_range.txt"
        test_file_path = os.path.join(self.temp_dir.name, test_file_rel)
        with open(test_file_path, "wb") as f:
            f.write(b"0123456789abcdefghij")

        with patch("webapp.app.SAVE_DIR", self.temp_dir.name):
            # 完整请求
            res_full = client.get(f"/media/{test_file_rel}")
            self.assertEqual(res_full.status_code, 200)
            self.assertEqual(res_full.content, b"0123456789abcdefghij")
            self.assertEqual(res_full.headers.get("accept-ranges"), "bytes")

            # Range 切片请求
            res_range = client.get(f"/media/{test_file_rel}", headers={"Range": "bytes=0-9"})
            self.assertEqual(res_range.status_code, 206)
            self.assertEqual(res_range.content, b"0123456789")
            self.assertEqual(res_range.headers.get("content-range"), "bytes 0-9/20")

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

    def test_health_cache_lifecycle_and_persistence(self):
        from webapp import health as health_service

        health_cache_file = os.path.join(self.temp_dir.name, "health_cache.json")
        with patch.object(health_service, "HEALTH_FILE", health_cache_file), \
             patch.object(health_service, "SAVE_DIR", self.temp_dir.name):
            snap = health_service.snapshot(force=True)
            self.assertIn("checked_at", snap)
            self.assertTrue(os.path.exists(health_cache_file))

            cached = health_service.cached()
            self.assertEqual(cached["checked_at"], snap["checked_at"])

    def test_health_issues_and_repair_and_clean(self):
        from webapp import health as health_service
        from fastapi.testclient import TestClient
        client = TestClient(webapp_app)

        health_cache_file = os.path.join(self.temp_dir.name, "health_cache.json")
        with patch.object(health_service, "HEALTH_FILE", health_cache_file), \
             patch.object(health_service, "SAVE_DIR", self.temp_dir.name):

            # 1. 保存一条记录，物理文件存在于 SAVE_DIR
            self._save("health-ok", "chan", "channel")
            chan_dir = os.path.join(self.temp_dir.name, "chan")
            os.makedirs(chan_dir, exist_ok=True)
            file_path = os.path.join(chan_dir, "health-ok.jpg")
            with open(file_path, "wb") as f:
                f.write(b"fake image data")

            # 2. 保存另一条记录，但物理文件不存在
            self._save("health-missing", "chan", "channel")

            # 查询 issues
            res = client.get("/api/status/health/issues?type=all")
            self.assertEqual(res.status_code, 200)
            data = res.json()["data"]
            self.assertGreaterEqual(data["total"], 1)

            # 查询 missing_files
            res_mf = client.get("/api/status/health/issues?type=missing_files")
            self.assertEqual(res_mf.status_code, 200)
            items_mf = res_mf.json()["data"]["items"]
            self.assertTrue(any(it["file_unique_id"] == "health-missing" for it in items_mf))

            # 修复接口
            res_repair = client.post("/api/status/health/repair", json={"action": "all"})
            self.assertEqual(res_repair.status_code, 200)
            self.assertIn("repaired_thumbs", res_repair.json()["data"])

            # 清理缺失文件记录
            res_clean = client.post("/api/status/health/clean-missing", json={})
            self.assertEqual(res_clean.status_code, 200)
            self.assertGreaterEqual(res_clean.json()["data"]["deleted_count"], 1)


if __name__ == "__main__":
    unittest.main()
