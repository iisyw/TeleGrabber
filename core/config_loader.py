"""TOML 配置加载与校验。

配置结构见 conf/config.example.toml。加载器只负责读取/合并/校验，
不产生文件系统副作用，便于测试。
"""

import copy
import os
import tomllib
from typing import Any


class ConfigError(Exception):
    """配置缺失或类型错误。"""


DEFAULTS: dict[str, Any] = {
    "telegram": {
        "bot_token": "",
        "api_id": 0,
        "api_hash": "",
        "proxy_url": "",
        "connection_timeout": 30,
        "download_retries": 3,
        "download_timeout": 3600,
        "download_stall_timeout": 180,
        "allowed_users": [],
        "allowed_file_extensions": [
            ".zip", ".rar", ".7z", ".apk", ".tar", ".gz", ".tgz",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".exe", ".iso",
        ],
    },
    "storage": {
        "save_dir": "downloads",
        "data_dir": "data",
    },
    "web": {
        "host": "127.0.0.1",
        "port": 5005,
    },
    "tasks": {
        "retain_days": 30,
        "retry_concurrency": 2,
        "min_free_mb": 512,
    },
    "audit": {
        "enabled": False,
    },
}


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _require_type(value: Any, expected: type, field: str) -> Any:
    # bool 是 int 的子类，需要单独排除
    if expected is int and isinstance(value, bool):
        raise ConfigError(f"{field} 必须是整数")
    if not isinstance(value, expected):
        raise ConfigError(f"{field} 类型错误，期望 {expected.__name__}")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError(f"{field} 必须是数组")
    return [str(item).strip() for item in value if str(item).strip()]


def load_config(path: str) -> dict[str, Any]:
    """读取 TOML 并与默认值合并，完成类型校验和归一化。"""
    data: dict[str, Any] = {}
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"配置文件解析失败 {path}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"无法读取配置文件 {path}: {exc}") from exc

    config = _merge(DEFAULTS, data)

    telegram = config["telegram"]
    storage = config["storage"]
    web = config["web"]
    tasks = config["tasks"]
    audit = config["audit"]

    for section, name in ((telegram, "telegram"), (storage, "storage"), (web, "web"), (tasks, "tasks"), (audit, "audit")):
        if not isinstance(section, dict):
            raise ConfigError(f"[{name}] 必须是配置节")

    _require_type(telegram["bot_token"], str, "telegram.bot_token")
    _require_type(telegram["api_hash"], str, "telegram.api_hash")
    _require_type(telegram["proxy_url"], str, "telegram.proxy_url")
    _require_type(telegram["api_id"], int, "telegram.api_id")
    _require_type(telegram["connection_timeout"], int, "telegram.connection_timeout")
    _require_type(telegram["download_retries"], int, "telegram.download_retries")
    _require_type(telegram["download_timeout"], int, "telegram.download_timeout")
    _require_type(telegram["download_stall_timeout"], int, "telegram.download_stall_timeout")
    _require_type(storage["save_dir"], str, "storage.save_dir")
    _require_type(storage["data_dir"], str, "storage.data_dir")
    _require_type(web["host"], str, "web.host")
    _require_type(web["port"], int, "web.port")
    _require_type(tasks["retain_days"], int, "tasks.retain_days")
    _require_type(tasks["retry_concurrency"], int, "tasks.retry_concurrency")
    _require_type(tasks["min_free_mb"], int, "tasks.min_free_mb")
    _require_type(audit["enabled"], bool, "audit.enabled")

    if telegram["connection_timeout"] <= 0:
        raise ConfigError("telegram.connection_timeout 必须大于 0")
    if telegram["download_retries"] < 0:
        raise ConfigError("telegram.download_retries 不能为负数")
    if telegram["download_timeout"] <= 0:
        raise ConfigError("telegram.download_timeout 必须大于 0")
    if telegram["download_stall_timeout"] <= 0:
        raise ConfigError("telegram.download_stall_timeout 必须大于 0")
    if not (1 <= web["port"] <= 65535):
        raise ConfigError("web.port 必须在 1-65535 之间")
    if not web["host"].strip():
        raise ConfigError("web.host 不能为空；本机使用可填写 127.0.0.1")
    if tasks["retain_days"] < 0:
        raise ConfigError("tasks.retain_days 不能为负数")
    if not (1 <= tasks["retry_concurrency"] <= 10):
        raise ConfigError("tasks.retry_concurrency 必须在 1-10 之间")
    if tasks["min_free_mb"] < 0:
        raise ConfigError("tasks.min_free_mb 不能为负数")

    telegram["allowed_users"] = _string_list(
        telegram["allowed_users"], "telegram.allowed_users"
    )

    extensions = _string_list(
        telegram["allowed_file_extensions"], "telegram.allowed_file_extensions"
    )
    normalized_extensions = []
    for ext in extensions:
        ext = ext.lower()
        normalized_extensions.append(ext if ext.startswith(".") else f".{ext}")
    telegram["allowed_file_extensions"] = normalized_extensions

    return config
