#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站评论自动回复机器人 — Web 服务入口
"""
import os
import sys
import time
import json
import logging
import threading
import webbrowser
import hashlib
import base64
import io
import random
import string
import copy
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from typing import Optional

import requests
import toml
import tomli_w

from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit

from bot import (
    BiliCommentBot,
    DEFAULT_CONFIG,
    CONFIG_FILE,
    HISTORY_FILE,
    COOKIE_FILE,
    VIDEO_CACHE_FILE,
)

# ─────────────────────────────────────────────
#  Flask + SocketIO
# ─────────────────────────────────────────────
SECRET_KEY = os.environ.get("BILI_SECRET_KEY", None)
if not SECRET_KEY:
    # 未设置环境变量时自动生成随机密钥（避免硬编码）
    SECRET_KEY = hashlib.sha256(os.urandom(32)).hexdigest()

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ─────────────────────────────────────────────
#  日志 Handler（推送到前端）
# ─────────────────────────────────────────────
class WebSocketLogHandler(logging.Handler):
    def __init__(self, sio: SocketIO):
        super().__init__()
        self.sio = sio
        self.log_buffer: list = []
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
        except Exception as exc:
            # 连接未就绪时静默忽略
            pass


ws_log_handler = WebSocketLogHandler(socketio)
ws_log_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
)

# ─────────────────────────────────────────────
#  配置管理
# ─────────────────────────────────────────────
def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = toml.load(f)

        def merge(base, override):
            result = dict(base)
            for k, v in override.items():
                if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                    result[k] = merge(result[k], v)
                else:
                    result[k] = v
            return result

        return merge(copy.deepcopy(DEFAULT_CONFIG), cfg)
    except Exception as e:
        print(f"加载配置文件失败: {e}，使用默认配置")
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg: dict) -> bool:
    try:
        with open(CONFIG_FILE, "wb") as f:
            tomli_w.dump(cfg, f)
        return True
    except Exception as e:
        print(f"保存配置文件失败: {e}")
        return False


# ─────────────────────────────────────────────
#  日志设置
# ─────────────────────────────────────────────
def _setup_logger(cfg: dict) -> logging.Logger:
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file", "logs/bot.log")
    data_dir = os.environ.get("BILI_DATA_DIR", "")
    if data_dir and not os.path.isabs(log_file):
        log_file = os.path.join(data_dir, log_file)
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
#  全局机器人实例
# ─────────────────────────────────────────────
_bot: Optional[BiliCommentBot] = None
_bot_logger: Optional[logging.Logger] = None


def get_bot() -> BiliCommentBot:
    global _bot, _bot_logger
    if _bot is None:
        cfg = load_config()
        _bot_logger = _setup_logger(cfg)
        _bot = BiliCommentBot(cfg, _bot_logger, socketio=socketio)
    return _bot


# ─────────────────────────────────────────────
#  扫码登录
# ─────────────────────────────────────────────
BILI_QR_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
BILI_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}

_qr_session: Optional[requests.Session] = None
_qr_key: Optional[str] = None
_qr_thread: Optional[threading.Thread] = None


def _gen_qr_image_base64(url: str) -> str:
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
#  Flask 路由
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


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

    def deep_update(base, upd):
        for k, v in upd.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                deep_update(base[k], v)
            else:
                base[k] = v
    deep_update(cfg, data)
    if save_config(cfg):
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
    """从 bot 的内存缓冲区读取历史记录（比读文件快）"""
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    try:
        bot = get_bot()
        history = bot.get_history()
        history.sort(key=lambda x: x.get("reply_time", 0), reverse=True)
        total = len(history)
        start = (page - 1) * per_page
        end = start + per_page
        return jsonify({"ok": True, "total": total, "page": page, "data": history[start:end]})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        bot = get_bot()
        bot.processed_comments.clear()
        # 清空内存缓冲
        bot._history_buffer = []
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


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    data = request.get_json()
    password = data.get("password", "") if data else ""
    cfg = load_config()
    auth_cfg = cfg.get("auth", {})
    stored_hash = auth_cfg.get("password", "")
    if not auth_cfg.get("enabled", False) or not stored_hash:
        return jsonify({"ok": True, "message": "未启用密码保护"})
    pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    if pwd_hash == stored_hash:
        return jsonify({"ok": True, "message": "验证成功"})
    return jsonify({"ok": False, "message": "密码错误"})


@app.route("/api/auth/password", methods=["POST"])
def api_auth_password():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "message": "无效数据"})
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")
    action = data.get("action", "")

    cfg = load_config()
    auth_cfg = cfg.get("auth", {})
    stored_hash = auth_cfg.get("password", "")

    if action == "generate":
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        new_password = "".join(random.choice(chars) for _ in range(16))
        pwd_hash = hashlib.sha256(new_password.encode("utf-8")).hexdigest()
        cfg.setdefault("auth", {})["password"] = pwd_hash
        cfg.setdefault("auth", {})["enabled"] = True
        if save_config(cfg):
            return jsonify({"ok": True, "message": "密码已生成", "password": new_password})
        return jsonify({"ok": False, "message": "保存失败"})

    if action == "change":
        if stored_hash:
            old_hash = hashlib.sha256(old_password.encode("utf-8")).hexdigest()
            if old_hash != stored_hash:
                return jsonify({"ok": False, "message": "旧密码错误"})
        if not new_password or len(new_password) < 4:
            return jsonify({"ok": False, "message": "新密码长度不能少于4位"})
        pwd_hash = hashlib.sha256(new_password.encode("utf-8")).hexdigest()
        cfg.setdefault("auth", {})["password"] = pwd_hash
        cfg.setdefault("auth", {})["enabled"] = True
        if save_config(cfg):
            return jsonify({"ok": True, "message": "密码已修改"})
        return jsonify({"ok": False, "message": "保存失败"})

    if action == "clear":
        cfg.setdefault("auth", {})["password"] = ""
        cfg.setdefault("auth", {})["enabled"] = False
        if save_config(cfg):
            return jsonify({"ok": True, "message": "密码保护已关闭"})
        return jsonify({"ok": False, "message": "保存失败"})

    return jsonify({"ok": False, "message": "未知操作"})


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
    emit("log_history", {"logs": ws_log_handler.log_buffer[-100:]})


# ─────────────────────────────────────────────
#  入口
# ─────────────────────────────────────────────
def main():
    host = "0.0.0.0"
    port = 5000
    url = f"http://{host}:{port}"
    browser_url = f"http://localhost:{port}"
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
    auth_enabled = cfg.get("auth", {}).get("enabled", False)

    if auth_enabled:
        print("🔒 登录密码保护已启用")
    else:
        print("⚠️  未启用登录密码保护，建议在配置 > 安全中设置密码")

    if cookie and api_key:
        print("检测到有效配置，自动启动机器人...")
        if bot.start():
            print("✓ 机器人已自动启动")
        else:
            print("✗ 机器人启动失败")
    else:
        print("提示: 请在 Web UI 中完成配置后启动")

    # 延迟打开浏览器（Docker 环境下不打开）
    if os.getenv('DOCKER_ENV') != 'true':
        threading.Timer(1.5, lambda: webbrowser.open(browser_url)).start()
    socketio.run(app, host=host, port=port, debug=False, use_reloader=False, log_output=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
