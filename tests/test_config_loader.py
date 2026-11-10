import os
import tempfile
import unittest

from config_loader import ConfigError, load_config


class ConfigLoaderTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "config.toml")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_defaults_when_file_missing(self):
        cfg = load_config(self.path)
        self.assertEqual(cfg["web"]["port"], 5000)
        self.assertEqual(cfg["telegram"]["download_retries"], 3)
        self.assertFalse(cfg["audit"]["enabled"])

    def test_parse_and_normalize(self):
        self._write(
            """
[telegram]
bot_token = "token"
api_id = 123
api_hash = "hash"
allowed_users = ["alice", 456]
allowed_file_extensions = ["ZIP", "rar"]

[web]
host = "127.0.0.1"
port = 5005

[audit]
enabled = true
"""
        )
        cfg = load_config(self.path)
        self.assertEqual(cfg["telegram"]["api_id"], 123)
        self.assertEqual(cfg["telegram"]["allowed_users"], ["alice", "456"])
        self.assertEqual(
            cfg["telegram"]["allowed_file_extensions"], [".zip", ".rar"]
        )
        self.assertEqual(cfg["web"]["port"], 5005)
        self.assertTrue(cfg["audit"]["enabled"])

    def test_invalid_type_raises(self):
        self._write(
            """
[web]
port = "not-a-number"
"""
        )
        with self.assertRaises(ConfigError):
            load_config(self.path)

    def test_malformed_toml_raises(self):
        self._write("[web\nport = 5000")
        with self.assertRaises(ConfigError):
            load_config(self.path)


if __name__ == "__main__":
    unittest.main()
