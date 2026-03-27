# B站评论自动回复机器人

![GitHub语言](https://img.shields.io/github/languages/top/Janson20/BiliCommentBot) 
![GitHub星数](https://img.shields.io/github/stars/Janson20/BiliCommentBot) 
![Fork数](https://img.shields.io/github/forks/Janson20/BiliCommentBot) 
![GitHub协议](https://img.shields.io/github/license/Janson20/BiliCommentBot) 
![最新发行版](https://img.shields.io/github/v/release/Janson20/BiliCommentBot) 
![议题](https://img.shields.io/github/issues/Janson20/BiliCommentBot)

使用 DeepSeek API 自动回复 B 站账号下视频新增评论的 Python 机器人，**现已集成完整的 Web UI 管理界面**。

## 功能特性

- 🌐 **Web UI 管理界面**：启动后自动打开浏览器，所有功能通过图形界面操作
- 🤖 自动监控 B 站视频的新增评论
- 🧠 使用 DeepSeek API 生成智能回复
- 🔄 Cookie 自动刷新，避免登录过期
- 👍 支持自动点赞评论（可选）
- 📝 实时日志查看，支持按级别过滤
- 📚 回复历史记录查看
- 🛡️ 智能频率控制和重试机制
- 💾 视频列表缓存，减少 API 请求
- 📱 扫码登录获取 Cookie
- ⚙️ 配置热更新，修改后立即生效无需重启

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动程序

双击 `启动机器人.bat` 或执行：

```bash
python main.py
```

程序会自动打开浏览器访问 `http://127.0.0.1:5000`，你可以通过 Web UI 完成所有配置和操作。

### 3. 配置并启动

1. **获取凭证**：在 Web UI 的「登录」页面，点击「扫码登录」，用 B 站 APP 扫描二维码获取 Cookie
2. **配置 DeepSeek API**：在「配置」→「DeepSeek」填入你的 API 密钥
3. **启动机器人**：在「控制台」页面点击「启动机器人」
4. **查看日志**：在「实时日志」页面监控运行状态

## Web UI 功能页面

| 页面 | 功能说明 |
|------|----------|
| **📊 控制台** | 机器人启动/停止控制、登录状态验证、实时统计（回复数/视频数/状态）、清空缓存 |
| **⚙️ 配置** | 6个分类 Tab：B站、DeepSeek、回复策略、频率控制、缓存、日志 —— 支持热更新 |
| **🔑 登录** | 扫码登录获取 Cookie，登录成功后自动写入配置 |
| **📝 历史记录** | 分页查看所有回复历史，支持清空 |
| **📋 实时日志** | WebSocket 实时推送日志，可按级别过滤（INFO/WARNING/ERROR/DEBUG），支持自动滚动 |

## 配置说明

配置文件为 `config.toml`，你可以通过 Web UI 的「配置」页面修改，也可以直接编辑文件。以下是主要配置项说明：

### B站配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `uid` | 你的 B 站用户ID（从主页URL获取） | - |
| `cookie` | B 站登录 Cookie（通过扫码登录自动获取） | - |
| `refresh_token` | Cookie 刷新令牌（自动刷新时需要） | - |
| `check_interval` | 检查评论的间隔时间（秒） | 60 |
| `auto_refresh_cookie` | 是否自动刷新 Cookie | true |
| `cookie_refresh_interval` | Cookie 刷新间隔（分钟） | 30 |
| `max_comment_pages` | 获取评论的最大页数 | 10 |
| `max_video_pages` | 获取视频列表的最大页数 | 10 |

### DeepSeek API 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | DeepSeek API 密钥 | - |
| `base_url` | API 基础 URL | https://api.deepseek.com/v1 |
| `model` | 使用的模型 | deepseek-chat |
| `max_tokens` | 最大回复长度 | 200 |
| `temperature` | 温度参数（0-1） | 0.7 |
| `system_prompt` | 系统提示词，定义 AI 回复风格 | 友善的 B 站 UP 主 |

### 回复配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enabled` | 是否启用自动回复 | true |
| `prefix` | 回复前缀 | - |
| `only_new` | 是否只回复未处理的评论 | true |
| `max_process` | 每次最多处理的评论数 | 10 |
| `reply_delay` | 回复延迟（秒） | 3 |
| `like_enabled` | 是否在回复前先点赞评论 | false |

### 请求频率控制

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `min_request_interval` | 最小请求间隔（秒） | 2.0 |
| `max_retries` | 最大重试次数 | 3 |
| `retry_delay` | 重试基础延迟（秒） | 5 |

**智能频率控制机制**：
- 动态调整请求间隔：根据连续失败次数自动增加间隔
- 智能退避算法：遇到 429 状态码时解析 Retry-After 头部
- 随机抖动：添加随机延迟避免同步重试
- 请求头随机化：模拟真实用户行为

### 缓存配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enabled` | 是否启用缓存 | true |
| `expire_time` | 缓存过期时间（秒） | 300 |

### 视频缓存配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `expire_time` | 视频列表缓存过期时间（秒） | 43200（12小时） |
| `cache_file` | 视频缓存文件路径 | video_cache.json |

### 日志配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `level` | 日志级别（DEBUG/INFO/WARNING/ERROR） | INFO |
| `file` | 日志文件路径 | logs/bot.log |
| `console` | 是否输出到控制台 | true |

## 完整配置示例

参考 `config.example.toml` 文件：

```toml
[bilibili]
uid = "你的B站用户ID"
cookie = "SESSDATA=xxx; bili_jct=xxx; ..."
refresh_token = "刷新令牌（可选）"
check_interval = 300  # 5分钟检查一次
auto_refresh_cookie = true
cookie_refresh_interval = 30
max_comment_pages = 10
max_video_pages = 10

[deepseek]
api_key = "sk-xxx"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
max_tokens = 200
temperature = 0.7
system_prompt = "你是一个友善的B站游戏区Minecraft UP主，请对评论做出自然、友好的回复。回复要简洁明了，控制在100字以内。"

[reply]
enabled = true
prefix = ""
only_new = true
max_process = 10
reply_delay = 3
like_enabled = false

[rate_limit]
min_request_interval = 2.0
max_retries = 3
retry_delay = 5

[cache]
enabled = true
expire_time = 300

[video_cache]
expire_time = 43200  # 12小时
cache_file = "video_cache.json"

[logging]
level = "INFO"
file = "logs/bot.log"
console = true
```

## 获取凭证

### 获取 B 站 Cookie（推荐方式：扫码登录）

1. 启动程序后访问 Web UI 的「登录」页面
2. 点击「扫码登录」按钮
3. 使用 B 站 APP 扫描二维码并确认登录
4. 登录成功后 Cookie 自动填入配置

**手动获取方式**（备用）：
1. 登录 B 站网页版
2. 按 F12 打开开发者工具
3. 切换到 Network 标签
4. 刷新页面
5. 找到任意请求，查看 Request Headers 中的 Cookie
6. 复制完整的 Cookie 字符串

**重要**：Cookie 中必须包含 `bili_jct` 字段，这是 CSRF 校验必需的。

### 获取 B 站用户 ID

1. 访问你的 B 站主页
2. 查看 URL 中的数字部分（如：space.bilibili.com/123456789）
3. 这个数字就是你的用户 ID

### 获取 DeepSeek API 密钥

1. 访问 [DeepSeek 官网](https://platform.deepseek.com/)
2. 注册并登录
3. 在 API 管理页面创建新的 API 密钥
4. 将密钥填入配置

## 功能详解

### Cookie 自动刷新

机器人支持 Cookie 自动刷新功能，可避免因 Cookie 过期而需要重新获取的问题：

- 在配置中设置 `auto_refresh_cookie = true`
- 提供有效的 `refresh_token` 参数
- 设置 `cookie_refresh_interval` 控制刷新间隔（默认 30 分钟）
- Cookie 和 refresh_token 会自动保存到 `bilibili_cookie.json` 文件

### Cookie 持久化

- Cookie 状态会保存到 `bilibili_cookie.json`
- 包含 cookie、refresh_token 和时间戳
- 程序退出前自动保存
- 启动时优先从文件加载

### 视频列表缓存

为了减少 API 请求频率，机器人会将视频列表缓存到 `video_cache.json` 文件中，默认缓存时间为 12 小时。

**缓存机制**：
- 首次运行时自动获取视频列表并缓存
- 每 12 小时自动更新视频列表
- 如果获取失败，会使用过期缓存
- 缓存保存到文件，重启后仍然有效

**清除缓存**：
- 在 Web UI 的「控制台」页面点击「清空缓存」
- 或删除 `video_cache.json` 文件后重启程序

### 历史记录

机器人会自动将回复过的评论保存到 `history.json` 文件中，包含以下信息：
- 评论 ID 和内容
- 评论用户信息
- 回复内容和时间
- 原始评论时间

你可以在 Web UI 的「历史记录」页面查看所有回复历史。

### 实时日志

程序运行时会生成详细的日志，包括：
- 评论获取和处理信息
- API 调用和响应
- 错误和警告信息
- Cookie 刷新状态

在 Web UI 的「实时日志」页面可以：
- 实时查看日志输出
- 按级别过滤日志
- 支持自动滚动到最新日志

## 故障排除

### Cookie 相关错误

**错误提示：未找到 CSRF token，无法回复评论**
- 原因：Cookie 中缺少 `bili_jct` 字段
- 解决：重新通过扫码登录获取 Cookie

**错误提示：Cookie 已过期，需要重新登录**
- 原因：Cookie 失效且无法自动刷新
- 解决：重新扫码登录获取新的 Cookie

### API 请求错误

**错误提示：请求过于频繁 (429)**
- 原因：请求频率超过 B 站限制
- 解决：增大 `min_request_interval` 和 `reply_delay` 值

**错误提示：JSON 解析失败**
- 原因：B 站 API 返回格式变更或响应被压缩
- 解决：检查日志中的响应内容，或清除缓存重试

### DeepSeek API 错误

**错误提示：DeepSeek API 调用失败**
- 原因：API 密钥无效、配额不足或网络问题
- 解决：检查 api_key 配置，确保账户有足够配额

**回复内容为空或不合理**
- 原因：system_prompt 设置不当
- 解决：调整 system_prompt，使其更符合预期回复风格

### 其他问题

**无法获取视频列表**
- 检查 uid 是否正确
- 确保网络连接正常
- 查看日志中的详细错误信息

**评论未回复**
- 检查 `reply.enabled` 是否为 true
- 查看日志中是否有错误信息
- 确认评论未被历史记录过滤

**Web UI 无法打开**
- 检查端口 5000 是否被占用
- 确认已安装 Flask 和 Flask-SocketIO
- 查看控制台错误信息

## 技术实现

### 核心架构

- **后端**：Flask + Flask-SocketIO，提供 RESTful API 和 WebSocket 实时通信
- **前端**：纯 HTML/CSS/JS，内嵌在 Python 字符串中
- **机器人核心**：后台线程运行，响应停止信号

### 主要模块

**BilibiliCookieManager**
- 管理 B 站 Cookie 的生命周期
- 自动刷新过期的 Cookie
- 持久化 Cookie 状态到文件

**BiliCommentBot**
- 机器人主逻辑控制器
- 管理视频列表和评论获取
- 协调 API 请求和回复生成
- 实现智能频率控制

**WebServer**
- Flask 应用服务器
- 提供 Web UI 界面
- WebSocket 实时日志推送
- 配置 API 接口

### 请求处理流程

1. **初始化阶段**
   - 加载配置文件
   - 初始化 Cookie 管理器
   - 加载历史记录
   - 加载视频缓存

2. **监控循环**
   - 检查 Cookie 状态
   - 获取视频列表（使用缓存）
   - 获取视频评论
   - 过滤已处理评论
   - 生成 AI 回复
   - 发送回复（可选点赞）
   - 保存历史记录

3. **错误处理**
   - 自动重试失败的请求
   - 智能退避避免频率限制
   - 降级到使用缓存
   - 记录详细日志

## 文件说明

| 文件 | 说明 |
|------|------|
| `main.py` | 主程序，包含 Web UI 和机器人核心逻辑 |
| `启动机器人.bat` | Windows 启动脚本 |
| `config.toml` | 配置文件（首次运行自动生成） |
| `config.example.toml` | 配置文件示例 |
| `requirements.txt` | Python 依赖 |
| `history.json` | 回复历史记录 |
| `bilibili_cookie.json` | Cookie 持久化文件 |
| `video_cache.json` | 视频列表缓存 |
| `logs/bot.log` | 程序运行日志 |

## 运行要求

- Python 3.11+
- 网络连接正常
- 已安装依赖（见 requirements.txt）

## 注意事项

1. 请确保 Cookie 和 API 密钥的正确性
2. **Cookie 必须包含 bili_jct 字段**，否则会出现 CSRF 校验失败
3. 建议合理设置检查间隔，避免频繁请求
4. 回复延迟设置可以防止被 B 站限制
5. 首次运行建议先测试，确认配置正确后再长期运行
6. 启用点赞功能会增加 API 请求频率，请谨慎使用
7. Web UI 默认运行在 `http://127.0.0.1:5000`，如需远程访问请修改代码中的 host 配置

## 免责声明

本工具仅供学习和研究使用，请遵守 B 站的相关规定和 API 使用条款。使用本工具所产生的任何后果由用户自行承担。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Janson20/BiliCommentBot&type=date&legend=top-left)](https://www.star-history.com/#Janson20/BiliCommentBot&type=date&legend=top-left)
