#!/bin/bash
set -e

# 初始化数据目录
if [ ! -d "/app/data" ]; then
    mkdir -p /app/data
fi

# 初始化日志目录
if [ ! -d "/app/logs" ]; then
    mkdir -p /app/logs
fi

# 如果配置文件不存在，从示例复制
if [ ! -f "/app/config.toml" ]; then
    echo "配置文件不存在，从示例文件创建..."
    cp /app/config.example.toml /app/config.toml
    echo "请配置 /app/config.toml 文件后重启容器"
fi

# 初始化数据文件（如果不存在）
for file in history.json bilibili_cookie.json video_cache.json; do
    if [ ! -f "/app/$file" ]; then
        echo "[]" > "/app/$file" 2>/dev/null || echo "{}" > "/app/$file"
    fi
done

# 启动应用
exec python main.py
