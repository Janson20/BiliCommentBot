# B站评论自动回复机器人

使用DeepSeek API自动回复B站账号下视频的新增评论的Python机器人。

## 功能特性

- 🤖 自动监控B站视频的新增评论
- 🧠 使用DeepSeek API生成智能回复
- ⚙️ 支持TOML配置文件
- 📝 完整的日志记录
- 🔄 可配置的检查间隔和回复策略
- 📚 自动保存回复历史记录
- 💾 视频列表12小时缓存，减少API请求

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置说明

1. 复制并编辑 `config.toml` 文件：

### B站配置
- `cookie`: 从浏览器获取的B站Cookie
- `uid`: 你的B站用户ID
- `check_interval`: 检查评论的间隔时间（秒）

### DeepSeek API配置
- `api_key`: DeepSeek API密钥
- `base_url`: API基础URL
- `model`: 使用的模型（默认：deepseek-chat）
- `max_tokens`: 最大回复长度
- `temperature`: 温度参数（0-1）

### 回复配置
- `enabled`: 是否启用自动回复
- `prefix`: 回复前缀
- `only_new`: 是否只回复未处理的评论
- `max_process`: 每次最多处理的评论数
- `reply_delay`: 回复延迟（秒）

### 请求频率控制配置
- `min_request_interval`: 最小请求间隔（秒，默认2.0）
- `max_retries`: 最大重试次数（默认3）
- `retry_delay`: 重试基础延迟（秒，默认5）

### 视频列表缓存配置
- `expire_time`: 视频列表缓存过期时间（秒，默认43200即12小时）
- `cache_file`: 视频缓存文件路径（默认video_cache.json）

**重要**：视频列表每12小时获取一次，减少API请求，避免频率限制

## 获取B站Cookie

1. 登录B站网页版
2. 按F12打开开发者工具
3. 切换到Network标签
4. 刷新页面
5. 找到任意请求，查看Request Headers中的Cookie
6. 复制完整的Cookie字符串到配置文件
7. **重要**: 确保Cookie中包含`bili_jct`字段，这是CSRF校验必需的

Cookie示例格式：
```
SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx; sid=xxx
```

## 获取B站用户ID

1. 访问你的B站主页
2. 查看URL中的数字部分（如：space.bilibili.com/123456789）
3. 这个数字就是你的用户ID

## 获取DeepSeek API密钥

1. 访问 [DeepSeek官网](https://platform.deepseek.com/)
2. 注册并登录
3. 在API管理页面创建新的API密钥
4. 将密钥填入配置文件

## 运行机器人

```bash
python main.py
```

## 日志文件

日志文件位于 `logs/bot.log`，包含详细的运行信息和错误记录。

## 注意事项

1. 请确保Cookie和API密钥的正确性
2. **Cookie必须包含bili_jct字段**，否则会出现CSRF校验失败
3. 建议合理设置检查间隔，避免频繁请求
4. 回复延迟设置可以防止被B站限制
5. 首次运行建议先测试，确认配置正确后再长期运行
6. 如果遇到CSRF校验失败，请重新获取Cookie并确保包含bili_jct字段

## 停止机器人

按 `Ctrl+C` 可以安全停止机器人运行。

## 历史记录

机器人会自动将回复过的评论保存到 `history.json` 文件中，包含以下信息：

- 评论ID和内容
- 评论用户信息
- 回复内容和时间
- 原始评论时间

历史记录文件格式示例：
```json
[
  {
    "comment_id": "123456789",
    "content": "视频很棒！",
    "user": "用户名",
    "uid": "987654321",
    "time": 1642694400,
    "reply_time": 1642694460,
    "reply_content": "谢谢支持！",
    "timestamp": "2022-01-20 12:01:00"
  }
]
```

## 免责声明

本工具仅供学习和研究使用，请遵守B站的相关规定和API使用条款。使用本工具所产生的任何后果由用户自行承担。

## 视频列表缓存

为了减少API请求频率，机器人会将视频列表缓存到 `video_cache.json` 文件中，默认缓存时间为12小时。

### 缓存机制
- **自动获取**：首次运行时自动获取视频列表并缓存
- **自动更新**：每12小时自动更新视频列表
- **容错处理**：如果获取失败，会使用过期缓存
- **持久化**：缓存保存到文件，重启后仍然有效

### 缓存文件格式
```json
{
  "videos": [
    {
      "bvid": "BV1xx411c7mD",
      "title": "视频标题",
      "description": "视频描述",
      "author": "UP主",
      "play": 1000,
      "comment": 100
    }
  ],
  "fetch_time": 1642694400,
  "fetch_timestamp": "2022-01-20 12:00:00"
}
```

### 配置缓存时间
如需修改缓存时间，编辑 `config.toml` 文件：
```toml
[video_cache]
expire_time = 43200  # 12小时（单位：秒）
cache_file = "video_cache.json"
```

### 清除缓存
如需立即刷新视频列表，删除 `video_cache.json` 文件后重启程序即可。