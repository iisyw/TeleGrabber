#!/bin/bash
set -e

echo "===== TeleGrabber 更新脚本 ====="
echo "正在获取最新代码..."
git pull

echo "正在重建并重启容器..."
docker-compose down
docker-compose build --no-cache
docker-compose up -d

echo "更新完成！"
echo "查看日志: docker-compose logs -f"

exit 0 