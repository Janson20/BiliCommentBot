#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站评论自动回复机器人 - Web UI 版
启动后自动打开浏览器，所有功能通过 Web 界面操作
"""

import os
import sys
import time
import json
import logging
import threading
import webbrowser
import hashlib
import urllib.parse
import re
import random
import gzip
import zlib
import base64
import io
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import toml
import tomli_w

from flask import Flask, request, jsonify, render_template_string
from flask_socketio import SocketIO, emit

# ─────────────────────────────────────────────
#  全局常量
# ─────────────────────────────────────────────
CONFIG_FILE = "config.toml"
HISTORY_FILE = "history.json"
COOKIE_FILE = "bilibili_cookie.json"
VIDEO_CACHE_FILE = "video_cache.json"

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
        "min_request_interval": 2.0,
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
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
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
    },
    "logging": {
        "level": "INFO",
        "file": "logs/bot.log",
        "console": True,
    },
}

# ─────────────────────────────────────────────
#  Flask + SocketIO
# ─────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = "bilibot-secret-2024"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ─────────────────────────────────────────────
#  日志 Handler（推送到前端）
# ─────────────────────────────────────────────
class WebSocketLogHandler(logging.Handler):
    def __init__(self, sio: SocketIO):
        super().__init__()
        self.sio = sio
        self.log_buffer: List[dict] = []
        self.max_buffer = 500

    def emit(self, record: logging.LogRecord):
        entry = {
            "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            "level": record.levelname,
            "msg": self.format(record),
        }
        self.log_buffer.append(entry)
        if len(self.log_buffer) > self.max_buffer:
            self.log_buffer = self.log_buffer[-self.max_buffer:]
        try:
            self.sio.emit("log", entry)
        except Exception:
            pass


ws_log_handler = WebSocketLogHandler(socketio)
ws_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

# ─────────────────────────────────────────────
#  配置管理
# ─────────────────────────────────────────────
def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = toml.load(f)
        # 深度合并默认值
        def merge(base, override):
            result = dict(base)
            for k, v in override.items():
                if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                    result[k] = merge(result[k], v)
                else:
                    result[k] = v
            return result
        return merge(DEFAULT_CONFIG, cfg)
    except Exception as e:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: dict) -> bool:
    try:
        with open(CONFIG_FILE, "wb") as f:
            tomli_w.dump(cfg, f)
        return True
    except Exception as e:
        return False


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
            patterns = [
                r'"refresh_csrf"\s*:\s*"([^"]+)"',
                r"refresh_csrf\s*=\s*'([^']+)'",
                r"refresh_csrf\s*=\s*\"([^\"]+)\"",
            ]
            for pattern in patterns:
                match = re.search(pattern, html_content, re.IGNORECASE)
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


# ─────────────────────────────────────────────
#  机器人核心
# ─────────────────────────────────────────────
class BiliCommentBot:
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
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

        # Cookie管理器
        self.cookie_manager: Optional[BilibiliCookieManager] = None
        self.csrf_token: Optional[str] = None
        self.last_cookie_refresh_time = 0
        self.cookie_refresh_interval = self.config["bilibili"].get("cookie_refresh_interval", 30) * 60
        self.auto_refresh_cookie = self.config["bilibili"].get("auto_refresh_cookie", True)
        self._init_cookie()

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
        self.video_cache_file = vc.get("cache_file", VIDEO_CACHE_FILE)
        self.video_cache_expire_time = vc.get("expire_time", 43200)
        self.load_video_cache()

        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # 统计
        self.stats = {"total_replied": 0, "start_time": None, "last_check": None}

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
        # 重新初始化Cookie
        self._init_cookie()

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return False
        self._running = True
        self.stats["start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.logger.info("机器人已启动")
        socketio.emit("bot_status", {"running": True})
        return True

    def stop(self):
        if not self._running:
            return False
        self._running = False
        self.logger.info("机器人已停止")
        socketio.emit("bot_status", {"running": False})
        # 保存Cookie
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
            socketio.emit("stats", self.get_stats())
            interval = self.config["bilibili"].get("check_interval", 60)
            self.logger.info(f"等待 {interval} 秒后进行下次检查")
            # 分段sleep，方便快速响应停止
            for _ in range(interval * 10):
                if not self._running:
                    break
                time.sleep(0.1)

    def update_headers(self):
        self.session.headers.update({
            "User-Agent": random.choice(self.user_agents),
            "Referer": random.choice(self.referers),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        })

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

    def rate_limit_request(self):
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if self.consecutive_failures > 0:
            self.adaptive_interval = min(self.min_request_interval * (1 + self.consecutive_failures * 0.5), self.min_request_interval * 5)
        else:
            self.adaptive_interval = self.min_request_interval
        if elapsed < self.adaptive_interval:
            sleep_time = self.adaptive_interval - elapsed + random.uniform(0, 0.5)
            time.sleep(sleep_time)
        self.last_request_time = time.time()
        self.update_headers()

    def make_request_with_retry(self, method: str, url: str, use_cache: bool = True, **kwargs) -> Optional[requests.Response]:
        if use_cache and method.upper() == "GET":
            cache_key = self.get_cache_key(url, kwargs.get("params"))
            cached = self.get_from_cache(cache_key)
            if cached:
                class MockResponse:
                    def __init__(self, d):
                        self.status_code = 200
                        self.headers = {}
                        self.text = json.dumps(d)
                        self._json = d
                    def json(self):
                        return self._json
                return MockResponse(cached)

        for attempt in range(self.max_retries):
            try:
                self.rate_limit_request()
                response = self.session.request(method, url, timeout=15, **kwargs)
                if response.status_code == 429:
                    self.consecutive_failures += 1
                    if attempt < self.max_retries - 1:
                        wait = int(response.headers.get("Retry-After", self.retry_delay * (2 ** attempt))) + random.uniform(0, 3)
                        self.logger.warning(f"请求频繁，等待 {wait:.1f}s 后重试")
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
                        rt = self.decompress_response(response)
                        if rt:
                            data = json.loads(rt)
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

    def decompress_response(self, response) -> str:
        try:
            if hasattr(response, "text") and response.text:
                try:
                    response.text.encode("utf-8").decode("utf-8")
                    return response.text
                except Exception:
                    pass
            content = response.content if hasattr(response, "content") else response.text
            if not content:
                return ""
            if isinstance(content, bytes) and content[:2] == b"\x1f\x8b":
                try:
                    return gzip.decompress(content).decode("utf-8")
                except Exception:
                    pass
            try:
                return zlib.decompress(content).decode("utf-8")
            except Exception:
                pass
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="ignore")
            return str(content)
        except Exception:
            return getattr(response, "text", "")

    def load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
                self.processed_comments = set(item.get("comment_id") for item in history)
                self.logger.info(f"加载历史记录，已处理 {len(self.processed_comments)} 条评论")
        except Exception as e:
            self.logger.error(f"加载历史记录失败: {e}")
            self.processed_comments = set()

    def save_history(self, comment: Comment, reply_content: str):
        try:
            history = []
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                        history = json.load(f)
                except Exception:
                    history = []
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
            history.append(item)
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            # 推送到前端
            socketio.emit("new_history", item)
        except Exception as e:
            self.logger.error(f"保存历史记录失败: {e}")

    def load_video_cache(self):
        try:
            if os.path.exists(self.video_cache_file):
                with open(self.video_cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                self.cached_videos = cache_data.get("videos", [])
                self.last_video_fetch_time = cache_data.get("fetch_time", 0)
                age_h = (time.time() - self.last_video_fetch_time) / 3600
                self.logger.info(f"加载视频缓存，缓存{age_h:.1f}小时，共{len(self.cached_videos)}个视频")
        except Exception as e:
            self.logger.error(f"加载视频缓存失败: {e}")
            self.cached_videos = []

    def save_video_cache(self, videos: List[dict]):
        try:
            with open(self.video_cache_file, "w", encoding="utf-8") as f:
                json.dump({"videos": videos, "fetch_time": int(time.time()), "fetch_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=2)
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
        self.logger.info("重新获取视频列表...")
        max_pn = self.config["bilibili"].get("max_video_pages", 5)
        all_videos = []
        pn = 1
        url = "https://api.bilibili.com/x/space/arc/search"
        while pn <= max_pn:
            params = {"mid": uid, "ps": 20, "pn": pn, "order": "pubdate"}
            try:
                response = self.make_request_with_retry("GET", url, params=params, use_cache=False)
                if not response:
                    break
                rt = self.decompress_response(response)
                if not rt:
                    break
                data = json.loads(rt)
                if data.get("code") == 0:
                    page_videos = data.get("data", {}).get("list", {}).get("vlist", [])
                    if not page_videos:
                        break
                    all_videos.extend(page_videos)
                    self.logger.info(f"第{pn}页获取到{len(page_videos)}个视频，累计{len(all_videos)}个")
                    if len(page_videos) < 20:
                        break
                    pn += 1
                else:
                    self.logger.error(f"获取视频列表失败: {data.get('message')}")
                    break
            except Exception as e:
                self.logger.error(f"获取视频列表异常: {e}")
                break
        if all_videos:
            self.cached_videos = all_videos
            self.last_video_fetch_time = current_time
            self.save_video_cache(all_videos)
            socketio.emit("video_list", {"count": len(all_videos), "videos": all_videos[:20]})
            return all_videos
        return self.cached_videos

    def bvid_to_aid(self, bvid: str) -> str:
        url = "https://api.bilibili.com/x/web-interface/view"
        try:
            response = self.make_request_with_retry("GET", url, params={"bvid": bvid})
            if not response:
                return ""
            rt = self.decompress_response(response)
            data = json.loads(rt)
            if data.get("code") == 0:
                return str(data.get("data", {}).get("aid", ""))
            return ""
        except Exception:
            return ""

    def get_video_comments(self, bvid: str) -> List[Comment]:
        url = "https://api.bilibili.com/x/v2/reply"
        aid = self.bvid_to_aid(bvid)
        if not aid:
            return []
        all_comments = []
        pn = 1
        max_pn = self.config["bilibili"].get("max_comment_pages", 10)
        page_size = 20
        while pn <= max_pn:
            params = {"type": 1, "oid": aid, "pn": pn, "ps": page_size, "sort": 2}
            try:
                response = self.make_request_with_retry("GET", url, params=params)
                if not response:
                    break
                rt = self.decompress_response(response)
                data = json.loads(rt)
                if data.get("code") == 0:
                    replies = data.get("data", {}).get("replies", [])
                    if not replies:
                        break
                    for r in replies:
                        all_comments.append(Comment(
                            comment_id=str(r["rpid"]),
                            content=r["content"]["message"],
                            user=r["member"]["uname"],
                            uid=str(r["member"]["mid"]),
                            time=r["ctime"],
                        ))
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
        return all_comments

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
                ctx_text += "前面的评论上下文：\n"
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
            response = requests.post(f"{api_config['base_url']}/chat/completions", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"].strip()
            self.logger.error(f"DeepSeek API失败: {response.status_code} {response.text[:200]}")
            return None
        except Exception as e:
            self.logger.error(f"DeepSeek API异常: {e}")
            return None

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
            result = json.loads(self.decompress_response(response))
            return result.get("code") == 0
        except Exception:
            return False

    def reply_comment(self, bvid: str, comment_id: str, content: str) -> bool:
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
        data = {"type": 1, "oid": aid, "root": comment_id, "parent": comment_id, "message": f"{prefix}{content}", "csrf": self.csrf_token}
        try:
            response = self.make_request_with_retry("POST", url, data=data)
            if not response:
                return False
            result = json.loads(self.decompress_response(response))
            if result.get("code") == 0:
                self.logger.info(f"回复成功: {comment_id}")
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
                save_config(self.config)
            self.cookie_manager.save_to_file(COOKIE_FILE)
            self.logger.info("Cookie自动刷新成功")
        self.last_cookie_refresh_time = current_time

    def process_comments(self):
        if self.auto_refresh_cookie:
            self.refresh_cookie_if_needed()
        if not self.config["reply"].get("enabled", True):
            return
        videos = self.get_video_list()
        if not videos:
            self.logger.warning("未获取到视频列表")
            return
        max_process = self.config["reply"].get("max_process", 10)
        context_count = self.config["reply"].get("context_comments_count", 0)
        processed_count = 0
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
                self.logger.info(f"处理评论: [{comment.user}] {comment.content[:40]}...")
                context = []
                if context_count > 0 and idx > 0:
                    context = comments[max(0, idx - context_count):idx]
                reply = self.generate_reply(comment.content, context, title, video.get("desc", ""))
                if reply:
                    if self.config["reply"].get("like_enabled", False):
                        self.like_comment(bvid, comment.comment_id)
                    if self.reply_comment(bvid, comment.comment_id, reply):
                        self.processed_comments.add(comment.comment_id)
                        self.save_history(comment, reply)
                        processed_count += 1
                        self.stats["total_replied"] += 1
                        delay = self.config["reply"].get("reply_delay", 2)
                        if delay > 0:
                            time.sleep(delay)
                else:
                    self.logger.warning(f"生成回复失败，跳过评论 {comment.comment_id}")

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


# ─────────────────────────────────────────────
#  扫码登录
# ─────────────────────────────────────────────
BILI_QR_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
BILI_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
BILI_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36", "Referer": "https://www.bilibili.com"}

_qr_session: Optional[requests.Session] = None
_qr_key: Optional[str] = None
_qr_thread: Optional[threading.Thread] = None


def _gen_qr_image_base64(url: str) -> str:
    """生成二维码图片并返回base64字符串"""
    import qrcode
    from PIL import Image
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _poll_qr_login(qr_key: str, session: requests.Session):
    """后台线程：轮询二维码登录状态"""
    global _qr_session, _qr_key
    params = {"qrcode_key": qr_key}
    timeout = 180
    start = time.time()
    last_code = None
    while time.time() - start < timeout:
        try:
            resp = session.get(BILI_QR_POLL, params=params, headers=BILI_HEADERS, timeout=10)
            data = resp.json()["data"]
            code = data["code"]
            if code != last_code:
                last_code = code
                msg_map = {86101: "等待扫码...", 86090: "已扫码，请在手机确认", 86038: "二维码已失效", 0: "登录成功！"}
                socketio.emit("qr_status", {"code": code, "message": msg_map.get(code, str(code))})
            if code == 0:
                cookies = dict(session.cookies)
                if data.get("url"):
                    from urllib.parse import urlparse, parse_qs
                    qs = parse_qs(urlparse(data["url"]).query)
                    for k, v in qs.items():
                        if k not in cookies:
                            cookies[k] = v[0]
                cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
                socketio.emit("qr_cookie", {"cookie": cookie_str, "cookies": cookies})
                return
            if code == 86038:
                return
        except Exception as e:
            socketio.emit("qr_status", {"code": -1, "message": f"请求错误: {e}"})
        time.sleep(1.5)
    socketio.emit("qr_status", {"code": -2, "message": "登录超时"})


# ─────────────────────────────────────────────
#  全局机器人实例
# ─────────────────────────────────────────────
_bot: Optional[BiliCommentBot] = None
_bot_logger: Optional[logging.Logger] = None


def get_bot() -> BiliCommentBot:
    global _bot, _bot_logger
    if _bot is None:
        cfg = load_config()
        _bot_logger = _setup_logger(cfg)
        _bot = BiliCommentBot(cfg, _bot_logger)
    return _bot


def _setup_logger(cfg: dict) -> logging.Logger:
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file", "logs/bot.log")
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("BiliBot")
    logger.setLevel(level)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    if log_cfg.get("console", True):
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(ch)
    logger.addHandler(ws_log_handler)
    return logger


# ─────────────────────────────────────────────
#  Flask 路由
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/config", methods=["GET"])
def api_get_config():
    cfg = load_config()
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "message": "无效数据"})
    cfg = load_config()
    # 深度更新
    def deep_update(base, upd):
        for k, v in upd.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                deep_update(base[k], v)
            else:
                base[k] = v
    deep_update(cfg, data)
    if save_config(cfg):
        # 热更新机器人配置
        bot = get_bot()
        bot.reload_config(cfg)
        return jsonify({"ok": True, "message": "配置已保存"})
    return jsonify({"ok": False, "message": "保存失败"})


@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    bot = get_bot()
    result = bot.start()
    return jsonify({"ok": result, "message": "已启动" if result else "已在运行中"})


@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    bot = get_bot()
    result = bot.stop()
    return jsonify({"ok": result, "message": "已停止" if result else "未在运行"})


@app.route("/api/bot/status", methods=["GET"])
def api_bot_status():
    bot = get_bot()
    return jsonify({"ok": True, **bot.get_stats()})


@app.route("/api/bot/verify", methods=["GET"])
def api_verify():
    bot = get_bot()
    return jsonify({"ok": True, **bot.verify_login()})


@app.route("/api/history", methods=["GET"])
def api_history():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            history.sort(key=lambda x: x.get("reply_time", 0), reverse=True)
            total = len(history)
            start = (page - 1) * per_page
            end = start + per_page
            return jsonify({"ok": True, "total": total, "page": page, "data": history[start:end]})
        return jsonify({"ok": True, "total": 0, "page": 1, "data": []})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        bot = get_bot()
        bot.processed_comments.clear()
        return jsonify({"ok": True, "message": "历史记录已清除"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


@app.route("/api/logs", methods=["GET"])
def api_logs():
    return jsonify({"ok": True, "logs": ws_log_handler.log_buffer[-200:]})


@app.route("/api/qr/generate", methods=["POST"])
def api_qr_generate():
    global _qr_session, _qr_key, _qr_thread
    try:
        _qr_session = requests.Session()
        resp = _qr_session.get(BILI_QR_GENERATE, headers=BILI_HEADERS, timeout=10)
        data = resp.json()
        if data["code"] != 0:
            return jsonify({"ok": False, "message": "获取二维码失败"})
        qr_url = data["data"]["url"]
        _qr_key = data["data"]["qrcode_key"]
        qr_b64 = _gen_qr_image_base64(qr_url)
        # 启动轮询线程
        _qr_thread = threading.Thread(target=_poll_qr_login, args=(_qr_key, _qr_session), daemon=True)
        _qr_thread.start()
        return jsonify({"ok": True, "qr_image": qr_b64})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


@app.route("/api/cache/clear", methods=["POST"])
def api_cache_clear():
    bot = get_bot()
    bot.cached_videos = []
    bot.last_video_fetch_time = 0
    if os.path.exists(VIDEO_CACHE_FILE):
        os.remove(VIDEO_CACHE_FILE)
    return jsonify({"ok": True, "message": "视频缓存已清除"})


@app.route("/api/videos", methods=["GET"])
def api_videos():
    bot = get_bot()
    return jsonify({"ok": True, "count": len(bot.cached_videos), "videos": bot.cached_videos[:50]})


# ─────────────────────────────────────────────
#  SocketIO 事件
# ─────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    bot = get_bot()
    emit("bot_status", {"running": bot.is_running})
    emit("stats", bot.get_stats())
    # 发送最近日志
    emit("log_history", {"logs": ws_log_handler.log_buffer[-100:]})


# ─────────────────────────────────────────────
#  HTML 模板（单页应用）
# ─────────────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>B站评论机器人</title>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #22263a;
    --border: #2e3250;
    --accent: #fb7299;
    --accent2: #23ade5;
    --green: #23c562;
    --yellow: #f6c90e;
    --red: #f05050;
    --text: #e8eaf6;
    --text2: #8b92b8;
    --radius: 10px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; }
  a { color: var(--accent2); text-decoration: none; }

  /* Layout */
  .app { display: flex; min-height: 100vh; }
  .sidebar {
    width: 220px; min-height: 100vh; background: var(--surface);
    border-right: 1px solid var(--border); display: flex; flex-direction: column;
    padding: 24px 0; position: fixed; top: 0; left: 0; bottom: 0;
  }
  .sidebar-logo { padding: 0 20px 24px; border-bottom: 1px solid var(--border); }
  .sidebar-logo .logo-title { font-size: 17px; font-weight: 700; color: var(--accent); }
  .sidebar-logo .logo-sub { font-size: 12px; color: var(--text2); margin-top: 4px; }
  .nav-list { list-style: none; margin-top: 16px; flex: 1; }
  .nav-list li a {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 20px; color: var(--text2); font-size: 14px;
    transition: all .2s; border-left: 3px solid transparent;
  }
  .nav-list li a:hover { background: var(--surface2); color: var(--text); }
  .nav-list li a.active { background: var(--surface2); color: var(--accent); border-left-color: var(--accent); }
  .nav-list li a .icon { font-size: 16px; width: 20px; text-align: center; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--red); display: inline-block; margin-left: auto; }
  .status-dot.running { background: var(--green); animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

  /* Main */
  .main { margin-left: 220px; flex: 1; padding: 32px; }

  /* Page sections */
  .page { display: none; }
  .page.active { display: block; }
  .page-title { font-size: 22px; font-weight: 700; margin-bottom: 24px; display: flex; align-items: center; gap: 10px; }
  .page-title .icon { color: var(--accent); }

  /* Cards */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; margin-bottom: 20px; }
  .card-title { font-size: 14px; font-weight: 600; color: var(--text2); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 16px; }

  /* Stats grid */
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
  .stat-value { font-size: 28px; font-weight: 700; color: var(--accent); }
  .stat-label { font-size: 12px; color: var(--text2); margin-top: 6px; }

  /* Buttons */
  .btn { display: inline-flex; align-items: center; gap: 6px; padding: 9px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 600; transition: all .2s; }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-primary:hover { filter: brightness(1.1); }
  .btn-success { background: var(--green); color: #fff; }
  .btn-success:hover { filter: brightness(1.1); }
  .btn-danger { background: var(--red); color: #fff; }
  .btn-danger:hover { filter: brightness(1.1); }
  .btn-secondary { background: var(--surface2); color: var(--text); border: 1px solid var(--border); }
  .btn-secondary:hover { background: var(--border); }
  .btn-info { background: var(--accent2); color: #fff; }
  .btn-info:hover { filter: brightness(1.1); }
  .btn:disabled { opacity: .5; cursor: not-allowed; }

  /* Forms */
  .form-group { margin-bottom: 18px; }
  .form-label { font-size: 13px; color: var(--text2); margin-bottom: 6px; display: block; font-weight: 500; }
  .form-input, .form-select, .form-textarea {
    width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 9px 12px; color: var(--text); font-size: 14px; transition: border .2s;
  }
  .form-input:focus, .form-select:focus, .form-textarea:focus { outline: none; border-color: var(--accent); }
  .form-textarea { resize: vertical; min-height: 90px; font-family: inherit; }
  .form-select { cursor: pointer; }
  .form-check { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .form-check input[type=checkbox] { width: 16px; height: 16px; accent-color: var(--accent); cursor: pointer; }
  .form-hint { font-size: 12px; color: var(--text2); margin-top: 4px; }
  .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .form-row-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }

  /* Tabs */
  .tab-bar { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 24px; }
  .tab-btn { padding: 10px 18px; background: none; border: none; color: var(--text2); cursor: pointer; font-size: 14px; border-bottom: 2px solid transparent; margin-bottom: -1px; transition: all .2s; }
  .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab-btn:hover:not(.active) { color: var(--text); }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* Log */
  .log-container {
    background: #080b12; border: 1px solid var(--border); border-radius: var(--radius);
    height: 420px; overflow-y: auto; padding: 12px; font-family: 'Consolas', monospace; font-size: 13px;
  }
  .log-entry { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,.03); }
  .log-entry .log-time { color: #4a5568; margin-right: 8px; }
  .log-entry.INFO .log-level { color: var(--accent2); }
  .log-entry.WARNING .log-level { color: var(--yellow); }
  .log-entry.ERROR .log-level { color: var(--red); }
  .log-entry.DEBUG .log-level { color: #6b7280; }

  /* Table */
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { padding: 10px 14px; text-align: left; color: var(--text2); font-weight: 600; border-bottom: 1px solid var(--border); white-space: nowrap; }
  td { padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,.05); }
  tr:hover td { background: rgba(255,255,255,.02); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .badge-green { background: rgba(35,197,98,.15); color: var(--green); }
  .badge-blue { background: rgba(35,173,229,.15); color: var(--accent2); }
  .badge-red { background: rgba(240,80,80,.15); color: var(--red); }

  /* Alert */
  .alert { padding: 12px 16px; border-radius: 8px; font-size: 14px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
  .alert-success { background: rgba(35,197,98,.1); border: 1px solid rgba(35,197,98,.3); color: var(--green); }
  .alert-danger { background: rgba(240,80,80,.1); border: 1px solid rgba(240,80,80,.3); color: var(--red); }
  .alert-info { background: rgba(35,173,229,.1); border: 1px solid rgba(35,173,229,.3); color: var(--accent2); }
  .alert-warning { background: rgba(246,201,14,.1); border: 1px solid rgba(246,201,14,.3); color: var(--yellow); }

  /* QR Code */
  .qr-box { text-align: center; padding: 20px; }
  .qr-box img { border: 4px solid #fff; border-radius: 8px; max-width: 220px; }
  .qr-status { margin-top: 12px; font-size: 14px; }

  /* Bot control */
  .control-bar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .running-badge { display: flex; align-items: center; gap: 8px; padding: 8px 16px; background: var(--surface2); border-radius: 8px; font-size: 14px; }

  /* Pagination */
  .pagination { display: flex; gap: 8px; align-items: center; margin-top: 16px; justify-content: flex-end; }
  .page-btn { padding: 6px 12px; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px; color: var(--text); cursor: pointer; font-size: 13px; }
  .page-btn:hover { background: var(--border); }
  .page-btn.active { background: var(--accent); border-color: var(--accent); }

  /* Toast */
  #toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; }
  .toast { padding: 12px 20px; border-radius: 8px; font-size: 14px; color: #fff; animation: slideIn .3s ease; min-width: 200px; }
  .toast.success { background: var(--green); }
  .toast.error { background: var(--red); }
  .toast.info { background: var(--accent2); }
  @keyframes slideIn { from{transform:translateX(100%);opacity:0} to{transform:translateX(0);opacity:1} }

  /* Responsive */
  @media (max-width: 768px) {
    .sidebar { width: 60px; }
    .sidebar-logo, .nav-list li a span:not(.icon) { display: none; }
    .main { margin-left: 60px; padding: 16px; }
    .form-row, .form-row-3 { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div id="toast-container"></div>
<div class="app">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-logo">
      <div class="logo-title">🤖 BiliBot</div>
      <div class="logo-sub">B站评论自动回复</div>
    </div>
    <ul class="nav-list">
      <li><a href="#" class="active" data-page="dashboard"><span class="icon">📊</span><span>控制台</span><span class="status-dot" id="nav-status-dot"></span></a></li>
      <li><a href="#" data-page="config"><span class="icon">⚙️</span><span>配置</span></a></li>
      <li><a href="#" data-page="login"><span class="icon">🔑</span><span>登录</span></a></li>
      <li><a href="#" data-page="history"><span class="icon">📝</span><span>历史记录</span></a></li>
      <li><a href="#" data-page="logs"><span class="icon">📋</span><span>实时日志</span></a></li>
    </ul>
  </aside>

  <!-- Main -->
  <main class="main">

    <!-- Dashboard -->
    <div class="page active" id="page-dashboard">
      <div class="page-title"><span class="icon">📊</span>控制台</div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value" id="stat-total">0</div>
          <div class="stat-label">总回复数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" id="stat-processed">0</div>
          <div class="stat-label">已处理评论</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" id="stat-videos">0</div>
          <div class="stat-label">缓存视频数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" id="stat-status" style="font-size:16px;margin-top:4px">停止中</div>
          <div class="stat-label">运行状态</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">机器人控制</div>
        <div class="control-bar">
          <button class="btn btn-success" id="btn-start" onclick="botStart()">▶ 启动机器人</button>
          <button class="btn btn-danger" id="btn-stop" onclick="botStop()" disabled>⏹ 停止</button>
          <button class="btn btn-secondary" onclick="verifyLogin()">🔍 验证登录状态</button>
          <button class="btn btn-secondary" onclick="clearCache()">🗑 清除视频缓存</button>
        </div>
        <div id="verify-result" style="margin-top:12px"></div>
      </div>

      <div class="card">
        <div class="card-title">运行信息</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:14px">
          <div><span style="color:var(--text2)">启动时间：</span><span id="info-start">-</span></div>
          <div><span style="color:var(--text2)">上次检查：</span><span id="info-check">-</span></div>
        </div>
      </div>
    </div>

    <!-- Config -->
    <div class="page" id="page-config">
      <div class="page-title"><span class="icon">⚙️</span>配置</div>
      <div class="tab-bar">
        <button class="tab-btn active" data-tab="tab-bilibili">B站配置</button>
        <button class="tab-btn" data-tab="tab-deepseek">DeepSeek</button>
        <button class="tab-btn" data-tab="tab-reply">回复策略</button>
        <button class="tab-btn" data-tab="tab-rate">频率控制</button>
        <button class="tab-btn" data-tab="tab-cache">缓存</button>
        <button class="tab-btn" data-tab="tab-logging">日志</button>
      </div>

      <!-- B站 -->
      <div class="tab-panel active" id="tab-bilibili">
        <div class="card">
          <div class="form-group">
            <label class="form-label">B站 Cookie</label>
            <textarea class="form-textarea" id="cfg-bilibili-cookie" rows="4" placeholder="SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx"></textarea>
            <div class="form-hint">请确保包含 SESSDATA、bili_jct、DedeUserID 字段。可在「登录」页扫码自动获取。</div>
          </div>
          <div class="form-group">
            <label class="form-label">Refresh Token（用于自动刷新 Cookie）</label>
            <input class="form-input" id="cfg-bilibili-refresh_token" placeholder="refresh_token">
          </div>
          <div class="form-group">
            <label class="form-label">B站用户 ID（UID）</label>
            <input class="form-input" id="cfg-bilibili-uid" placeholder="如：123456789">
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">检查评论间隔（秒）</label>
              <input class="form-input" type="number" id="cfg-bilibili-check_interval" value="60">
            </div>
            <div class="form-group">
              <label class="form-label">Cookie 刷新间隔（分钟）</label>
              <input class="form-input" type="number" id="cfg-bilibili-cookie_refresh_interval" value="30">
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">最大评论页数</label>
              <input class="form-input" type="number" id="cfg-bilibili-max_comment_pages" value="10">
            </div>
            <div class="form-group">
              <label class="form-label">最大视频页数</label>
              <input class="form-input" type="number" id="cfg-bilibili-max_video_pages" value="10">
            </div>
          </div>
          <div class="form-group">
            <label class="form-check">
              <input type="checkbox" id="cfg-bilibili-auto_refresh_cookie" checked>
              启用 Cookie 自动刷新
            </label>
          </div>
        </div>
      </div>

      <!-- DeepSeek -->
      <div class="tab-panel" id="tab-deepseek">
        <div class="card">
          <div class="form-group">
            <label class="form-label">DeepSeek API Key</label>
            <input class="form-input" id="cfg-deepseek-api_key" placeholder="sk-xxx" type="password">
          </div>
          <div class="form-group">
            <label class="form-label">API Base URL</label>
            <input class="form-input" id="cfg-deepseek-base_url" value="https://api.deepseek.com/v1">
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">模型</label>
              <input class="form-input" id="cfg-deepseek-model" value="deepseek-chat">
            </div>
            <div class="form-group">
              <label class="form-label">最大 Token 数</label>
              <input class="form-input" type="number" id="cfg-deepseek-max_tokens" value="200">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">温度（0-1，越高越随机）</label>
            <input class="form-input" type="number" step="0.1" min="0" max="1" id="cfg-deepseek-temperature" value="0.7">
          </div>
          <div class="form-group">
            <label class="form-label">系统提示词（定义 AI 角色和回复风格）</label>
            <textarea class="form-textarea" id="cfg-deepseek-system_prompt" rows="5"></textarea>
          </div>
        </div>
      </div>

      <!-- Reply -->
      <div class="tab-panel" id="tab-reply">
        <div class="card">
          <div class="form-group">
            <label class="form-check">
              <input type="checkbox" id="cfg-reply-enabled" checked>
              启用自动回复
            </label>
          </div>
          <div class="form-group">
            <label class="form-check">
              <input type="checkbox" id="cfg-reply-only_new" checked>
              只回复未处理过的评论
            </label>
          </div>
          <div class="form-group">
            <label class="form-check">
              <input type="checkbox" id="cfg-reply-like_enabled">
              回复时同时点赞评论
            </label>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">每次最多处理评论数</label>
              <input class="form-input" type="number" id="cfg-reply-max_process" value="10">
            </div>
            <div class="form-group">
              <label class="form-label">回复延迟（秒）</label>
              <input class="form-input" type="number" id="cfg-reply-reply_delay" value="2">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">上下文评论数（0=不使用上下文）</label>
            <input class="form-input" type="number" id="cfg-reply-context_comments_count" value="0">
            <div class="form-hint">生成回复时参考前 N 条评论作为上下文</div>
          </div>
          <div class="form-group">
            <label class="form-label">回复前缀（可留空）</label>
            <input class="form-input" id="cfg-reply-prefix" placeholder="">
          </div>
        </div>
      </div>

      <!-- Rate Limit -->
      <div class="tab-panel" id="tab-rate">
        <div class="card">
          <div class="form-row-3">
            <div class="form-group">
              <label class="form-label">最小请求间隔（秒）</label>
              <input class="form-input" type="number" step="0.5" id="cfg-rate_limit-min_request_interval" value="2">
            </div>
            <div class="form-group">
              <label class="form-label">最大重试次数</label>
              <input class="form-input" type="number" id="cfg-rate_limit-max_retries" value="3">
            </div>
            <div class="form-group">
              <label class="form-label">重试基础延迟（秒）</label>
              <input class="form-input" type="number" id="cfg-rate_limit-retry_delay" value="5">
            </div>
          </div>
        </div>
      </div>

      <!-- Cache -->
      <div class="tab-panel" id="tab-cache">
        <div class="card">
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">GET 响应缓存时间（秒）</label>
              <input class="form-input" type="number" id="cfg-cache-expire_time" value="300">
            </div>
            <div class="form-group">
              <label class="form-label">视频列表缓存时间（秒）</label>
              <input class="form-input" type="number" id="cfg-video_cache-expire_time" value="43200">
              <div class="form-hint">默认 43200 = 12小时</div>
            </div>
          </div>
          <div class="form-group">
            <label class="form-check">
              <input type="checkbox" id="cfg-cache-enabled" checked>
              启用 GET 响应缓存
            </label>
          </div>
        </div>
      </div>

      <!-- Logging -->
      <div class="tab-panel" id="tab-logging">
        <div class="card">
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">日志级别</label>
              <select class="form-select" id="cfg-logging-level">
                <option value="DEBUG">DEBUG</option>
                <option value="INFO" selected>INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">日志文件路径</label>
              <input class="form-input" id="cfg-logging-file" value="logs/bot.log">
            </div>
          </div>
          <div class="form-group">
            <label class="form-check">
              <input type="checkbox" id="cfg-logging-console" checked>
              输出到控制台
            </label>
          </div>
        </div>
      </div>

      <div style="display:flex;gap:12px;margin-top:8px">
        <button class="btn btn-primary" onclick="saveConfig()">💾 保存配置</button>
        <button class="btn btn-secondary" onclick="loadConfig()">🔄 重新加载</button>
      </div>
    </div>

    <!-- Login -->
    <div class="page" id="page-login">
      <div class="page-title"><span class="icon">🔑</span>扫码登录</div>
      <div class="card" style="max-width:500px">
        <div class="card-title">微信扫码登录 B 站</div>
        <p style="font-size:14px;color:var(--text2);margin-bottom:20px">
          点击「生成二维码」后，使用 B站 App 扫码登录。Cookie 获取成功后会自动填入配置并保存。
        </p>
        <button class="btn btn-primary" id="btn-gen-qr" onclick="generateQR()">📱 生成二维码</button>
        <div id="qr-container" style="margin-top:20px"></div>
      </div>
    </div>

    <!-- History -->
    <div class="page" id="page-history">
      <div class="page-title"><span class="icon">📝</span>回复历史</div>
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
          <span id="history-total" style="color:var(--text2);font-size:14px">共 0 条记录</span>
          <button class="btn btn-danger" onclick="clearHistory()" style="padding:7px 14px;font-size:13px">🗑 清空历史</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>用户</th>
                <th>评论内容</th>
                <th>回复内容</th>
              </tr>
            </thead>
            <tbody id="history-tbody"></tbody>
          </table>
        </div>
        <div class="pagination" id="history-pagination"></div>
      </div>
    </div>

    <!-- Logs -->
    <div class="page" id="page-logs">
      <div class="page-title"><span class="icon">📋</span>实时日志</div>
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <div style="display:flex;gap:8px;align-items:center">
            <label class="form-check" style="font-size:13px">
              <input type="checkbox" id="log-auto-scroll" checked> 自动滚动
            </label>
            <select class="form-select" id="log-filter" style="width:120px;padding:5px 8px;font-size:13px" onchange="filterLogs()">
              <option value="">全部</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
              <option value="DEBUG">DEBUG</option>
            </select>
          </div>
          <button class="btn btn-secondary" onclick="clearLogs()" style="padding:7px 14px;font-size:13px">清空</button>
        </div>
        <div class="log-container" id="log-container"></div>
      </div>
    </div>

  </main>
</div>

<script>
const socket = io();
let currentPage = 'dashboard';
let historyPage = 1;
let allLogs = [];
let configData = {};

// ── Socket 事件 ──
socket.on('connect', () => { console.log('WS connected'); });
socket.on('bot_status', d => updateBotStatus(d.running));
socket.on('stats', d => updateStats(d));
socket.on('log', entry => appendLog(entry));
socket.on('log_history', d => { allLogs = d.logs; renderLogs(); });
socket.on('new_history', item => {
  if (currentPage === 'history') loadHistory(historyPage);
});
socket.on('qr_status', d => {
  const el = document.getElementById('qr-status');
  if (el) {
    el.textContent = d.message;
    el.className = 'qr-status';
    if (d.code === 0) el.style.color = 'var(--green)';
    else if (d.code < 0 || d.code === 86038) el.style.color = 'var(--red)';
    else el.style.color = 'var(--accent2)';
  }
});
socket.on('qr_cookie', d => {
  showToast('登录成功，正在保存配置...', 'success');
  // 自动保存cookie到配置
  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ bilibili: { cookie: d.cookie } })
  }).then(r => r.json()).then(r => {
    if (r.ok) {
      showToast('Cookie 已保存到配置', 'success');
      loadConfig();
    }
  });
  document.getElementById('btn-gen-qr').disabled = false;
});
socket.on('video_list', d => {
  document.getElementById('stat-videos').textContent = d.count;
});

// ── 页面导航 ──
document.querySelectorAll('.nav-list a').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    const page = a.dataset.page;
    navigateTo(page);
  });
});
function navigateTo(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-list a').forEach(a => a.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  document.querySelector(`[data-page="${page}"]`).classList.add('active');
  currentPage = page;
  if (page === 'history') loadHistory(1);
  if (page === 'config') loadConfig();
}

// ── Tab 切换 ──
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tabId = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(tabId).classList.add('active');
  });
});

// ── 统计更新 ──
function updateStats(d) {
  document.getElementById('stat-total').textContent = d.total_replied || 0;
  document.getElementById('stat-processed').textContent = d.processed_count || 0;
  document.getElementById('stat-videos').textContent = d.cached_videos || 0;
  document.getElementById('info-start').textContent = d.start_time || '-';
  document.getElementById('info-check').textContent = d.last_check || '-';
  updateBotStatus(d.running);
}
function updateBotStatus(running) {
  const dot = document.getElementById('nav-status-dot');
  const statEl = document.getElementById('stat-status');
  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  if (running) {
    dot.classList.add('running');
    statEl.textContent = '运行中';
    statEl.style.color = 'var(--green)';
    btnStart.disabled = true;
    btnStop.disabled = false;
  } else {
    dot.classList.remove('running');
    statEl.textContent = '已停止';
    statEl.style.color = 'var(--red)';
    btnStart.disabled = false;
    btnStop.disabled = true;
  }
}

// ── 机器人控制 ──
function botStart() {
  fetch('/api/bot/start', {method:'POST'}).then(r=>r.json()).then(d=>{
    showToast(d.message, d.ok ? 'success' : 'error');
  });
}
function botStop() {
  fetch('/api/bot/stop', {method:'POST'}).then(r=>r.json()).then(d=>{
    showToast(d.message, d.ok ? 'success' : 'error');
  });
}
function verifyLogin() {
  const el = document.getElementById('verify-result');
  el.innerHTML = '<span style="color:var(--text2)">验证中...</span>';
  fetch('/api/bot/verify').then(r=>r.json()).then(d=>{
    if (d.valid) {
      const u = d.user_info || {};
      el.innerHTML = `<div class="alert alert-success">✅ 登录有效 — ${u.name || ''} (UID: ${u.mid || ''})</div>`;
    } else {
      el.innerHTML = `<div class="alert alert-danger">❌ ${d.message}</div>`;
    }
  });
}
function clearCache() {
  fetch('/api/cache/clear', {method:'POST'}).then(r=>r.json()).then(d=>{
    showToast(d.message, d.ok ? 'success' : 'error');
    document.getElementById('stat-videos').textContent = '0';
  });
}

// ── 配置 ──
function loadConfig() {
  fetch('/api/config').then(r=>r.json()).then(d=>{
    if (!d.ok) return;
    configData = d.config;
    const cfg = d.config;

    // 填充所有字段
    function set(id, val) {
      const el = document.getElementById(id);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!val;
      else el.value = val !== undefined && val !== null ? val : '';
    }

    const b = cfg.bilibili || {};
    set('cfg-bilibili-cookie', b.cookie);
    set('cfg-bilibili-refresh_token', b.refresh_token);
    set('cfg-bilibili-uid', b.uid);
    set('cfg-bilibili-check_interval', b.check_interval);
    set('cfg-bilibili-cookie_refresh_interval', b.cookie_refresh_interval);
    set('cfg-bilibili-max_comment_pages', b.max_comment_pages);
    set('cfg-bilibili-max_video_pages', b.max_video_pages);
    set('cfg-bilibili-auto_refresh_cookie', b.auto_refresh_cookie);

    const ds = cfg.deepseek || {};
    set('cfg-deepseek-api_key', ds.api_key);
    set('cfg-deepseek-base_url', ds.base_url);
    set('cfg-deepseek-model', ds.model);
    set('cfg-deepseek-max_tokens', ds.max_tokens);
    set('cfg-deepseek-temperature', ds.temperature);
    set('cfg-deepseek-system_prompt', ds.system_prompt);

    const r = cfg.reply || {};
    set('cfg-reply-enabled', r.enabled);
    set('cfg-reply-only_new', r.only_new);
    set('cfg-reply-like_enabled', r.like_enabled);
    set('cfg-reply-max_process', r.max_process);
    set('cfg-reply-reply_delay', r.reply_delay);
    set('cfg-reply-context_comments_count', r.context_comments_count);
    set('cfg-reply-prefix', r.prefix);

    const rl = cfg.rate_limit || {};
    set('cfg-rate_limit-min_request_interval', rl.min_request_interval);
    set('cfg-rate_limit-max_retries', rl.max_retries);
    set('cfg-rate_limit-retry_delay', rl.retry_delay);

    const ca = cfg.cache || {};
    set('cfg-cache-expire_time', ca.expire_time);
    set('cfg-cache-enabled', ca.enabled);
    const vc = cfg.video_cache || {};
    set('cfg-video_cache-expire_time', vc.expire_time);

    const lg = cfg.logging || {};
    set('cfg-logging-level', lg.level);
    set('cfg-logging-file', lg.file);
    set('cfg-logging-console', lg.console);
  });
}

function saveConfig() {
  function get(id) {
    const el = document.getElementById(id);
    if (!el) return undefined;
    if (el.type === 'checkbox') return el.checked;
    if (el.type === 'number') return el.value === '' ? 0 : Number(el.value);
    return el.value;
  }

  const cfg = {
    bilibili: {
      cookie: get('cfg-bilibili-cookie'),
      refresh_token: get('cfg-bilibili-refresh_token'),
      uid: get('cfg-bilibili-uid'),
      check_interval: get('cfg-bilibili-check_interval'),
      cookie_refresh_interval: get('cfg-bilibili-cookie_refresh_interval'),
      max_comment_pages: get('cfg-bilibili-max_comment_pages'),
      max_video_pages: get('cfg-bilibili-max_video_pages'),
      auto_refresh_cookie: get('cfg-bilibili-auto_refresh_cookie'),
    },
    deepseek: {
      api_key: get('cfg-deepseek-api_key'),
      base_url: get('cfg-deepseek-base_url'),
      model: get('cfg-deepseek-model'),
      max_tokens: get('cfg-deepseek-max_tokens'),
      temperature: get('cfg-deepseek-temperature'),
      system_prompt: get('cfg-deepseek-system_prompt'),
    },
    reply: {
      enabled: get('cfg-reply-enabled'),
      only_new: get('cfg-reply-only_new'),
      like_enabled: get('cfg-reply-like_enabled'),
      max_process: get('cfg-reply-max_process'),
      reply_delay: get('cfg-reply-reply_delay'),
      context_comments_count: get('cfg-reply-context_comments_count'),
      prefix: get('cfg-reply-prefix'),
    },
    rate_limit: {
      min_request_interval: get('cfg-rate_limit-min_request_interval'),
      max_retries: get('cfg-rate_limit-max_retries'),
      retry_delay: get('cfg-rate_limit-retry_delay'),
    },
    cache: {
      expire_time: get('cfg-cache-expire_time'),
      enabled: get('cfg-cache-enabled'),
    },
    video_cache: {
      expire_time: get('cfg-video_cache-expire_time'),
      cache_file: 'video_cache.json',
    },
    logging: {
      level: get('cfg-logging-level'),
      file: get('cfg-logging-file'),
      console: get('cfg-logging-console'),
    },
  };

  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(cfg),
  }).then(r=>r.json()).then(d=>{
    showToast(d.message, d.ok ? 'success' : 'error');
  });
}

// ── 扫码登录 ──
function generateQR() {
  const btn = document.getElementById('btn-gen-qr');
  btn.disabled = true;
  const container = document.getElementById('qr-container');
  container.innerHTML = '<span style="color:var(--text2)">生成中...</span>';
  fetch('/api/qr/generate', {method:'POST'}).then(r=>r.json()).then(d=>{
    if (d.ok) {
      container.innerHTML = `
        <div class="qr-box">
          <img src="data:image/png;base64,${d.qr_image}" alt="二维码">
          <div id="qr-status" class="qr-status" style="color:var(--accent2)">等待扫码...</div>
          <div style="font-size:12px;color:var(--text2);margin-top:8px">请使用 B站 App 扫码，有效期 3 分钟</div>
        </div>`;
    } else {
      container.innerHTML = `<div class="alert alert-danger">${d.message}</div>`;
      btn.disabled = false;
    }
  }).catch(e => {
    container.innerHTML = `<div class="alert alert-danger">请求失败: ${e}</div>`;
    btn.disabled = false;
  });
}

// ── 历史记录 ──
function loadHistory(page) {
  historyPage = page;
  fetch(`/api/history?page=${page}&per_page=20`).then(r=>r.json()).then(d=>{
    if (!d.ok) return;
    const tbody = document.getElementById('history-tbody');
    document.getElementById('history-total').textContent = `共 ${d.total} 条记录`;
    tbody.innerHTML = d.data.map(item => `
      <tr>
        <td style="white-space:nowrap;color:var(--text2)">${item.timestamp || ''}</td>
        <td><span class="badge badge-blue">${escHtml(item.user || '')}</span></td>
        <td style="max-width:240px;word-break:break-all">${escHtml(item.content || '')}</td>
        <td style="max-width:240px;word-break:break-all;color:var(--green)">${escHtml(item.reply_content || '')}</td>
      </tr>`).join('');
    // 分页
    const total = d.total;
    const totalPages = Math.ceil(total / 20);
    const pg = document.getElementById('history-pagination');
    let pgHtml = '';
    if (page > 1) pgHtml += `<button class="page-btn" onclick="loadHistory(${page-1})">‹</button>`;
    for (let i = Math.max(1,page-2); i <= Math.min(totalPages,page+2); i++) {
      pgHtml += `<button class="page-btn ${i===page?'active':''}" onclick="loadHistory(${i})">${i}</button>`;
    }
    if (page < totalPages) pgHtml += `<button class="page-btn" onclick="loadHistory(${page+1})">›</button>`;
    pg.innerHTML = pgHtml;
  });
}
function clearHistory() {
  if (!confirm('确认清空所有历史记录？此操作不可撤销。')) return;
  fetch('/api/history/clear', {method:'POST'}).then(r=>r.json()).then(d=>{
    showToast(d.message, d.ok ? 'success' : 'error');
    if (d.ok) loadHistory(1);
  });
}

// ── 日志 ──
function appendLog(entry) {
  allLogs.push(entry);
  if (allLogs.length > 1000) allLogs = allLogs.slice(-1000);
  const filter = document.getElementById('log-filter').value;
  if (!filter || entry.level === filter) {
    const container = document.getElementById('log-container');
    const div = document.createElement('div');
    div.className = `log-entry ${entry.level}`;
    div.innerHTML = `<span class="log-time">${entry.time}</span><span class="log-level">[${entry.level}]</span> ${escHtml(entry.msg)}`;
    container.appendChild(div);
    if (document.getElementById('log-auto-scroll').checked) {
      container.scrollTop = container.scrollHeight;
    }
  }
}
function renderLogs() {
  const container = document.getElementById('log-container');
  const filter = document.getElementById('log-filter').value;
  container.innerHTML = '';
  allLogs.filter(e => !filter || e.level === filter).forEach(entry => {
    const div = document.createElement('div');
    div.className = `log-entry ${entry.level}`;
    div.innerHTML = `<span class="log-time">${entry.time}</span><span class="log-level">[${entry.level}]</span> ${escHtml(entry.msg)}`;
    container.appendChild(div);
  });
  container.scrollTop = container.scrollHeight;
}
function filterLogs() { renderLogs(); }
function clearLogs() { allLogs = []; document.getElementById('log-container').innerHTML = ''; }

// ── Toast ──
function showToast(msg, type='info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ── 工具 ──
function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── 初始化 ──
(function init() {
  loadConfig();
  fetch('/api/bot/status').then(r=>r.json()).then(d => updateStats(d));
})();
</script>
</body>
</html>"""

# ─────────────────────────────────────────────
#  入口
# ─────────────────────────────────────────────
def main():
    host = "127.0.0.1"
    port = 5000
    url = f"http://{host}:{port}"
    print(f"""
╔══════════════════════════════════════════╗
║       B站评论自动回复机器人 Web UI        ║
╠══════════════════════════════════════════╣
║  访问地址: {url:<31}║
║  按 Ctrl+C 停止服务                      ║
╚══════════════════════════════════════════╝
""")
    # 初始化机器人（预加载）
    bot = get_bot()

    # 检测配置是否完整，自动启动机器人
    cfg = load_config()
    cookie = cfg.get("bilibili", {}).get("cookie", "")
    api_key = cfg.get("deepseek", {}).get("api_key", "")

    if cookie and api_key:
        print("检测到有效配置，自动启动机器人...")
        if bot.start():
            print("✓ 机器人已自动启动")
        else:
            print("✗ 机器人启动失败")
    else:
        print("提示: 请在 Web UI 中完成配置后启动")

    # 延迟打开浏览器
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    socketio.run(app, host=host, port=port, debug=False, use_reloader=False, log_output=False)


if __name__ == "__main__":
    main()
