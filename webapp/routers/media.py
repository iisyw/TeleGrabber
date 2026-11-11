"""媒体列表、统计、元数据、缩略图与删除接口。"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from webapp.api_response import (
    INTERNAL_SERVER_ERROR, RESOURCE_NOT_FOUND, VALIDATION_FAILED,
    BusinessError, ok,
)
from core.thumbnails import (
    generate_thumbnail_from_db, get_thumb_path, get_thumb_url,
    is_valid_file_unique_id,
)
from core.utils import _db_lock, delete_media_by_id, delete_media_records, get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter()

THUMB_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _search_condition(conn, search):
    """构造检索条件：FTS5 trigram 优先，短词回退 LIKE。"""
    terms = [term for term in (search or "").split() if term]
    if not terms:
        return None, []
    has_fts = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_fts'"
    ).fetchone()
    if has_fts and all(len(term) >= 3 for term in terms):
        match = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
        return "id IN (SELECT rowid FROM media_fts WHERE media_fts MATCH ?)", [match]
    conditions = []
    params = []
    for term in terms:
        conditions.append("(caption LIKE ? OR filename LIKE ? OR source_name LIKE ?)")
        like = f"%{term}%"
        params.extend([like, like, like])
    return " AND ".join(conditions), params


@router.get("/thumb/{file_unique_id}")
def get_thumbnail(file_unique_id: str):
    """缩略图接口：命中磁盘直接返回，未命中时按需生成并缓存。"""
    if not is_valid_file_unique_id(file_unique_id):
        raise HTTPException(status_code=404, detail="缩略图不存在")

    thumb_path = get_thumb_path(file_unique_id)
    if not os.path.exists(thumb_path):
        generate_thumbnail_from_db(file_unique_id)

    if os.path.exists(thumb_path):
        return FileResponse(
            thumb_path, media_type="image/webp", headers=THUMB_CACHE_HEADERS
        )
    raise HTTPException(status_code=404, detail="缩略图不存在")


@router.get("/api/media")
def get_media(
    limit: int = Query(30, ge=1, le=100),
    search: Optional[str] = None,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None,
    media_group_id: Optional[str] = None,
    media_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    favorite: Optional[bool] = None,
    tag: Optional[str] = None,
    sort: Optional[str] = "message_time",
    cursor_time: Optional[str] = None,
    cursor_id: Optional[int] = None,
):
    """获取媒体记录列表，支持按原始消息时间(message_time)或下载时间(datetime)排序。"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = ("SELECT id, user_id, user_name, filename, datetime, message_time, "
                 "media_group_id, media_type, caption, source_name, source_id, "
                 "source_username, source_link1, source_type, "
                 "file_unique_id, file_id, message_id, current_message_id, original_message_id, remark, width, height, file_size, favorite, tags "
                 "FROM media_metadata")
        params = []
        conditions = []

        if search:
            clause, search_params = _search_condition(cursor, search)
            if clause:
                conditions.append(clause)
                params.extend(search_params)

        if source_name:
            conditions.append("source_name = ?")
            params.append(source_name)

        if media_group_id:
            conditions.append("media_group_id = ?")
            params.append(media_group_id)

        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)

        if media_type:
            conditions.append("media_type = ?")
            params.append(media_type)

        if favorite:
            conditions.append("favorite = 1")

        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%,{tag},%")

        if date_from:
            conditions.append("COALESCE(message_time, datetime) >= ?")
            params.append(date_from)

        if date_to:
            upper = date_to + "T23:59:59" if len(date_to) == 10 else date_to
            conditions.append("COALESCE(message_time, datetime) <= ?")
            params.append(upper)

        if cursor_id is not None:
            if sort == "datetime":
                conditions.append("id < ?")
                params.append(cursor_id)
            elif cursor_time:
                conditions.append(
                    "(COALESCE(message_time, datetime) < ? OR "
                    "(COALESCE(message_time, datetime) = ? AND id < ?))"
                )
                params.extend([cursor_time, cursor_time, cursor_id])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        if sort == "datetime":
            query += " ORDER BY id DESC"
        else:
            query += " ORDER BY COALESCE(message_time, datetime) DESC, id DESC"

        query += " LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return ok([
            {
                "id": row[0], "user_id": row[1], "user_name": row[2],
                "filename": row[3], "datetime": row[4], "message_time": row[5],
                "media_group_id": row[6], "media_type": row[7], "caption": row[8],
                "source_name": row[9], "source_id": row[10],
                "source_username": row[11], "source_link1": row[12],
                "source_type": row[13],
                "file_unique_id": row[14], "file_id": row[15],
                "message_id": row[16], "current_message_id": row[17],
                "original_message_id": row[18], "thumb_url": get_thumb_url(row[14]),
                "remark": row[19], "width": row[20], "height": row[21],
                "file_size": row[22], "favorite": bool(row[23]), "tags": row[24] or '',
            }
            for row in rows
        ])
    except Exception as e:
        logger.error("获取媒体记录失败: %s", e)
        raise HTTPException(status_code=500, detail="获取媒体记录失败")


@router.get("/api/stats")
def get_stats(
    search: Optional[str] = None,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None,
    media_group_id: Optional[str] = None,
    media_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    favorite: Optional[bool] = None,
    tag: Optional[str] = None,
):
    """获取媒体统计信息，筛选参数与 /api/media 一致。"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = ("SELECT COUNT(*), "
                 "COUNT(DISTINCT CASE WHEN media_group_id IS NOT NULL AND media_group_id != '' "
                 "THEN media_group_id ELSE 'msg_' || id END) "
                 "FROM media_metadata")
        params = []
        conditions = []
        if search:
            clause, search_params = _search_condition(cursor, search)
            if clause:
                conditions.append(clause)
                params.extend(search_params)
        if source_name:
            conditions.append("source_name = ?")
            params.append(source_name)
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        if media_type:
            conditions.append("media_type = ?")
            params.append(media_type)
        if favorite:
            conditions.append("favorite = 1")
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%,{tag},%")
        if date_from:
            conditions.append("COALESCE(message_time, datetime) >= ?")
            params.append(date_from)
        if date_to:
            upper = date_to + "T23:59:59" if len(date_to) == 10 else date_to
            conditions.append("COALESCE(message_time, datetime) <= ?")
            params.append(upper)
        if media_group_id:
            conditions.append("media_group_id = ?")
            params.append(media_group_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        cursor.execute(query, params)
        row = cursor.fetchone()
        conn.close()
        return ok({"total_count": row[0], "message_count": row[1], "filtered": bool(conditions)})
    except Exception as e:
        logger.error("获取统计信息失败: %s", e)
        raise HTTPException(status_code=500, detail="获取统计信息失败")


class MediaMetaUpdate(BaseModel):
    favorite: Optional[bool] = None
    tags: Optional[str] = None
    remark: Optional[str] = None


@router.patch("/api/media/{media_id}/meta")
def update_media_meta(media_id: int, payload: MediaMetaUpdate):
    fields = []
    params = []
    if payload.favorite is not None:
        fields.append("favorite = ?")
        params.append(1 if payload.favorite else 0)
    if payload.tags is not None:
        raw = payload.tags.replace("，", ",").split(",")
        tags = []
        for item in raw:
            tag = item.strip()
            if tag and tag not in tags:
                tags.append(tag)
        normalized = f",{','.join(tags)}," if tags else ""
        fields.append("tags = ?")
        params.append(normalized)
    if payload.remark is not None:
        fields.append("remark = ?")
        params.append(payload.remark.strip())
    if not fields:
        raise BusinessError(VALIDATION_FAILED, "没有需要更新的字段")

    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                f"UPDATE media_metadata SET {', '.join(fields)} WHERE id = ?",
                (*params, media_id),
            )
            conn.commit()
            if cursor.rowcount <= 0:
                raise BusinessError(RESOURCE_NOT_FOUND, "媒体不存在")
            row = conn.execute(
                "SELECT favorite, tags, remark FROM media_metadata WHERE id = ?",
                (media_id,),
            ).fetchone()
        finally:
            conn.close()
    return ok({
        "id": media_id,
        "favorite": bool(row[0]),
        "tags": row[1] or '',
        "remark": row[2] or '',
    })


@router.get("/api/duplicates")
def get_duplicates(limit: int = Query(50, ge=1, le=200)):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT file_unique_id, COUNT(*) AS cnt, COALESCE(SUM(file_size), 0), "
            "GROUP_CONCAT(filename, char(31)), GROUP_CONCAT(COALESCE(source_name, ''), char(31)) "
            "FROM media_metadata WHERE file_unique_id IS NOT NULL AND file_unique_id != '' "
            "GROUP BY file_unique_id HAVING COUNT(*) > 1 "
            "ORDER BY cnt DESC, file_unique_id LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return ok([
        {
            "file_unique_id": row[0],
            "count": row[1],
            "total_bytes": row[2],
            "filenames": (row[3] or '').split(chr(31)),
            "sources": (row[4] or '').split(chr(31)),
        }
        for row in rows
    ])


@router.delete("/api/media/{id}")
def delete_media(id: int):
    """删除指定记录及物理文件（按主键 ID）。"""
    try:
        deleted_count = delete_media_by_id([id])
    except Exception as e:
        logger.error("删除媒体失败: %s", e)
        raise BusinessError(INTERNAL_SERVER_ERROR, "删除媒体失败")

    if deleted_count <= 0:
        raise BusinessError(RESOURCE_NOT_FOUND, "未找到相关记录或文件已删除")
    return ok({"status": "success", "deleted_count": deleted_count})


@router.delete("/api/media_group/{media_group_id}")
def delete_media_group(media_group_id: str):
    """删除整个媒体组及其物理文件。"""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_unique_id FROM media_metadata WHERE media_group_id = ?",
                (media_group_id,),
            )
            unique_ids = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.error("查询媒体组失败: %s", e)
        raise BusinessError(INTERNAL_SERVER_ERROR, "批量删除媒体组失败")

    if not unique_ids:
        raise BusinessError(RESOURCE_NOT_FOUND, "未找到该媒体组记录")

    try:
        deleted_count = delete_media_records(unique_ids)
    except Exception as e:
        logger.error("批量删除媒体组失败: %s", e)
        raise BusinessError(INTERNAL_SERVER_ERROR, "批量删除媒体组失败")

    return ok({"status": "success", "deleted_count": deleted_count})
