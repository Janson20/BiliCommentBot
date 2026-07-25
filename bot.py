#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站评论自动回复机器人 — 机器人核心逻辑
"""
import os
import time
import json
import logging
import threading
import hashlib
import urllib.parse
import re
import random
import copy
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─────────────────────────────────────────────
#  文件路径常量
# ─────────────────────────────────────────────
DATA_DIR = os.environ.get("BILI_DATA_DIR", "")
CONFIG_FILE = os.path.join(DATA_DIR, "config.toml") if DATA_DIR else "config.toml"
HISTORY_FILE = os.path.join(DATA_DIR, "history.json") if DATA_DIR else "history.json"
COOKIE_FILE = os.path.join(DATA_DIR, "bilibili_cookie.json") if DATA_DIR else "bilibili_cookie.json"
VIDEO_CACHE_FILE = os.path.join(DATA_DIR, "video_cache.json") if DATA_DIR else "video_cache.json"

# ─────────────────────────────────────────────
#  默认配置
# ─────────────────────────────────────────────
DEFAULT_CONFIG = {
    "bilibili": {
        "cookie": "",
        "refresh_token": "",
        "uid": "",
        "check_interval": 60,
        "auto_refresh_cookie": True,
        "cookie_refresh_interval": 30,
        "max_comment_pages": 10,
        "max_video_pages": 10,
    },
    "rate_limit": {
        "min_request_interval": 3.0,
        "max_retries": 3,
        "retry_delay": 5,
    },
    "cache": {
        "expire_time": 300,
        "enabled": True,
    },
    "video_cache": {
        "expire_time": 43200,
        "cache_file": "video_cache.json",
    },
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "max_tokens": 200,
        "temperature": 0.7,
        "system_prompt": "你是一个友善的B站UP主，请对评论做出自然、友好的回复。回复要简洁明了，控制在100字以内。",
    },
    "reply": {
        "enabled": True,
        "prefix": "",
        "only_new": True,
        "max_process": 10,
        "reply_delay": 2,
        "like_enabled": False,
        "context_comments_count": 0,
        "only_bvid": "",
        "like_user_video_enabled": False,
        "like_user_video_only_followers": False,
        "chained_reply_enabled": True,
        "max_reply_depth": 3,
        "keyword_filter": {
            "enabled": False,
            "whitelist": "",
            "blacklist": "",
            "mode": "any",
            "match_case": False,
        },
        "length_filter": {
            "enabled": False,
            "min_length": 0,
            "max_length": 500,
        },
        "user_filter": {
            "enabled": False,
            "whitelist": "",
            "blacklist": "",
        },
    },
    "logging": {
        "level": "INFO",
        "file": "logs/bot.log",
        "console": True,
    },
    "auth": {
        "enabled": False,
        "password": "",
    },
}

# ─────────────────────────────────────────────
#  模拟响应（缓存命中时返回）
# ─────────────────────────────────────────────
class CachedResponse:
    """模拟 requests.Response，由缓存数据构造"""
    def __init__(self, data: dict):
        self.status_code = 200
        self.headers = {}
        self._data = data

    def json(self):
        return self._data

    @property
    def text(self):
        return json.dumps(self._data, ensure_ascii=False)

    @property
    def content(self):
        return self.text.encode("utf-8")


# ─────────────────────────────────────────────
#  评论数据类
# ─────────────────────────────────────────────
@dataclass
class Comment:
    comment_id: str
    content: str
    user: str
    uid: str
    time: int
    replied: bool = False
    parent_id: Optional[str] = None
    root_id: Optional[str] = None
    depth: int = 0
    children: List['Comment'] = None

    def __post_init__(self):
        if self.children is None:
            self.children = []


# ─────────────────────────────────────────────
#  B站Cookie管理器
# ─────────────────────────────────────────────
class BilibiliCookieManager:
    def __init__(self, cookie_str: str = None, refresh_token: str = None, logger=None):
        self.logger = logger or logging.getLogger("BiliBot")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        })
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        if cookie_str:
            self.set_cookie_from_str(cookie_str)
        self.refresh_token = refresh_token
        self.csrf_token = self._get_csrf_from_cookie()

    def set_cookie_from_str(self, cookie_str: str):
        cookie_dict = {}
        for item in cookie_str.split(";"):
            item = item.strip()
            if not item:
                continue
            if "=" in item:
                key, value = item.split("=", 1)
                cookie_dict[key.strip()] = value.strip()
        self.session.cookies.update(cookie_dict)

    def _get_csrf_from_cookie(self) -> Optional[str]:
        return self.session.cookies.get("bili_jct", None)

    def check_cookie_status(self) -> dict:
        url = "https://passport.bilibili.com/x/passport-login/web/cookie/info"
        try:
            response = self.session.get(url, timeout=10)
            data = response.json()
            if data.get("code") == 0:
                return {"need_refresh": data.get("data", {}).get("refresh", False), "message": "OK"}
            return {"need_refresh": False, "message": data.get("message", "未知错误")}
        except Exception as e:
            return {"need_refresh": False, "message": str(e)}

    def get_refresh_csrf(self) -> Optional[str]:
        timestamp = int(time.time())
        md5 = hashlib.md5(f"{timestamp}".encode()).hexdigest()
        correspond_path = f"/apis/redirect/login?from=bilibili.com&timestamp={timestamp}&md5={md5}"
        encoded_path = urllib.parse.quote(correspond_path, safe="")
        url = f"https://www.bilibili.com/correspond/1/{encoded_path}"
        try:
            response = self.session.get(url, timeout=15)
            html_content = response.text
            # 合并为单一正则（B站可能用双引号或单引号）
            match = re.search(
                r'''refresh_csrf\s*[=:]\s*['"]([^'"]+)['"]''',
                html_content, re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()
            return self.session.cookies.get("refresh_csrf")
        except Exception as e:
            self.logger.error(f"获取refresh_csrf异常: {e}")
            return None

    def refresh_cookie(self, refresh_token: str = None) -> Tuple[bool, dict]:
        token = refresh_token or self.refresh_token
        if not token:
            return False, {"message": "refresh_token不存在"}
        refresh_csrf = self.get_refresh_csrf()
        if not refresh_csrf:
            return False, {"message": "获取refresh_csrf失败"}
        csrf_token = self._get_csrf_from_cookie()
        if not csrf_token:
            return False, {"message": "获取CSRF token失败"}
        url = "https://passport.bilibili.com/x/passport-login/web/cookie/refresh"
        params = {"csrf": csrf_token, "refresh_csrf": refresh_csrf, "refresh_token": token, "source": "main_web"}
        try:
            response = self.session.post(url, data=params, timeout=15)
            data = response.json()
            if data.get("code") == 0:
                response_data = data.get("data", {})
                new_refresh_token = response_data.get("refresh_token")
                if new_refresh_token:
                    self.refresh_token = new_refresh_token
                if response.cookies:
                    for k, v in response.cookies.items():
                        self.session.cookies.set(k, v)
                self.csrf_token = self._get_csrf_from_cookie()
                return True, {"message": "刷新成功", "new_refresh_token": new_refresh_token, "cookies": dict(self.session.cookies)}
            return False, {"message": data.get("message", "刷新失败")}
        except Exception as e:
            return False, {"message": str(e)}

    def verify_cookie(self) -> Tuple[bool, dict]:
        sessdata = self.session.cookies.get("SESSDATA")
        bili_jct = self.session.cookies.get("bili_jct")
        if not sessdata or not bili_jct:
            return False, {"message": "关键Cookie缺失", "code": -1}
        url = "https://api.bilibili.com/x/space/myinfo"
        try:
            response = self.session.get(url, timeout=10)
            data = response.json()
            if data.get("code") == 0:
                user_info = data.get("data", {})
                return True, {"message": "Cookie有效", "user_info": {"mid": user_info.get("mid"), "name": user_info.get("name")}}
            return False, {"message": data.get("message", "验证失败"), "code": data.get("code")}
        except Exception as e:
            return False, {"message": str(e), "code": -999}

    def auto_refresh_if_needed(self) -> Tuple[bool, dict]:
        status = self.check_cookie_status()
        if status.get("need_refresh"):
            success, result = self.refresh_cookie()
            return True, {"success": success, **result}
        return False, {"message": "Cookie状态正常"}

    def get_cookie_str(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.session.cookies.items())

    def save_to_file(self, filename: str = COOKIE_FILE):
        data = {"cookie": dict(self.session.cookies), "refresh_token": self.refresh_token, "timestamp": time.time()}
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_file(self, filename: str = COOKIE_FILE) -> bool:
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.get("cookie", {}).items():
                self.session.cookies.set(k, v)
            self.refresh_token = data.get("refresh_token", "")
            self.csrf_token = self._get_csrf_from_cookie()
            return True
        except Exception:
            return False


# ─────────────────────────────────────────────
#  机器人核心
# ─────────────────────────────────────────────
class BiliCommentBot:
    # 本地 BVID ↔ AID 互转常量（所有实例共享）
    _BV_XOR = 23442827791579
    _BV_MASK = 2251799813685247
    _BV_BASE = 58
    _BV_TABLE = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"

    def __init__(self, config: dict, logger: logging.Logger, socketio=None, on_config_changed=None):
        self.config = config
        self.logger = logger
        self.socketio = socketio  # 可选，用于推送到前端
        self.on_config_changed = on_config_changed  # 配置变更回调，用于持久化

        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=Retry(total=0))
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/92.0.4515.107 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
        ]
        self.referers = [
            "https://www.bilibili.com/",
            "https://search.bilibili.com/",
            "https://space.bilibili.com/",
        ]
        self.update_headers()

        # Cookie 管理器
        self.cookie_manager: Optional[BilibiliCookieManager] = None
        self.csrf_token: Optional[str] = None
        self.last_cookie_refresh_time = 0
        self.cookie_refresh_interval = self.config["bilibili"].get("cookie_refresh_interval", 30) * 60
        self.auto_refresh_cookie = self.config["bilibili"].get("auto_refresh_cookie", True)
        self._init_cookie()

        # 历史记录缓冲（必须在 load_history 之前初始化）
        self._history_buffer: List[dict] = []
        self._history_dirty = False
        self._history_flush_interval = 10  # 每 10 条 flush 一次

        # 历史 & 缓存
        self.processed_comments: set = set()
        self.load_history()
        self.cache: dict = {}
        self.cache_expire_time = self.config.get("cache", {}).get("expire_time", 300)

        # 频率控制
        self.last_request_time = 0
        rl = self.config.get("rate_limit", {})
        self.min_request_interval = rl.get("min_request_interval", 2.0)
        self.max_retries = rl.get("max_retries", 3)
        self.retry_delay = rl.get("retry_delay", 5)
        self.consecutive_failures = 0
        self.adaptive_interval = self.min_request_interval

        # 视频缓存
        vc = self.config.get("video_cache", {})
        self.cached_videos: List[dict] = []
        self.last_video_fetch_time = 0
        cache_file_path = vc.get("cache_file", "video_cache.json")
        if DATA_DIR and not os.path.isabs(cache_file_path):
            cache_file_path = os.path.join(DATA_DIR, cache_file_path)
        self.video_cache_file = cache_file_path
        self.video_cache_expire_time = vc.get("expire_time", 43200)
        self.load_video_cache()

        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 统计
        self.stats = {"total_replied": 0, "start_time": None, "last_check": None}

        # B站频率限制相关错误码
        self.BILI_RATE_LIMIT_CODES = frozenset({-509, -412, -799, 412, 509, 799, 10403})

    # ── SocketIO 推送辅助 ──
    def _emit(self, event: str, data: dict):
        """安全推送事件到前端（SocketIO 可选）"""
        if self.socketio:
            try:
                self.socketio.emit(event, data)
            except Exception:
                pass

    # ── Cookie 初始化 ──
    def _init_cookie(self):
        cookie_str = self.config["bilibili"].get("cookie", "")
        refresh_token = self.config["bilibili"].get("refresh_token", "")
        if cookie_str:
            self.cookie_manager = BilibiliCookieManager(cookie_str, refresh_token, logger=self.logger)
            self.session.cookies.update(self.cookie_manager.session.cookies)
        elif os.path.exists(COOKIE_FILE):
            self.cookie_manager = BilibiliCookieManager(logger=self.logger)
            if self.cookie_manager.load_from_file(COOKIE_FILE):
                self.session.cookies.update(self.cookie_manager.session.cookies)
        if self.cookie_manager:
            self.csrf_token = self.cookie_manager._get_csrf_from_cookie()

    def reload_config(self, config: dict):
        """热更新配置"""
        self.config = config
        self.cookie_refresh_interval = config["bilibili"].get("cookie_refresh_interval", 30) * 60
        self.auto_refresh_cookie = config["bilibili"].get("auto_refresh_cookie", True)
        rl = config.get("rate_limit", {})
        self.min_request_interval = rl.get("min_request_interval", 2.0)
        self.max_retries = rl.get("max_retries", 3)
        self.retry_delay = rl.get("retry_delay", 5)
        self.adaptive_interval = self.min_request_interval
        vc = config.get("video_cache", {})
        self.video_cache_expire_time = vc.get("expire_time", 43200)
        # 刷新缓存设置（旧缓存最终会超时，但 expire_time 需立即生效）
        self.cache_expire_time = config.get("cache", {}).get("expire_time", 300)
        self.cache = {}  # 清空缓存让新配置立即生效
        # 重新初始化 Cookie
        self._init_cookie()

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return False
        self._running = True
        self._stop_event.clear()
        self.stats["start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.logger.info("机器人已启动")
        self._emit("bot_status", {"running": True})
        return True

    def stop(self):
        if not self._running:
            return False
        self._running = False
        self._stop_event.set()
        self.logger.info("机器人已停止")
        self._emit("bot_status", {"running": False})
        # 刷出历史记录和 Cookie
        self._flush_history()
        if self.cookie_manager:
            try:
                self.cookie_manager.save_to_file(COOKIE_FILE)
            except Exception:
                pass
        return True

    def _run_loop(self):
        while self._running:
            self.stats["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                self.process_comments()
            except Exception as e:
                self.logger.error(f"处理评论异常: {e}", exc_info=True)
            self._emit("stats", self.get_stats())
            interval = max(1, int(self.config["bilibili"].get("check_interval", 60)))
            self.logger.info(f"等待 {interval} 秒后进行下次检查")
            # 使用 Event.wait() 可被停止信号立即唤醒，避免循环 sleep
            self._stop_event.wait(timeout=interval)

    def update_headers(self):
        self.session.headers.update({
            "User-Agent": random.choice(self.user_agents),
            "Referer": random.choice(self.referers),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        })

    # ── APP 端参数常量 ──
    _APP_COMMON_PARAMS = {
        "build": "2001100",
        "version": "2.0.1",
        "mobi_app": "android_hd",
        "platform": "android",
        "channel": "master",
        "c_locale": "zh_CN",
        "s_locale": "zh_CN",
        "statistics": '{"appId":5,"platform":3,"version":"2.0.1","abtest":""}',
        "qn": "80",
    }

    _APP_USER_AGENTS = [
        "Mozilla/5.0 BiliDroid/8.43.0 (bbcallen@gmail.com) os/android model/android mobi_app/android build/8430300 channel/master innerVer/8430300 osVer/15 network/2",
        "Mozilla/5.0 BiliDroid/8.42.0 (bbcallen@gmail.com) os/android model/android mobi_app/android build/8420300 channel/master innerVer/8420300 osVer/14 network/2",
        "Mozilla/5.0 BiliDroid/8.43.0 (bbcallen@gmail.com) os/android model/android_hd mobi_app/android_hd build/2001100 channel/master innerVer/2001100 osVer/15 network/2",
    ]

    _APP_BASE_HEADERS = {
        "env": "prod",
        "app-key": "android64",
        "x-bili-aurora-zone": "sh001",
        "bili-http-engine": "cronet",
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    def _make_app_headers(self) -> dict:
        headers = dict(self._APP_BASE_HEADERS)
        headers["User-Agent"] = random.choice(self._APP_USER_AGENTS)
        return headers

    def _app_sign(self, params: dict) -> dict:
        signed = dict(params)
        signed["appkey"] = "dfca71928277209b"
        signed["ts"] = str(int(time.time()))
        sorted_keys = sorted(signed.keys())
        raw = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(signed[k]), safe='')}"
            for k in sorted_keys
        )
        appsec = "b5475a8825547a4fc26c7d518eaaa02e"
        signed["sign"] = hashlib.md5((raw + appsec).encode()).hexdigest()
        return signed

    # ── 缓存 ──
    def get_cache_key(self, url: str, params: dict = None) -> str:
        cache_data = f"{url}_{str(sorted(params.items()) if params else '')}"
        return hashlib.md5(cache_data.encode()).hexdigest()

    def get_from_cache(self, key: str) -> Optional[dict]:
        if key in self.cache:
            data, ts = self.cache[key]
            if time.time() - ts < self.cache_expire_time:
                return data
            del self.cache[key]
        return None

    def set_cache(self, key: str, data: dict):
        self.cache[key] = (data, time.time())

    # ── 请求带频率控制 ──
    def _is_bili_rate_limited(self, response) -> bool:
        if response.status_code == 429:
            return True
        try:
            ct = response.headers.get("Content-Type", "")
            if "json" not in ct:
                return False
            data = response.json()
            code = data.get("code", 0)
            if code in self.BILI_RATE_LIMIT_CODES:
                return True
            msg = data.get("message", "")
            if isinstance(msg, str) and ("过于频繁" in msg or "请求过于频繁" in msg or "访问被拒绝" in msg):
                return True
        except Exception:
            pass
        return False

    def rate_limit_request(self):
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if self.consecutive_failures > 0:
            self.adaptive_interval = min(
                self.min_request_interval * (2 ** self.consecutive_failures),
                self.min_request_interval * 10,
            )
        else:
            self.adaptive_interval = self.min_request_interval
        if elapsed < self.adaptive_interval:
            sleep_time = self.adaptive_interval - elapsed + random.uniform(0, 1.0)
            time.sleep(sleep_time)
        self.last_request_time = time.time()
        self.update_headers()

    def make_request_with_retry(self, method: str, url: str, use_cache: bool = True, **kwargs) -> Optional[requests.Response]:
        if use_cache and method.upper() == "GET":
            cache_key = self.get_cache_key(url, kwargs.get("params"))
            cached = self.get_from_cache(cache_key)
            if cached:
                return CachedResponse(cached)

        for attempt in range(self.max_retries):
            try:
                self.rate_limit_request()
                response = self.session.request(method, url, timeout=15, **kwargs)
                if self._is_bili_rate_limited(response):
                    self.consecutive_failures += 1
                    if attempt < self.max_retries - 1:
                        retry_after = response.headers.get("Retry-After", "")
                        if retry_after.isdigit():
                            wait = int(retry_after)
                        else:
                            wait = max(self.retry_delay * (2 ** attempt), self.min_request_interval * (2 + attempt))
                        wait += random.uniform(0, 2)
                        self.logger.warning(
                            f"请求频率限制 [{url}], 等待 {wait:.1f}s 后重试 "
                            f"(attempt {attempt + 1}/{self.max_retries}, "
                            f"failures: {self.consecutive_failures})"
                        )
                        time.sleep(wait)
                        continue
                elif response.status_code >= 500:
                    self.consecutive_failures += 1
                    if attempt < self.max_retries - 1:
                        wait = self.retry_delay * (2 ** attempt) + random.uniform(0, 2)
                        time.sleep(wait)
                        continue
                else:
                    self.consecutive_failures = 0
                if not response.text:
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                        continue
                    return None
                if use_cache and method.upper() == "GET" and response.status_code == 200:
                    try:
                        data = response.json()
                        self.set_cache(self.get_cache_key(url, kwargs.get("params")), data)
                    except Exception:
                        pass
                return response
            except requests.exceptions.RequestException as e:
                self.consecutive_failures += 1
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt) + random.uniform(0, 2))
                    continue
                self.logger.error(f"请求失败: {e}")
                return None
        return None

    # ── 历史记录 ──
    def load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
                self.processed_comments = set(item.get("comment_id") for item in history)
                self._history_buffer = history
                self.logger.info(f"加载历史记录，已处理 {len(self.processed_comments)} 条评论")
        except Exception as e:
            self.logger.error(f"加载历史记录失败: {e}")
            self.processed_comments = set()
            self._history_buffer = []

    def save_history(self, comment: Comment, reply_content: str):
        """追加到内存缓冲区，满 N 条后刷到磁盘"""
        try:
            item = {
                "comment_id": comment.comment_id,
                "content": comment.content,
                "user": comment.user,
                "uid": comment.uid,
                "time": comment.time,
                "reply_time": int(time.time()),
                "reply_content": reply_content,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._history_buffer.append(item)
            self._history_dirty = True
            self._emit("new_history", item)

            if len(self._history_buffer) % self._history_flush_interval == 0:
                self._flush_history()
        except Exception as e:
            self.logger.error(f"保存历史记录失败: {e}")

    def _flush_history(self):
        """将内存缓冲区写入磁盘（批量写，减少 I/O）"""
        if not self._history_dirty:
            return
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self._history_buffer, f, ensure_ascii=False, indent=2)
            self._history_dirty = False
        except Exception as e:
            self.logger.error(f"刷出历史记录失败: {e}")

    def get_history(self) -> list:
        """返回内存中的完整历史记录（比读文件快）"""
        return self._history_buffer

    # ── 视频缓存 ──
    def load_video_cache(self):
        try:
            if os.path.exists(self.video_cache_file):
                with open(self.video_cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                if isinstance(cache_data, dict):
                    self.cached_videos = cache_data.get("videos", [])
                    self.last_video_fetch_time = cache_data.get("fetch_time", 0)
                elif isinstance(cache_data, list):
                    self.cached_videos = cache_data
                    self.last_video_fetch_time = 0
                else:
                    self.cached_videos = []
                    self.last_video_fetch_time = 0
                age_h = (time.time() - self.last_video_fetch_time) / 3600
                self.logger.info(f"加载视频缓存，缓存{age_h:.1f}小时，共{len(self.cached_videos)}个视频")
        except Exception as e:
            self.logger.error(f"加载视频缓存失败: {e}")
            self.cached_videos = []

    def save_video_cache(self, videos: List[dict]):
        try:
            with open(self.video_cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "videos": videos,
                    "fetch_time": int(time.time()),
                    "fetch_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存视频缓存失败: {e}")

    def get_video_list(self) -> List[dict]:
        uid = self.config["bilibili"].get("uid")
        if not uid:
            self.logger.error("未配置uid")
            return []
        current_time = time.time()
        if self.cached_videos and (current_time - self.last_video_fetch_time) < self.video_cache_expire_time:
            self.logger.info(f"使用视频缓存，共{len(self.cached_videos)}个")
            return self.cached_videos
        self.logger.info("重新获取视频列表（APP API）...")
        max_pn = self.config["bilibili"].get("max_video_pages", 5)
        all_videos = []
        pn = 1
        url = "https://app.bilibili.com/x/v2/space/archive/cursor"
        inter_page_delay_base = max(self.min_request_interval * 1.2, 3.0)
        while pn <= max_pn:
            params = self._app_sign({"vmid": uid, "ps": 20, "pn": pn, "order": "pubdate", "sort": "desc", **self._APP_COMMON_PARAMS})
            try:
                if pn > 1:
                    extra_delay = inter_page_delay_base + random.uniform(0, 1.5)
                    self.logger.debug(f"视频列表页间延迟 {extra_delay:.1f}s（第{pn}页）")
                    time.sleep(extra_delay)
                response = self.make_request_with_retry(
                    "GET", url, params=params, use_cache=False,
                    headers=self._make_app_headers(),
                )
                if not response:
                    break
                data = response.json()
                if data.get("code") == 0:
                    items = data.get("data", {}).get("item", [])
                    if not items:
                        break
                    for item in items:
                        stat = item.get("stat") or {}
                        all_videos.append({
                            "bvid": item.get("bvid", ""),
                            "title": item.get("title", ""),
                            "desc": item.get("description") or item.get("title", ""),
                            "play": item.get("play") or stat.get("view", 0),
                            "comment": item.get("comment") or stat.get("reply", 0),
                        })
                    self.logger.info(f"第{pn}页获取到{len(items)}个视频，累计{len(all_videos)}个")
                    has_next = data.get("data", {}).get("has_next", True)
                    if not has_next or len(items) < 20:
                        break
                    pn += 1
                else:
                    error_code = data.get("code", 0)
                    error_msg = data.get("message", "")
                    self.logger.error(f"获取视频列表第{pn}页失败: code={error_code} msg={error_msg}")
                    if error_code in self.BILI_RATE_LIMIT_CODES or "过于频繁" in str(error_msg):
                        if all_videos:
                            self.logger.warning(
                                f"视频列表获取被频率限制，保留已取得的 {len(all_videos)} 个视频",
                            )
                            self._partial_save_video_cache(all_videos, current_time)
                        else:
                            self.logger.warning("视频列表被频率限制且无已获取数据，将使用过期缓存")
                        break
                    break
            except Exception as e:
                self.logger.error(f"获取视频列表异常: {e}")
                break
        if all_videos:
            self.cached_videos = all_videos
            self.last_video_fetch_time = current_time
            self.save_video_cache(all_videos)
            self._emit("video_list", {"count": len(all_videos), "videos": all_videos[:20]})
            return all_videos
        if self.cached_videos:
            cache_age_h = (current_time - self.last_video_fetch_time) / 3600
            self.logger.warning(
                f"获取视频列表失败，回退到过期缓存（{cache_age_h:.1f}小时前，{len(self.cached_videos)}个视频）"
            )
        return self.cached_videos

    def _partial_save_video_cache(self, videos: List[dict], fetch_time: float):
        try:
            self.cached_videos = videos
            self.last_video_fetch_time = fetch_time
            self.save_video_cache(videos)
            self._emit("video_list", {"count": len(videos), "videos": videos[:20]})
        except Exception as e:
            self.logger.error(f"保存部分视频缓存失败: {e}")

    # ── BVID ↔ AID 互转 ──
    _BV_REVERSE = {c: i for i, c in enumerate(_BV_TABLE)}

    def bvid_to_aid(self, bvid: str) -> str:
        if not bvid or not bvid.startswith("BV"):
            return ""
        try:
            bvid_arr = list(bvid[3:])
            bvid_arr[0], bvid_arr[6] = bvid_arr[6], bvid_arr[0]
            bvid_arr[1], bvid_arr[4] = bvid_arr[4], bvid_arr[1]
            tmp = 0
            for char in bvid_arr:
                idx = self._BV_REVERSE.get(char)
                if idx is None:
                    return ""
                tmp = tmp * self._BV_BASE + idx
            return str((tmp & self._BV_MASK) ^ self._BV_XOR)
        except Exception:
            return ""

    # ── 评论获取 ──
    def get_video_comments(self, bvid: str) -> List[Comment]:
        url = "https://api.bilibili.com/x/v2/reply"
        aid = self.bvid_to_aid(bvid)
        if not aid:
            return []

        chained_reply_enabled = self.config["reply"].get("chained_reply_enabled", True)
        max_reply_depth = self.config["reply"].get("max_reply_depth", 3)

        all_comments = []
        seen_ids = set()
        pn = 1
        max_pn = self.config["bilibili"].get("max_comment_pages", 10)
        page_size = 20

        while pn <= max_pn:
            params = {"type": 1, "oid": aid, "pn": pn, "ps": page_size, "sort": 2}
            try:
                response = self.make_request_with_retry("GET", url, params=params)
                if not response:
                    break
                data = response.json()
                if data.get("code") == 0:
                    replies = data.get("data", {}).get("replies", [])
                    if not replies:
                        break

                    for r in replies:
                        cid = str(r["rpid"])
                        if cid in seen_ids:
                            continue
                        seen_ids.add(cid)

                        main_comment = Comment(
                            comment_id=cid,
                            content=r["content"]["message"],
                            user=r["member"]["uname"],
                            uid=str(r["member"]["mid"]),
                            time=r["ctime"],
                            depth=0,
                        )
                        all_comments.append(main_comment)

                        if chained_reply_enabled:
                            self.logger.debug(f"检查评论 {main_comment.comment_id} 的子评论...")
                            child_replies = self.get_comment_replies(
                                bvid,
                                main_comment.comment_id,
                                max_depth=max_reply_depth - 1,
                            )
                            if child_replies:
                                filtered_children = [c for c in child_replies if c.comment_id not in seen_ids]
                                for c in filtered_children:
                                    seen_ids.add(c.comment_id)
                                self.logger.info(
                                    f"评论 {main_comment.comment_id} 有 {len(child_replies)} 条子评论"
                                    f"（去重后 {len(filtered_children)} 条）"
                                )
                                all_comments.extend(filtered_children)
                                main_comment.children = filtered_children

                    if len(replies) < page_size:
                        break
                    pn += 1
                else:
                    err = data.get("message", "")
                    if "ps out of bounds" in err and pn == 1 and page_size > 10:
                        page_size = 10
                        continue
                    break
            except Exception as e:
                self.logger.error(f"获取评论异常: {e}")
                break

        if chained_reply_enabled:
            main_count = sum(1 for c in all_comments if c.depth == 0)
            child_count = len(all_comments) - main_count
            self.logger.info(f"共获取 {main_count} 条主评论和 {child_count} 条子评论")

        return all_comments

    def get_comment_replies(self, bvid: str, root_comment_id: str, max_depth: int = 2, current_depth: int = 1) -> List[Comment]:
        if current_depth > max_depth:
            return []

        url = "https://api.bilibili.com/x/v2/reply/reply"
        aid = self.bvid_to_aid(bvid)
        if not aid:
            return []

        all_replies = []
        pn = 1
        page_size = 10

        while True:
            params = {"type": 1, "oid": aid, "root": root_comment_id, "pn": pn, "ps": page_size}
            try:
                response = self.make_request_with_retry("GET", url, params=params)
                if not response:
                    break

                data = response.json()
                if data.get("code") != 0:
                    break

                replies_data = data.get("data", {}).get("replies", [])
                if not replies_data:
                    break

                for r in replies_data:
                    child_comment = Comment(
                        comment_id=str(r["rpid"]),
                        content=r["content"]["message"],
                        user=r["member"]["uname"],
                        uid=str(r["member"]["mid"]),
                        time=r["ctime"],
                        parent_id=root_comment_id,
                        root_id=root_comment_id,
                        depth=current_depth,
                    )

                    if current_depth < max_depth:
                        grandchildren = self.get_comment_replies(
                            bvid,
                            child_comment.comment_id,
                            max_depth,
                            current_depth + 1,
                        )
                        child_comment.children = grandchildren

                    all_replies.append(child_comment)

                page_info = data.get("data", {}).get("page", {})
                if page_info.get("count", 0) <= pn * page_size:
                    break
                pn += 1

            except Exception as e:
                self.logger.error(f"获取子评论异常: {e}")
                break

        return all_replies

    # ── DeepSeek 回复生成 ──
    def generate_reply(self, comment: str, context: List[Comment] = None, video_title: str = None, video_desc: str = None) -> Optional[str]:
        api_config = self.config["deepseek"]
        headers = {"Authorization": f"Bearer {api_config['api_key']}", "Content-Type": "application/json"}
        system_prompt = api_config.get("system_prompt", "你是一个友善的B站UP主，请对评论做出自然、友好的回复。控制在100字以内。")
        messages = [{"role": "system", "content": system_prompt}]
        video_context = ""
        if video_title or video_desc:
            video_context = "视频信息：\n"
            if video_title:
                video_context += f"标题：{video_title}\n"
            if video_desc:
                video_context += f"简介：{video_desc}\n"
        if context or video_context:
            ctx_text = video_context
            if context:
                ctx_text += "前面的评论上下文（已回复的历史评论，仅供参考，请勿回复这些历史评论）：\n"
                for i, c in enumerate(context, 1):
                    ctx_text += f"{i}. {c.user}: {c.content}\n"
            messages.append({"role": "user", "content": ctx_text.strip()})
        messages.append({"role": "user", "content": comment})
        data = {
            "model": api_config["model"],
            "messages": messages,
            "max_tokens": api_config["max_tokens"],
            "temperature": api_config["temperature"],
        }
        try:
            # 使用 bot 的 session（复用连接池），失败时重试
            max_attempts = max(1, self.config.get("rate_limit", {}).get("max_retries", 3))
            for attempt in range(max_attempts):
                try:
                    response = self.session.post(
                        f"{api_config['base_url']}/chat/completions",
                        headers=headers, json=data, timeout=30,
                    )
                    if response.status_code == 200:
                        return response.json()["choices"][0]["message"]["content"].strip()
                    self.logger.error(f"DeepSeek API失败: {response.status_code} {response.text[:200]}")
                    if attempt < max_attempts - 1:
                        wait = self.retry_delay * (2 ** attempt) + random.uniform(0, 2)
                        self.logger.warning(f"DeepSeek API重试 ({attempt+1}/{max_attempts}) 等待 {wait:.1f}s")
                        time.sleep(wait)
                        continue
                    return None
                except requests.exceptions.RequestException as e:
                    self.logger.error(f"DeepSeek API请求异常: {e}")
                    if attempt < max_attempts - 1:
                        wait = self.retry_delay * (2 ** attempt) + random.uniform(0, 2)
                        time.sleep(wait)
                        continue
                    return None
        except Exception as e:
            self.logger.error(f"DeepSeek API异常: {e}")
            return None

    # ── 评论点赞 ──
    def like_comment(self, bvid: str, comment_id: str) -> bool:
        if self.cookie_manager:
            self.csrf_token = self.cookie_manager._get_csrf_from_cookie()
        if not self.csrf_token:
            return False
        url = "https://api.bilibili.com/x/v2/reply/action"
        aid = self.bvid_to_aid(bvid)
        data = {"type": 1, "oid": aid, "rpid": comment_id, "action": 1, "csrf": self.csrf_token}
        try:
            response = self.make_request_with_retry("POST", url, data=data)
            if not response:
                return False
            result = response.json()
            return result.get("code") == 0
        except Exception:
            return False

    # ── 获取用户最新视频（APP API） ──
    def get_user_latest_video(self, uid: str) -> Optional[dict]:
        self.logger.debug(f"开始获取用户 {uid} 的最新视频...")
        url = "https://app.bilibili.com/x/v2/space/archive/cursor"
        params = self._app_sign({"vmid": uid, "ps": 1, "pn": 1, "order": "pubdate", "sort": "desc", **self._APP_COMMON_PARAMS})
        try:
            response = self.make_request_with_retry(
                "GET", url, params=params, use_cache=False,
                headers=self._make_app_headers(),
            )
            if not response:
                self.logger.warning(f"获取用户 {uid} 视频列表失败：请求无响应")
                return None
            data = response.json()
            if data.get("code") == 0:
                items = data.get("data", {}).get("item", [])
                if items:
                    video = items[0]
                    stat = video.get("stat") or {}
                    result = {
                        "bvid": video.get("bvid", ""),
                        "title": video.get("title", ""),
                        "play": video.get("play") or stat.get("view", 0),
                        "comment": video.get("comment") or stat.get("reply", 0),
                    }
                    self.logger.debug(
                        f"成功获取用户 {uid} 的最新视频: {result.get('title', 'N/A')} ({result.get('bvid', 'N/A')})"
                    )
                    return result
                self.logger.warning(f"用户 {uid} 没有视频")
            else:
                error_code = data.get("code", 0)
                error_msg = data.get("message", "")
                if error_code in self.BILI_RATE_LIMIT_CODES or "过于频繁" in str(error_msg):
                    self.logger.warning(f"获取用户 {uid} 视频列表被频率限制: code={error_code} msg={error_msg}")
                else:
                    self.logger.warning(f"获取用户 {uid} 视频列表失败: code={error_code} msg={error_msg}")
            return None
        except Exception as e:
            self.logger.error(f"获取用户 {uid} 最新视频异常: {e}", exc_info=True)
            return None

    def like_video(self, bvid: str) -> bool:
        self.logger.debug(f"开始点赞视频: {bvid}")
        aid = self.bvid_to_aid(bvid)
        if not aid:
            self.logger.error(f"点赞视频失败: 无法转换 BVID {bvid} 到 AID")
            return False
        url = "https://app.bilibili.com/x/v2/view/like"
        data = self._app_sign({"aid": aid, "like": "1"})
        try:
            response = self.make_request_with_retry(
                "POST", url, data=data,
                headers=self._make_app_headers(),
            )
            if not response:
                self.logger.warning(f"点赞视频失败: 请求无响应")
                return False
            result = response.json()
            code = result.get("code")
            message = result.get("message", "未知错误")
            if code == 0:
                self.logger.info(f"✓ 成功点赞视频: {bvid}")
                return True
            self.logger.warning(f"点赞视频失败: code={code}, message={message}")
            return False
        except Exception as e:
            self.logger.error(f"点赞视频异常: {e}", exc_info=True)
            return False

    def check_is_follower(self, follower_uid: str, following_uid: str) -> bool:
        self.logger.debug(f"检查用户 {follower_uid} 是否关注 {following_uid}...")
        url = "https://api.bilibili.com/x/relation/same/followers"
        params = {"vmid": following_uid, "mid": follower_uid}
        try:
            response = self.make_request_with_retry("GET", url, params=params, use_cache=False)
            if not response:
                self.logger.warning(f"检查粉丝关系失败: 请求无响应")
                return False
            data = response.json()
            code = data.get("code")
            if code == 0:
                following = data.get("data", {}).get("following", False)
                self.logger.debug(f"用户 {follower_uid} 关注状态: {following}")
                return following
            message = data.get("message", "未知错误")
            self.logger.warning(f"检查粉丝关系失败: code={code}, message={message}")
            return False
        except Exception as e:
            self.logger.error(f"检查粉丝关系异常: {e}", exc_info=True)
            return False

    def reply_comment(self, bvid: str, comment_id: str, content: str, root_id: str = None, parent_id: str = None) -> bool:
        if self.cookie_manager:
            self.csrf_token = self.cookie_manager._get_csrf_from_cookie()
        if not self.csrf_token:
            self.logger.error("未找到CSRF token")
            return False
        if self.cookie_manager:
            is_valid, result = self.cookie_manager.verify_cookie()
            if not is_valid:
                self.logger.error(f"Cookie无效: {result.get('message')}")
                return False

        url = "https://api.bilibili.com/x/v2/reply/add"
        aid = self.bvid_to_aid(bvid)
        prefix = self.config["reply"].get("prefix", "")

        root = root_id if root_id else comment_id
        parent = parent_id if parent_id else comment_id

        data = {"type": 1, "oid": aid, "root": root, "parent": parent, "message": f"{prefix}{content}", "csrf": self.csrf_token}

        reply_type = "楼中楼回复" if root_id else "主评论回复"
        self.logger.debug(f"{reply_type}: bvid={bvid}, root={root}, parent={parent}, comment_id={comment_id}")

        try:
            response = self.make_request_with_retry("POST", url, data=data)
            if not response:
                return False
            result = response.json()
            if result.get("code") == 0:
                self.logger.info(f"回复成功: {comment_id} (类型: {reply_type})")
                return True
            self.logger.error(f"回复失败: {result.get('message')}")
            return False
        except Exception as e:
            self.logger.error(f"回复异常: {e}")
            return False

    def refresh_cookie_if_needed(self):
        if not self.cookie_manager or not self.cookie_manager.refresh_token:
            return
        current_time = time.time()
        if current_time - self.last_cookie_refresh_time < self.cookie_refresh_interval:
            return
        need_refresh, result = self.cookie_manager.auto_refresh_if_needed()
        if need_refresh and result.get("success"):
            self.session.cookies.update(self.cookie_manager.session.cookies)
            self.csrf_token = self.cookie_manager._get_csrf_from_cookie()
            new_rt = result.get("new_refresh_token")
            if new_rt:
                self.config["bilibili"]["refresh_token"] = new_rt
                if self.on_config_changed:
                    self.on_config_changed(new_rt)
        self.last_cookie_refresh_time = current_time

    # ── 主处理循环 ──
    def process_comments(self):
        if self.auto_refresh_cookie:
            self.refresh_cookie_if_needed()
        if not self.config["reply"].get("enabled", True):
            return

        only_bvid = self.config["reply"].get("only_bvid", "").strip()
        if only_bvid:
            self.logger.info(f"仅回复指定视频: {only_bvid}")
            video_title = f"指定视频({only_bvid})"
            videos = [{"bvid": only_bvid, "title": video_title, "desc": ""}]
        else:
            videos = self.get_video_list()
            if not videos:
                self.logger.warning("未获取到视频列表")
                return

        max_process = self.config["reply"].get("max_process", 10)
        context_count = self.config["reply"].get("context_comments_count", 0)
        processed_count = 0
        my_uid = self.config["bilibili"].get("uid", "")

        for video in videos:
            if processed_count >= max_process:
                break
            bvid = video["bvid"]
            title = video.get("title", "")
            self.logger.info(f"处理视频: {title} ({bvid})")
            comments = self.get_video_comments(bvid)

            for idx, comment in enumerate(comments):
                if processed_count >= max_process:
                    break
                if comment.comment_id in self.processed_comments:
                    continue

                # 立即标记，防止重复
                self.processed_comments.add(comment.comment_id)

                # 跳过自己的评论
                if my_uid and comment.uid == my_uid:
                    self.logger.debug(f"跳过自己的评论: {comment.comment_id}")
                    continue

                # 应用过滤器（关键词、长度、用户黑白名单）
                passed, reason = self._check_filters(comment)
                if not passed:
                    self.logger.debug(f"跳过评论 {comment.comment_id}: {reason}")
                    continue

                self.logger.info(f"处理评论: [{comment.user}] {comment.content[:40]}... (深度: {comment.depth})")

                # 构建上下文
                context = []
                if comment.depth > 0 and comment.parent_id:
                    parent_comment = next((c for c in comments if c.comment_id == comment.parent_id), None)
                    if parent_comment:
                        context.append(parent_comment)
                        self.logger.debug(f"添加父评论到上下文: [{parent_comment.user}] {parent_comment.content[:30]}...")

                if context_count > 0 and idx > 0:
                    start_idx = max(0, idx - context_count)
                    for i in range(start_idx, idx):
                        if comments[i].comment_id != comment.parent_id:
                            context.append(comments[i])

                reply = self.generate_reply(comment.content, context, title, video.get("desc", ""))
                if not reply:
                    self.logger.warning(f"生成回复失败，跳过评论 {comment.comment_id}")
                    continue

                if self.config["reply"].get("like_enabled", False):
                    self.like_comment(bvid, comment.comment_id)

                is_child_comment = comment.depth > 0 and comment.root_id is not None

                if is_child_comment:
                    if not comment.root_id:
                        self.logger.error(f"楼中楼回复失败：根评论ID为空 (comment_id={comment.comment_id})")
                        continue
                    self.logger.info(f"楼中楼回复: 根评论={comment.root_id}, 当前评论={comment.comment_id}")
                    if self.reply_comment(bvid, comment.comment_id, reply, root_id=comment.root_id):
                        self.logger.info(f"楼中楼回复成功: {comment.comment_id}")
                        self.processed_comments.add(comment.comment_id)
                        self.save_history(comment, reply)
                    continue
                else:
                    # 主评论回复
                    if not self.reply_comment(bvid, comment.comment_id, reply):
                        continue
                    self.processed_comments.add(comment.comment_id)
                    self.save_history(comment, reply)
                    processed_count += 1
                    self.stats["total_replied"] += 1

                    # 点赞评论用户的最新视频
                    if self.config["reply"].get("like_user_video_enabled", False):
                        self.logger.info(f"[点赞视频] 配置已启用，准备点赞用户 {comment.user} (UID: {comment.uid}) 的最新视频")
                        only_followers = self.config["reply"].get("like_user_video_only_followers", False)

                        skip_like = False
                        if only_followers:
                            my_uid = self.config["bilibili"].get("uid")
                            if my_uid:
                                is_follower = self.check_is_follower(comment.uid, my_uid)
                                if not is_follower:
                                    self.logger.info(f"[点赞视频] 用户 {comment.user} 未关注你，跳过点赞视频")
                                    skip_like = True
                            else:
                                self.logger.warning("[点赞视频] 未配置 uid，无法检查粉丝关系，跳过点赞视频")
                                skip_like = True

                        if not skip_like:
                            latest_video = self.get_user_latest_video(comment.uid)
                            if latest_video:
                                if self.like_video(latest_video["bvid"]):
                                    self.logger.info(f"[点赞视频] ✓ 成功点赞用户 {comment.user} 的最新视频")
                                else:
                                    self.logger.warning(f"[点赞视频] ✗ 点赞用户 {comment.user} 的最新视频失败")
                            else:
                                self.logger.warning(f"[点赞视频] 用户 {comment.user} 没有视频或获取失败")

                    delay = self.config["reply"].get("reply_delay", 2)
                    if delay > 0:
                        time.sleep(delay)

    def _check_filters(self, comment: Comment) -> tuple:
        """检查评论是否通过所有过滤器。返回 (通过, 跳过原因)"""
        # ── 长度过滤 ──
        lf = self.config["reply"].get("length_filter", {})
        if lf.get("enabled", False):
            min_len = lf.get("min_length", 0)
            max_len = lf.get("max_length", 500)
            content_len = len(comment.content)
            if min_len > 0 and content_len < min_len:
                return False, f"评论长度 {content_len} < {min_len}"
            if max_len > 0 and content_len > max_len:
                return False, f"评论长度 {content_len} > {max_len}"

        # ── 关键词过滤 ──
        kf = self.config["reply"].get("keyword_filter", {})
        if kf.get("enabled", False):
            wl_str = kf.get("whitelist", "").strip()
            bl_str = kf.get("blacklist", "").strip()
            match_case = kf.get("match_case", False)
            content = comment.content if match_case else comment.content.lower()

            # 黑名单
            if bl_str:
                keywords = [k.strip() for k in bl_str.split(",") if k.strip()]
                if not match_case:
                    keywords = [k.lower() for k in keywords]
                for kw in keywords:
                    if kw in content:
                        return False, f"命中黑名单关键词: {kw}"

            # 白名单
            if wl_str:
                keywords = [k.strip() for k in wl_str.split(",") if k.strip()]
                if not match_case:
                    keywords = [k.lower() for k in keywords]
                mode = kf.get("mode", "any")
                if mode == "all":
                    if not all(kw in content for kw in keywords):
                        return False, "未包含所有白名单关键词"
                else:
                    if not any(kw in content for kw in keywords):
                        return False, "未包含任何白名单关键词"

        # ── 用户过滤 ──
        uf = self.config["reply"].get("user_filter", {})
        if uf.get("enabled", False):
            uid = comment.uid
            bl_str = uf.get("blacklist", "").strip()
            wl_str = uf.get("whitelist", "").strip()

            if bl_str:
                blacklist = [u.strip() for u in bl_str.split(",") if u.strip()]
                if uid in blacklist:
                    return False, f"用户 {uid} 在黑名单中"

            if wl_str:
                whitelist = [u.strip() for u in wl_str.split(",") if u.strip()]
                if uid not in whitelist:
                    return False, f"用户 {uid} 不在白名单中"

        return True, ""

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "total_replied": self.stats["total_replied"],
            "start_time": self.stats["start_time"],
            "last_check": self.stats["last_check"],
            "processed_count": len(self.processed_comments),
            "cached_videos": len(self.cached_videos),
        }

    def verify_login(self) -> dict:
        if not self.cookie_manager:
            return {"valid": False, "message": "未配置Cookie"}
        valid, result = self.cookie_manager.verify_cookie()
        return {"valid": valid, **result}
