"""FastAPI 应用组装：中间件、异常处理、静态资源、路由注册与启动。"""

import logging
import mimetypes
import os
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
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
from webapp.routers import media, sources, status, storage

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
    if response.status_code in (200, 206) and request.url.path.startswith(("/assets/", "/media/")):
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
app.include_router(storage.router)
app.include_router(status.router)

# 媒体文件映射（支持 HTTP 206 Partial Content 分片流式缓冲播放）
os.makedirs(SAVE_DIR, exist_ok=True)


@app.get("/media/{file_path:path}")
def serve_media_file(file_path: str, request: Request):
    """支持 Range 请求的媒体文件流式服务，让大视频无需等待全量下载即可边下边播与拖动进度条。"""
    full_path = os.path.abspath(os.path.join(SAVE_DIR, file_path))
    save_root = os.path.abspath(SAVE_DIR)
    if not (full_path == save_root or full_path.startswith(save_root + os.sep)):
        raise HTTPException(status_code=403, detail="禁止访问")

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="媒体文件不存在")

    stat = os.stat(full_path)
    file_size = stat.st_size
    media_type, _ = mimetypes.guess_type(full_path)
    media_type = media_type or "application/octet-stream"

    range_header = request.headers.get("Range")
    if not range_header or not range_header.startswith("bytes="):
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        }
        return FileResponse(full_path, media_type=media_type, headers=headers)

    try:
        range_spec = range_header.replace("bytes=", "").strip()
        parts = range_spec.split("-", 1)
        start_raw, end_raw = parts[0].strip(), parts[1].strip()

        if start_raw and end_raw:
            start = int(start_raw)
            end = int(end_raw)
        elif start_raw:
            start = int(start_raw)
            end = file_size - 1
        elif end_raw:
            start = file_size - int(end_raw)
            end = file_size - 1
        else:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

        if start >= file_size or end >= file_size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

        content_length = end - start + 1

        def stream_chunk():
            with open(full_path, "rb") as f:
                f.seek(start)
                remaining = content_length
                chunk_size = 128 * 1024  # 128KB 块
                while remaining > 0:
                    read_len = min(chunk_size, remaining)
                    data = f.read(read_len)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "ETag": f'"{stat.st_mtime}-{file_size}"',
        }
        return StreamingResponse(
            stream_chunk(),
            status_code=206,
            headers=headers,
            media_type=media_type,
        )
    except Exception:
        return FileResponse(full_path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

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
