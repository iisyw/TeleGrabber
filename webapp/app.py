"""FastAPI 应用组装：中间件、异常处理、静态资源、路由注册与启动。"""

import logging
import os
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from webapp.api_response import (
    ACCESS_DENIED, INTERNAL_SERVER_ERROR, METHOD_NOT_ALLOWED,
    RESOURCE_NOT_FOUND, UNAUTHORIZED, VALIDATION_FAILED, BusinessError,
    error_payload, error_response, set_request_id,
)
from core.config import SAVE_DIR
from core import runtime_state
from webapp.routers import media, sources, status, storage, tasks

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("webapp")

app = FastAPI(title="TeleGrabber Web Management")


@app.middleware("http")
async def request_context(request: Request, call_next):
    """注入 requestId，并为构建产物/媒体文件设置长缓存。"""
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    if response.status_code == 200 and request.url.path.startswith(("/assets/", "/media/")):
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    return response


def _is_api_request(request: Request) -> bool:
    return request.url.path.startswith("/api/")


@app.exception_handler(BusinessError)
async def handle_business_error(request: Request, exc: BusinessError):
    return error_response(exc.code, exc.msg)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    if not _is_api_request(request):
        return PlainTextResponse("Bad Request", status_code=400)
    return error_response(VALIDATION_FAILED, "请求参数校验失败")


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if not _is_api_request(request):
        return PlainTextResponse(
            str(exc.detail), status_code=exc.status_code, headers=exc.headers
        )

    if exc.status_code == 401:
        code = UNAUTHORIZED
    elif exc.status_code == 403:
        code = ACCESS_DENIED
    elif exc.status_code == 404:
        code = RESOURCE_NOT_FOUND
    elif exc.status_code == 405:
        code = METHOD_NOT_ALLOWED
    elif exc.status_code in (400, 422):
        code = VALIDATION_FAILED
    else:
        code = INTERNAL_SERVER_ERROR

    return JSONResponse(
        status_code=exc.status_code if exc.status_code == 401 else 200,
        content=error_payload(code, exc.detail),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    logger.exception("未捕获异常: %s", exc)
    runtime_state.record_error(str(exc), source="web")
    if not _is_api_request(request):
        return PlainTextResponse("Internal Server Error", status_code=500)
    return error_response(INTERNAL_SERVER_ERROR)


# 路由顺序：API -> 静态资源 -> 前端入口 -> SPA 回退
app.include_router(media.router)
app.include_router(sources.router)
app.include_router(tasks.router)
app.include_router(storage.router)
app.include_router(status.router)

# 媒体文件映射（用于预览下载的内容）
os.makedirs(SAVE_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=SAVE_DIR), name="media")

# Vue 构建产物（web/dist）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
web_dist_dir = os.path.join(PROJECT_ROOT, "web", "dist")
web_assets_dir = os.path.join(web_dist_dir, "assets")
os.makedirs(web_assets_dir, exist_ok=True)
app.mount("/assets", StaticFiles(directory=web_assets_dir), name="assets")


def get_index_path():
    dist_index = os.path.join(web_dist_dir, "index.html")
    return dist_index if os.path.exists(dist_index) else None


@app.get("/")
def read_index():
    index_path = get_index_path()
    if index_path:
        return FileResponse(index_path)
    return error_response(INTERNAL_SERVER_ERROR, "前端尚未构建，请执行 cd web && npm run build")


@app.get("/favicon.ico")
async def favicon():
    favicon_path = os.path.join(web_dist_dir, "favicon.png")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    raise HTTPException(status_code=404, detail="资源不存在")


@app.get("/favicon.png")
async def favicon_png():
    return await favicon()


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """Vue Router history 模式回退：非 API/静态资源路径统一返回 index.html。"""
    reserved = ("api", "media", "thumb", "assets", "static")
    if any(full_path == name or full_path.startswith(f"{name}/") for name in reserved):
        raise HTTPException(status_code=404, detail="接口不存在")

    index_path = get_index_path()
    if index_path:
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="前端尚未构建")


def run_server(host="127.0.0.1", port=5005):
    if host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "Web 后台未启用内置鉴权，正在监听 %s。请确保网络可信，或在前置反向代理上配置访问控制。",
            host,
        )
    uvicorn.run(app, host=host, port=port, log_level="info")
