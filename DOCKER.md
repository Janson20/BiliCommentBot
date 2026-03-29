# Docker 部署指南

本文档介绍如何使用 Docker 部署 B站评论自动回复机器人。

## 前置要求

- Docker 20.10+
- Docker Compose 2.0+
- 至少 1GB 可用磁盘空间

## 快速部署

### 1. 克隆项目

```bash
git clone https://github.com/Janson20/BiliCommentBot.git
cd BiliCommentBot
```

### 2. 创建配置文件

```bash
cp config.example.toml config.toml
```

### 3. 编辑配置文件

编辑 `config.toml`，填入必要的配置：

```toml
[bilibili]
uid = "你的B站用户ID"
cookie = "从WebUI扫码登录获取"
refresh_token = ""
check_interval = 60
auto_refresh_cookie = true
cookie_refresh_interval = 30
max_comment_pages = 10
max_video_pages = 10

[deepseek]
api_key = "你的DeepSeek API密钥"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
max_tokens = 200
temperature = 0.7
system_prompt = "你是一个友善的B站游戏区Minecraft UP主，请对评论做出自然、友好的回复。回复要简洁明了，控制在100字以内。"

[reply]
enabled = true
prefix = "🤖 "
only_new = true
max_process = 10
reply_delay = 2

[rate_limit]
min_request_interval = 2.0
max_retries = 3
retry_delay = 5

[cache]
enabled = true
expire_time = 300

[video_cache]
expire_time = 43200
cache_file = "video_cache.json"

[logging]
level = "INFO"
file = "logs/bot.log"
console = true
```

> **提示**：如果你还没有获取 Cookie，可以先启动容器，然后在 Web UI 的「登录」页面扫码登录获取。

### 4. 启动容器

```bash
docker-compose up -d
```

### 5. 访问 Web UI

打开浏览器访问：`http://localhost:5000`

如果是在服务器上部署，访问：`http://<服务器IP>:5000`

## 常用命令

### 查看日志

```bash
# 实时查看容器日志
docker-compose logs -f

# 查看最近 100 行日志
docker-compose logs --tail=100
```

### 停止和重启

```bash
# 停止容器
docker-compose stop

# 重启容器
docker-compose restart

# 停止并删除容器
docker-compose down
```

### 更新和重建

```bash
# 拉取最新代码
git pull

# 重新构建镜像
docker-compose build

# 重启容器
docker-compose up -d

# 一键更新（重新构建并启动）
docker-compose up -d --build
```

### 进入容器

```bash
# 进入容器 shell
docker-compose exec bilicomment-bot /bin/bash
```

## 数据持久化

Docker Compose 配置会自动挂载以下文件和目录：

| 宿主机路径 | 容器路径 | 说明 |
|-----------|---------|------|
| `./config.toml` | `/app/config.toml` | 配置文件 |
| `./data` | `/app/data` | 数据目录 |
| `./logs` | `/app/logs` | 日志目录 |
| `./history.json` | `/app/history.json` | 回复历史 |
| `./bilibili_cookie.json` | `/app/bilibili_cookie.json` | Cookie 文件 |
| `./video_cache.json` | `/app/video_cache.json` | 视频缓存 |

这些文件和目录会被持久化到宿主机，即使删除容器也不会丢失数据。

## 健康检查

容器内置了健康检查机制：

```bash
# 查看健康状态
docker inspect bilicomment-bot --format='{{.State.Health.Status}}'
```

健康检查状态：
- `healthy` - 服务正常运行
- `unhealthy` - 服务异常
- `starting` - 服务启动中

## 网络配置

### 端口映射

默认端口映射为 `5000:5000`，如需修改，编辑 `docker-compose.yml`：

```yaml
ports:
  - "8080:5000"  # 将容器 5000 端口映射到宿主机 8080
```

### 远程访问

如果需要在局域网内远程访问，确保端口映射为 `0.0.0.0:5000:5000` 或添加：

```yaml
ports:
  - "0.0.0.0:5000:5000"
```

## 环境变量

支持的环境变量：

```yaml
environment:
  - TZ=Asia/Shanghai          # 时区设置
  - PYTHONUNBUFFERED=1        # Python 输出缓冲
  - DOCKER_ENV=true           # Docker 环境标识
```

## 故障排除

### 容器无法启动

```bash
# 查看详细日志
docker-compose logs bilicomment-bot

# 检查配置文件语法
python3 -c "import toml; toml.load('config.toml')"
```

### Web UI 无法访问

1. 检查容器是否运行：`docker-compose ps`
2. 检查端口是否被占用：`netstat -tuln | grep 5000`
3. 检查防火墙设置
4. 查看容器日志：`docker-compose logs`

### 配置修改不生效

修改配置后需要重启容器：

```bash
docker-compose restart
```

### 磁盘空间不足

```bash
# 清理 Docker 资源
docker system prune -a

# 查看 Docker 占用空间
docker system df
```

### 权限问题

如果遇到文件权限问题，可以设置：

```bash
# 设置正确的文件权限
chmod 644 config.toml
chmod 755 logs data
```

## 生产环境部署建议

### 1. 使用反向代理

推荐使用 Nginx 作为反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. 启用 HTTPS

使用 Let's Encrypt 和 Certbot：

```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 3. 日志轮转

配置日志轮转防止日志文件过大：

```yaml
# 在 docker-compose.yml 中添加
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

### 4. 自动重启

Docker Compose 已配置 `restart: unless-stopped`，确保容器异常退出时自动重启。

### 5. 备份策略

定期备份配置和数据：

```bash
#!/bin/bash
# backup.sh
BACKUP_DIR="/path/to/backup"
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf $BACKUP_DIR/bilicomment_$DATE.tar.gz config.toml history.json bilibili_cookie.json video_cache.json logs/
```

## 性能优化

### 资源限制

在 `docker-compose.yml` 中添加资源限制：

```yaml
services:
  bilicomment:
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
```

## 安全建议

1. **不要提交敏感信息**：确保 `config.toml` 不包含在 Git 仓库中
2. **使用强密码**：如果启用了 Web UI 的认证功能，使用强密码
3. **定期更新**：定期更新 Docker 镜像和依赖
4. **限制访问**：使用防火墙限制 Web UI 的访问来源
5. **日志审计**：定期检查日志文件，发现异常行为

## 更新日志

- 2026-03-29: 添加 Docker 部署支持
