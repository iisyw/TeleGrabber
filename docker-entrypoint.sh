#!/bin/sh
set -e

# 打印Python版本
echo "Python版本："
python --version

# 打印已安装的依赖
echo "\n已安装的依赖："
pip list

# 确保下载目录存在
mkdir -p /app/downloads

# 检查环境变量
if [ -z "$TELEGRAM_BOT_TOKEN" ] && [ ! -f .env ]; then
    echo "错误：TELEGRAM_BOT_TOKEN环境变量未设置，且.env文件不存在！"
    exit 1
fi

echo "\n启动TeleGrabber机器人..."
exec python main.py 