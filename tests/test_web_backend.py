import importlib.util
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import utils

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
if FASTAPI_AVAILABLE:
    from webapp.app import app as webapp_app  # noqa: F401  (确保 app 可正常组装)
    from webapp.routers import sources as sources_api
else:
    sources_api = None


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class WebBackendTestCase(unittest.TestCase):
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
