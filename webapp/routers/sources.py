"""来源列表与来源元数据接口。"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from webapp.api_response import INTERNAL_SERVER_ERROR, VALIDATION_FAILED, BusinessError, ok
from core.utils import _db_lock, get_db_connection
from core import user_api

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/sources")
def get_sources(source_type: Optional[str] = None):
    """一次返回来源列表及各来源媒体/消息计数，避免前端 N+1 请求。"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = (
            "SELECT m.source_name, m.source_type, COUNT(*) AS media_count, "
            "COUNT(DISTINCT CASE "
            "WHEN m.media_group_id IS NOT NULL AND m.media_group_id != '' "
            "THEN m.media_group_id ELSE 'msg_' || m.id END) AS message_count, "
            "MAX(m.datetime) AS last_synced_at, "
            "COALESCE(sm.pinned, 0) AS pinned, COALESCE(sm.hidden, 0) AS hidden, "
            "COALESCE(sm.remark, '') AS remark, MAX(m.source_id) AS source_id "
            "FROM media_metadata m LEFT JOIN source_meta sm ON sm.source_name = m.source_name "
            "WHERE m.source_name IS NOT NULL AND m.source_name != ''"
        )
        params = []
        if source_type:
            query += " AND m.source_type = ?"
            params.append(source_type)
        query += (
            " GROUP BY m.source_name, m.source_type "
            "ORDER BY COALESCE(sm.pinned, 0) DESC, MAX(m.id) DESC"
        )
        cursor.execute(query, params)
        rows = cursor.fetchall()
        failed_rows = cursor.execute(
            "SELECT source_name, COUNT(*) FROM download_tasks "
            "WHERE status = 'failed' AND source_name IS NOT NULL AND source_name != '' "
            "GROUP BY source_name"
        ).fetchall()
        failed_map = {row[0]: row[1] for row in failed_rows}

        total_query = (
            "SELECT COUNT(*), COUNT(DISTINCT CASE "
            "WHEN media_group_id IS NOT NULL AND media_group_id != '' "
            "THEN media_group_id ELSE 'msg_' || id END) FROM media_metadata"
        )
        total_params = []
        if source_type:
            total_query += " WHERE source_type = ?"
            total_params.append(source_type)
        cursor.execute(total_query, total_params)
        totals = cursor.fetchone()
        conn.close()
        return ok({
            "sources": [
                {
                    "source_name": row[0],
                    "source_type": row[1],
                    "media_count": row[2],
                    "message_count": row[3],
                    "last_synced_at": row[4],
                    "pinned": bool(row[5]),
                    "hidden": bool(row[6]),
                    "remark": row[7] or '',
                    "source_id": row[8],
                    "protected": user_api.is_chat_protected(row[8]),
                    "failed_count": failed_map.get(row[0], 0),
                }
                for row in rows
            ],
            "totals": {"media_count": totals[0], "message_count": totals[1]},
        })
    except Exception as e:
        logger.error("获取来源列表失败: %s", e)
        raise BusinessError(INTERNAL_SERVER_ERROR, "获取来源列表失败")


class SourceMetaUpdate(BaseModel):
    source_name: str
    pinned: Optional[bool] = None
    hidden: Optional[bool] = None
    remark: Optional[str] = None


@router.patch("/api/sources/meta")
def update_source_meta(payload: SourceMetaUpdate):
    source_name = (payload.source_name or "").strip()
    if not source_name:
        raise BusinessError(VALIDATION_FAILED, "来源名称不能为空")
    if payload.pinned is None and payload.hidden is None and payload.remark is None:
        raise BusinessError(VALIDATION_FAILED, "没有需要更新的字段")
    with _db_lock:
        conn = get_db_connection()
        try:
            existing = conn.execute(
                "SELECT pinned, hidden, remark FROM source_meta WHERE source_name = ?",
                (source_name,),
            ).fetchone()
            pinned = int(payload.pinned) if payload.pinned is not None else (existing[0] if existing else 0)
            hidden = int(payload.hidden) if payload.hidden is not None else (existing[1] if existing else 0)
            remark = payload.remark if payload.remark is not None else (existing[2] if existing else '')
            conn.execute(
                "INSERT INTO source_meta (source_name, pinned, hidden, remark, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(source_name) DO UPDATE SET pinned = excluded.pinned, "
                "hidden = excluded.hidden, remark = excluded.remark, updated_at = excluded.updated_at",
                (source_name, pinned, hidden, remark, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
    return ok({"source_name": source_name, "pinned": bool(pinned), "hidden": bool(hidden), "remark": remark})
