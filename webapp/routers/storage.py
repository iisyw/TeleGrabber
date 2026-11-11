"""存储占用统计接口。"""

import logging
import shutil

from fastapi import APIRouter

from webapp.api_response import INTERNAL_SERVER_ERROR, BusinessError, ok
from core.config import SAVE_DIR
from core.utils import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/storage/summary")
def get_storage_summary():
    try:
        conn = get_db_connection()
        try:
            totals = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM media_metadata"
            ).fetchone()
            by_source = conn.execute(
                "SELECT source_name, source_type, COUNT(*), COALESCE(SUM(file_size), 0) "
                "FROM media_metadata GROUP BY source_name, source_type "
                "ORDER BY COUNT(*) DESC"
            ).fetchall()
            by_type = conn.execute(
                "SELECT media_type, COUNT(*), COALESCE(SUM(file_size), 0) "
                "FROM media_metadata GROUP BY media_type ORDER BY COUNT(*) DESC"
            ).fetchall()
        finally:
            conn.close()

        disk = shutil.disk_usage(SAVE_DIR)
        return ok({
            "total_count": totals[0],
            "total_bytes": totals[1],
            "by_source": [
                {
                    "source_name": row[0] or '',
                    "source_type": row[1] or '',
                    "count": row[2],
                    "bytes": row[3],
                }
                for row in by_source
            ],
            "by_type": [
                {"media_type": row[0] or '', "count": row[1], "bytes": row[2]}
                for row in by_type
            ],
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
            },
        })
    except Exception as e:
        logger.error("获取存储统计失败: %s", e)
        raise BusinessError(INTERNAL_SERVER_ERROR, "获取存储统计失败")
