# B站评论自动回复机器人

使用DeepSeek API自动回复B站账号下视频的新增评论的Python机器人。

## 功能特性

- 🤖 自动监控B站视频的新增评论
- 🧠 使用DeepSeek API生成智能回复
- 🔄 Cookie自动刷新，避免登录过期
- 👍 支持自动点赞评论（可选）
- ⚙️ 支持TOML配置文件
- 📝 完整的日志记录
- 🔄 可配置的检查间隔和回复策略
- 📚 自动保存回复历史记录
- 💾 视频列表12小时缓存，减少API请求
- 🛡️ 智能频率控制和重试机制
- 🎲 随机化请求头，避免被识别
- 💾 Cookie持久化存储和管理

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置说明

1. 复制并编辑 `config.toml` 文件：

### B站配置
- `cookie`: 从浏览器获取的B站Cookie
- `refresh_token`: Cookie刷新令牌（用于自动刷新Cookie）
- `uid`: 你的B站用户ID
- `check_interval`: 检查评论的间隔时间（秒）
- `cookie_refresh_interval`: Cookie刷新间隔（分钟，默认30）
- `auto_refresh_cookie`: 是否自动刷新Cookie（默认true）

### DeepSeek API配置
- `api_key`: DeepSeek API密钥
- `base_url`: API基础URL
- `model`: 使用的模型（默认：deepseek-chat）
- `max_tokens`: 最大回复长度
- `temperature`: 温度参数（0-1）
- `system_prompt`: 系统提示词，定义AI回复的风格和角色（默认为友善的Minecraft UP主）

### 回复配置
- `enabled`: 是否启用自动回复
- `prefix`: 回复前缀
- `only_new`: 是否只回复未处理的评论
- `max_process`: 每次最多处理的评论数
- `reply_delay`: 回复延迟（秒）
- `like_enabled`: 是否在回复前先点赞评论（默认false）

### 请求频率控制配置
- `min_request_interval`: 最小请求间隔（秒，默认2.0）
- `max_retries`: 最大重试次数（默认3）
- `retry_delay`: 重试基础延迟（秒，默认5）

**智能频率控制机制**：
- 动态调整请求间隔：根据连续失败次数自动增加间隔
- 智能退避算法：遇到429状态码时，会解析Retry-After头部，按照建议时间等待
- 随机抖动：添加随机延迟避免同步重试
- 响应缓存：GET请求会缓存响应，减少重复请求（5分钟过期）
- 请求头随机化：每次请求使用不同的User-Agent和Referer，模拟真实用户行为

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

### Cookie自动刷新功能

机器人支持Cookie自动刷新功能，可避免因Cookie过期而需要重新获取的问题：

**启用自动刷新**：
- 在配置文件中设置 `auto_refresh_cookie = true`
- 提供有效的 `refresh_token` 参数
- 设置 `cookie_refresh_interval` 控制刷新间隔（默认30分钟）

**获取refresh_token**：
refresh_token 通常在登录B站时的响应中获取，可以通过以下方式：
1. 使用B站登录API获取
2. 使用浏览器抓包工具捕获登录响应
3. 在某些情况下，B站可能不提供此功能，此时可禁用自动刷新

**Cookie持久化**：
- Cookie和refresh_token会自动保存到 `bilibili_cookie.json` 文件
- 机器人退出前会自动保存Cookie状态
- 启动时会优先从文件加载Cookie
- Cookie刷新成功后会自动更新文件

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

## 完整配置示例

参考 `config.example.toml` 文件，以下是一个典型的配置示例：

```toml
[bilibili]
uid = "你的B站用户ID"
cookie = "SESSDATA=xxx; bili_jct=xxx; ..."
refresh_token = "刷新令牌（可选）"
check_interval = 300  # 5分钟检查一次
cookie_refresh_interval = 30  # 30分钟检查Cookie
auto_refresh_cookie = true  # 启用Cookie自动刷新

[deepseek]
api_key = "sk-xxx"
base_url = "https://api.deepseek.com"
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
like_enabled = false  # 是否在回复前点赞评论

[rate_limit]
min_request_interval = 2.0
max_retries = 3
retry_delay = 5

[video_cache]
expire_time = 43200  # 12小时
cache_file = "video_cache.json"

[logging]
level = "INFO"
file = "logs/bot.log"
console = true
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
7. Cookie自动刷新功能需要有效的refresh_token，否则会定期提醒重新登录
8. 启用点赞功能会增加API请求频率，请谨慎使用
9. 机器人会自动保存Cookie状态到 `bilibili_cookie.json` 文件，请勿手动删除此文件
10. 如果Cookie过期且无法自动刷新，需要重新登录获取新的Cookie和refresh_token

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

## 高级功能

### 智能响应处理

机器人具备智能的响应处理能力：

**响应解压**：
- 自动检测和处理gzip压缩的响应
- 支持zlib/deflate压缩格式
- 自动回退到普通文本解码

**错误处理**：
- 空响应检测和重试
- JSON解析错误的详细日志记录
- 自动降级到使用过期缓存（如果可用）

### 点赞评论功能

启用点赞功能后，机器人会在回复评论前先点赞该评论：

**配置示例**：
```toml
[reply]
enabled = true
like_enabled = true  # 启用点赞功能
prefix = ""
max_process = 10
reply_delay = 5
```

**注意事项**：
- 点赞功能会增加API请求次数
- 点赞失败不会影响回复功能
- 每个评论只会点赞一次

### Cookie状态监控

机器人会定期检查Cookie状态：

**检查时机**：
- 启动时检查一次
- 每隔 `cookie_refresh_interval` 分钟检查一次
- 在执行重要操作前检查

**状态信息**：
- Cookie是否需要刷新
- 刷新操作的执行结果
- 错误信息和警告

**自动保存**：
- Cookie状态会保存到 `bilibili_cookie.json`
- 包含cookie、refresh_token和时间戳
- 程序退出前自动保存

## 故障排除

### Cookie相关错误

**错误提示：未找到CSRF token，无法回复评论**
- 原因：Cookie中缺少 `bili_jct` 字段
- 解决：重新获取Cookie，确保包含 `bili_jct=xxx` 字段

**错误提示：Cookie已过期，需要重新登录**
- 原因：Cookie失效且无法自动刷新
- 解决：重新登录B站获取新的Cookie和refresh_token

**错误提示：获取refresh_csrf失败**
- 原因：Cookie刷新令牌无效或B站API变更
- 解决：重新获取refresh_token或禁用自动刷新功能

### API请求错误

**错误提示：请求过于频繁 (429)**
- 原因：请求频率超过B站限制
- 解决：增大 `min_request_interval` 和 `reply_delay` 值

**错误提示：JSON解析失败**
- 原因：B站API返回格式变更或响应被压缩
- 解决：检查日志中的响应内容，或清除缓存重试

**错误提示：ps参数超限**
- 原因：每页评论数超过B站限制
- 解决：机器人会自动调整page_size，无需手动处理

### DeepSeek API错误

**错误提示：DeepSeek API调用失败**
- 原因：API密钥无效、配额不足或网络问题
- 解决：检查api_key配置，确保账户有足够配额

**回复内容为空或不合理**
- 原因：system_prompt设置不当
- 解决：调整system_prompt，使其更符合预期回复风格

### 其他问题

**无法获取视频列表**
- 检查uid是否正确
- 确保网络连接正常
- 查看日志中的详细错误信息

**评论未回复**
- 检查 `reply.enabled` 是否为true
- 查看日志中是否有错误信息
- 确认评论未被历史记录过滤

**Cookie文件损坏**
- 删除 `bilibili_cookie.json` 文件
- 重新配置Cookie和refresh_token
- 重启程序

**视频列表未更新**
- 删除 `video_cache.json` 文件强制刷新
- 检查 `video_cache.expire_time` 配置
- 确认网络连接正常

## 技术实现

### 核心类

**BilibiliCookieManager**
- 管理B站Cookie的生命周期
- 自动刷新过期的Cookie
- 持久化Cookie状态到文件
- 检查Cookie有效性

**BiliCommentBot**
- 机器人主逻辑控制器
- 管理视频列表和评论获取
- 协调API请求和回复生成
- 实现智能频率控制

**Comment**
- 评论数据结构
- 存储评论的基本信息和状态

### 请求处理流程

1. **初始化阶段**
   - 加载配置文件
   - 初始化Cookie管理器
   - 加载历史记录
   - 加载视频缓存

2. **监控循环**
   - 检查Cookie状态
   - 获取视频列表（使用缓存）
   - 获取视频评论
   - 过滤已处理评论
   - 生成AI回复
   - 发送回复（可选点赞）
   - 保存历史记录

3. **错误处理**
   - 自动重试失败的请求
   - 智能退避避免频率限制
   - 降级到使用缓存
   - 记录详细日志

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Janson20/BiliCommentBot&type=date&legend=top-left)](https://www.star-history.com/#Janson20/BiliCommentBot&type=date&legend=top-left)