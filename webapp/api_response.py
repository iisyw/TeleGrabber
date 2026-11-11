"""统一响应与业务错误码。

对齐 DefaultFramework 的 internal/platform/gwe 约定：
- 成功：{"code": 10000, "msg": "成功", "data": ..., "requestId": "..."}
- 业务/系统错误：HTTP 200 + 非 10000 的 code
- 未授权：HTTP 401 + code 40100（当前无内置鉴权，仅保留通用映射）
"""

import contextvars
from typing import Any, Optional

from fastapi.responses import JSONResponse

# 通用状态码（与 gwe/error_code.go 对齐）
SUCCESS = 10000
SUCCESS_WITH_WARNING = 10001

REQUEST_ERROR = 40000
PARAMETER_ERROR = 40001
INVALID_REQUEST_FORMAT = 40002
RESOURCE_NOT_FOUND = 40004
METHOD_NOT_ALLOWED = 40005
VALIDATION_FAILED = 40006
ACCESS_DENIED = 40008
BUSINESS_ERROR = 40010

UNAUTHORIZED = 40100
INVALID_CREDENTIALS = 40101

INTERNAL_SERVER_ERROR = 50000
DATABASE_ERROR = 50001
FILE_SYSTEM_ERROR = 50003

ERROR_MESSAGES = {
    SUCCESS: "成功",
    SUCCESS_WITH_WARNING: "成功但有警告",
    REQUEST_ERROR: "请求错误",
    PARAMETER_ERROR: "参数错误",
    INVALID_REQUEST_FORMAT: "无效的请求格式",
    RESOURCE_NOT_FOUND: "资源不存在",
    METHOD_NOT_ALLOWED: "请求方法不支持",
    VALIDATION_FAILED: "数据校验失败",
    ACCESS_DENIED: "没有权限访问该资源",
    BUSINESS_ERROR: "操作失败",
    UNAUTHORIZED: "未登录或会话已过期",
    INVALID_CREDENTIALS: "认证信息无效",
    INTERNAL_SERVER_ERROR: "服务器内部错误",
    DATABASE_ERROR: "数据处理失败",
    FILE_SYSTEM_ERROR: "文件操作失败",
}

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id or "")


def get_request_id() -> str:
    return _request_id_var.get()


def _message_for(code: int, custom_msg: Optional[str] = None) -> str:
    text = str(custom_msg).strip() if custom_msg is not None else ""
    return text or ERROR_MESSAGES.get(code, "操作失败")


def ok(data: Any = None, msg: Optional[str] = None) -> dict:
    """构造成功响应。data 为 None 时不输出 data 字段（对齐 omitempty）。"""
    payload = {"code": SUCCESS, "msg": _message_for(SUCCESS, msg)}
    if data is not None:
        payload["data"] = data
    request_id = get_request_id()
    if request_id:
        payload["requestId"] = request_id
    return payload


def error_payload(code: int, msg: Optional[str] = None) -> dict:
    payload = {"code": code, "msg": _message_for(code, msg)}
    request_id = get_request_id()
    if request_id:
        payload["requestId"] = request_id
    return payload


class BusinessError(Exception):
    """可预期的业务错误；由全局异常处理器转换为统一响应。"""

    def __init__(self, code: int, msg: Optional[str] = None):
        self.code = code
        self.msg = _message_for(code, msg)
        super().__init__(self.msg)


def http_status_for(code: int) -> int:
    # gwe 约定：只有未登录使用 401，其余业务/系统错误仍返回 HTTP 200
    return 401 if code == UNAUTHORIZED else 200


def error_response(code: int, msg: Optional[str] = None, headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=http_status_for(code),
        content=error_payload(code, msg),
        headers=headers,
    )
