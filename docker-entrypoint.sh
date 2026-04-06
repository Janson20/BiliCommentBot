#!/bin/bash
set -e

DATA_DIR="/app/data"

# 初始化数据目录
if [ ! -d "$DATA_DIR" ]; then
    mkdir -p "$DATA_DIR"
fi

# 初始化日志目录
if [ ! -d "$DATA_DIR/logs" ]; then
    mkdir -p "$DATA_DIR/logs"
fi

# 如果配置文件不存在，从示例复制
if [ ! -f "$DATA_DIR/config.toml" ]; then
    echo "配置文件不存在，从示例文件创建..."
    cp /app/config.docker.example.toml "$DATA_DIR/config.toml"
    echo "请编辑 $DATA_DIR/config.toml 文件后重启容器"
fi

# 初始化数据文件（如果不存在）
for file in history.json bilibili_cookie.json video_cache.json; do
    if [ ! -f "$DATA_DIR/$file" ]; then
        echo "[]" > "$DATA_DIR/$file" 2>/dev/null || echo "{}" > "$DATA_DIR/$file"
    fi
done

echo "=========================================="
echo "  B站评论自动回复机器人 - Docker 版"
echo "  数据目录: $DATA_DIR"
echo "  配置文件: $DATA_DIR/config.toml"
echo "  日志目录: $DATA_DIR/logs/"
echo "=========================================="

# 启动应用
exec python main.py
