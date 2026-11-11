"""进程级运行状态，供 Web 状态页读取。"""

import threading
from datetime import datetime

_lock = threading.Lock()
_state = {
    "started_at": None,
    "bot_running": False,
    "bot_id": None,
    "bot_username": None,
    "last_error": None,
    "last_error_at": None,
    "last_error_source": None,
}


def mark_bot_started(bot=None):
    with _lock:
        _state["started_at"] = datetime.now().isoformat()
        _state["bot_running"] = True
        _state["bot_id"] = getattr(bot, "id", None)
        _state["bot_username"] = getattr(bot, "username", None)
        _state["last_error"] = None
        _state["last_error_at"] = None
        _state["last_error_source"] = None


def mark_bot_stopped(error=None):
    with _lock:
        _state["bot_running"] = False
        if error:
            _state["last_error"] = str(error)[:500]
            _state["last_error_at"] = datetime.now().isoformat()
            _state["last_error_source"] = "bot"


def record_error(error, source="runtime"):
    with _lock:
        _state["last_error"] = str(error)[:500]
        _state["last_error_at"] = datetime.now().isoformat()
        _state["last_error_source"] = source


def snapshot():
    with _lock:
        return dict(_state)
