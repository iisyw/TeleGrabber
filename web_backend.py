import os
import sqlite3
import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from utils import DB_PATH, SAVE_DIR, delete_media_records

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("web_backend")

app = FastAPI(title="TeleGrabber Web Management")

# 数据模型
class MediaRecord(BaseModel):
    id: int
    file_unique_id: str
    user_id: Optional[int]
    user_name: Optional[str]
    filename: str
    datetime: str
    media_group_id: Optional[str]
    media_type: str
    caption: Optional[str]
    source: Optional[str]
    source_link: Optional[str]
    source_type: Optional[str]

# 媒体文件映射 (用于预览下载的内容)
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=SAVE_DIR), name="media")

# 静态资源映射 (html, css, js)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "TeleGrabber Dashboard is running. Please ensure 'static' folder exists."}

@app.get("/favicon.ico")
async def favicon():
    favicon_path = os.path.join(static_dir, "favicon.png")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    raise HTTPException(status_code=404)

@app.get("/api/media", response_model=List[MediaRecord])
def get_media(
    limit: int = 30, 
    offset: int = 0, 
    search: Optional[str] = None,
    source: Optional[str] = None,
    media_group_id: Optional[str] = None
):
    """获取媒体记录列表"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        query = "SELECT id, user_id, user_name, filename, datetime, media_group_id, media_type, caption, source, source_link, source_type, file_unique_id FROM media_metadata"
        params = []
        conditions = []
        
        if search:
            conditions.append("(caption LIKE ? OR filename LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        
        if source:
            conditions.append("source = ?")
            params.append(source)

        if media_group_id:
            if media_group_id == "single":
                conditions.append("(media_group_id IS NULL OR media_group_id = '' OR media_group_id = 'single')")
            else:
                conditions.append("media_group_id = ?")
                params.append(media_group_id)
            
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
            
        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [
            MediaRecord(
                id=row[0], user_id=row[1], user_name=row[2], 
                filename=row[3], datetime=row[4], media_group_id=row[5],
                media_type=row[6], caption=row[7], source=row[8],
                source_link=row[9], source_type=row[10], file_unique_id=row[11]
            ) for row in rows
        ]
    except Exception as e:
        logger.error(f"获取媒体记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/media_groups")
def get_media_groups(source: Optional[str] = None):
    """获取指定来源下的所有媒体组ID"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        query = "SELECT DISTINCT media_group_id FROM media_metadata"
        params = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        
        cursor.execute(query, params)
        groups = [row[0] for row in cursor.fetchall() if row[0] and row[0] != 'single']
        conn.close()
        return groups
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sources")
def get_sources():
    """获取所有来源渠道列表"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT source FROM media_metadata WHERE source IS NOT NULL AND source != ''")
        sources = [row[0] for row in cursor.fetchall()]
        conn.close()
        return sources
    except Exception as e:
        logger.error(f"获取来源列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
def get_stats():
    """获取媒体统计信息"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM media_metadata")
        count = cursor.fetchone()[0]
        conn.close()
        return {"total_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/media/{id}")
def delete_media(id: int):
    """删除指定记录及物理文件 (按主键 ID)"""
    try:
        from utils import delete_media_by_id
        deleted_count = delete_media_by_id([id])
        if deleted_count > 0:
            return {"status": "success", "deleted_count": deleted_count}
        else:
            raise HTTPException(status_code=404, detail="未找到相关记录或文件已删除")
    except Exception as e:
        logger.error(f"删除媒体失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/media_group/{media_group_id}")
def delete_media_group(media_group_id: str):
    """删除整个媒体组及其物理文件"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT file_unique_id FROM media_metadata WHERE media_group_id = ?", (media_group_id,))
        unique_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        if not unique_ids:
            raise HTTPException(status_code=404, detail="未找到该媒体组记录")
            
        deleted_count = delete_media_records(unique_ids)
        return {"status": "success", "deleted_count": deleted_count}
    except Exception as e:
        logger.error(f"批量删除媒体组失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def run_server(port=5000):
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

if __name__ == "__main__":
    run_server()
