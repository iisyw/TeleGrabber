#!/bin/bash
set -e

if [ ! -f conf/config.toml ]; then
    echo "错误：缺少 conf/config.toml，请先复制 conf/config.example.toml 并填写配置。"
    exit 1
fi

echo "===== TeleGrabber 更新脚本 ====="
echo "正在获取最新代码..."
git pull

echo "正在重建并重启容器..."
docker compose down
docker compose build --no-cache
docker compose up -d

echo "更新完成！"
echo "查看日志: docker compose logs -f"

exit 0
