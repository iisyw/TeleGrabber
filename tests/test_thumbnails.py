import logging
import os
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


class ThumbnailPathTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.thumb_patch = patch.object(utils, "THUMB_DIR", self.temp_dir.name)
        self.thumb_patch.start()

    def tearDown(self):
        self.thumb_patch.stop()
        self.temp_dir.cleanup()

    def test_rejects_unsafe_file_unique_id(self):
        self.assertFalse(utils.is_valid_file_unique_id("../etc/passwd"))
        self.assertFalse(utils.is_valid_file_unique_id("short"))
        self.assertFalse(utils.is_valid_file_unique_id(""))
        self.assertTrue(utils.is_valid_file_unique_id("AgADabcdefghijklmn"))

    def test_thumb_path_is_sharded_and_deterministic(self):
        uid = "AgADabcdefghijklmn"
        path = utils.get_thumb_path(uid)
        self.assertTrue(path.endswith(os.path.join("ag", f"{uid}.webp")))
        self.assertEqual(path, utils.get_thumb_path(uid))
        self.assertEqual(utils.get_thumb_url(uid), f"/thumb/{uid}")

    def test_delete_thumbnail_removes_file(self):
        uid = "AgADabcdefghijklmn"
        path = utils.get_thumb_path(uid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"fake")

        utils.delete_thumbnail(uid)

        self.assertFalse(os.path.exists(path))


@unittest.skipUnless(utils._PIL_AVAILABLE, "Pillow is not installed")
class ThumbnailGenerationTestCase(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.temp_dir = tempfile.TemporaryDirectory()
        self.thumb_patch = patch.object(utils, "THUMB_DIR", self.temp_dir.name)
        self.thumb_patch.start()

        self.original_path = os.path.join(self.temp_dir.name, "original.png")
        Image.new("RGB", (1200, 800), (30, 120, 200)).save(self.original_path)

    def tearDown(self):
        self.thumb_patch.stop()
        self.temp_dir.cleanup()

    def test_generate_thumbnail_creates_webp(self):
        uid = "AgADabcdefghijklmn"
        self.assertTrue(utils.generate_thumbnail(self.original_path, uid, "photo"))

        thumb_path = utils.get_thumb_path(uid)
        self.assertTrue(os.path.exists(thumb_path))
        from PIL import Image

        with Image.open(thumb_path) as img:
            self.assertEqual(img.format, "WEBP")
            self.assertLessEqual(max(img.size), utils.THUMB_MAX_SIZE)

    def test_generate_thumbnail_skips_missing_original(self):
        self.assertFalse(
            utils.generate_thumbnail(
                os.path.join(self.temp_dir.name, "missing.jpg"),
                "AgADabcdefghijklmn",
                "photo",
            )
        )


if __name__ == "__main__":
    unittest.main()
