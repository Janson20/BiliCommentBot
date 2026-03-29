# 使用 Python 3.11 官方镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    DOCKER_ENV=true

# 安装系统依赖（包括 curl 用于健康检查）
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY main.py .
COPY config.example.toml .
COPY docker-entrypoint.sh .

# 赋予 entrypoint 脚本执行权限
RUN chmod +x docker-entrypoint.sh

# 创建必要的目录
RUN mkdir -p logs data

# 暴露端口
EXPOSE 5000

# 设置数据卷
VOLUME ["/app/logs", "/app/data"]

# 使用 entrypoint 脚本
ENTRYPOINT ["./docker-entrypoint.sh"]
