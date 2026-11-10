import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault(
    "config",
    SimpleNamespace(
        SAVE_DIR="downloads",
        DATA_DIR="data",
        AUDIT_LOG=False,
        logger=logging.getLogger("test"),
    ),
)

import utils


class UtilsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "telegrabber.db")
        self.db_patch = patch.object(utils, "DB_PATH", self.db_path)
        self.db_patch.start()
        utils.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_private_message_link_normalizes_channel_id(self):
        self.assertEqual(
            utils.build_private_message_link(-1001812716119, 12345),
            "https://t.me/c/1812716119/12345",
        )
        self.assertEqual(
            utils.build_private_message_link("1812716119"),
            "https://t.me/c/1812716119",
        )

    def test_save_to_db_persists_message_ids_and_dimensions(self):
        user = SimpleNamespace(id=1, username="tester", first_name="Tester")
        media = SimpleNamespace(file_id="file-id", file_unique_id="unique-id")

        saved = utils.save_to_db(
            user,
            media,
            "sample.jpg",
            current_message_id=321,
            original_message_id=123,
            width=1080,
            height=1920,
        )

        self.assertTrue(saved)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT message_id, current_message_id, original_message_id, width, height "
                "FROM media_metadata WHERE file_unique_id = ?",
                ("unique-id",),
            ).fetchone()
        self.assertEqual(row, (123, 321, 123, 1080, 1920))

    def test_db_connection_reuses_initialized_wal_mode(self):
        with utils.get_db_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(mode, "wal")
        self.assertEqual(timeout, 60000)

    def test_init_db_creates_query_indexes(self):
        with sqlite3.connect(self.db_path) as conn:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                ).fetchall()
            }

        self.assertTrue(
            {
                "idx_media_source",
                "idx_media_group",
                "idx_media_message_time",
                "idx_media_datetime",
            }.issubset(indexes)
        )


if __name__ == "__main__":
    unittest.main()
