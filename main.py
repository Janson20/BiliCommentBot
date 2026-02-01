#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站评论自动回复机器人
使用DeepSeek API自动回复B站视频的新增评论
"""

import os
import time
import json
import logging
import requests
import toml
import random
import hashlib
import urllib.parse
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


class BilibiliCookieManager:
    """
    B站Cookie管理器
    实现Cookie的自动刷新功能
    """

    def __init__(self, cookie_str: str = None, refresh_token: str = None):
        """
        初始化Cookie管理器

        Args:
            cookie_str: Cookie字符串，格式为"SESSDATA=xxx; bili_jct=xxx; ..."
            refresh_token: 刷新令牌，可从登录响应中获取
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.bilibili.com/',
            'Origin': 'https://www.bilibili.com',
        })

        if cookie_str:
            self.set_cookie_from_str(cookie_str)

        self.refresh_token = refresh_token
        self.csrf_token = self._get_csrf_from_cookie()

    def set_cookie_from_str(self, cookie_str: str):
        """从字符串设置Cookie"""
        cookie_dict = {}
        for item in cookie_str.split(';'):
            item = item.strip()
            if not item:
                continue
            if '=' in item:
                key, value = item.split('=', 1)
                cookie_dict[key.strip()] = value.strip()
            else:
                cookie_dict[item] = ''
        self.session.cookies.update(cookie_dict)

    def _get_csrf_from_cookie(self) -> Optional[str]:
        """从Cookie中获取CSRF Token (bili_jct)"""
        return self.session.cookies.get('bili_jct', None)

    def _generate_correspond_path(self) -> str:
        """生成加密的correspondPath参数"""
        timestamp = int(time.time())
        md5 = hashlib.md5(f'{timestamp}'.encode()).hexdigest()
        correspond_path = f'/apis/redirect/login?from=bilibili.com&timestamp={timestamp}&md5={md5}'
        return correspond_path

    def check_cookie_status(self) -> Dict:
        """
        检查Cookie状态

        Returns:
            Dict: 状态信息，包含是否需要刷新
        """
        url = 'https://passport.bilibili.com/x/passport-login/web/cookie/info'

        try:
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()

            if data.get('code') == 0:
                return {
                    'need_refresh': data.get('data', {}).get('refresh', False),
                    'message': 'Cookie状态检查成功',
                    'data': data.get('data', {})
                }
            else:
                return {
                    'need_refresh': False,
                    'message': f'检查失败: {data.get("message", "未知错误")}',
                    'code': data.get('code')
                }

        except Exception as e:
            return {
                'need_refresh': False,
                'message': f'请求异常: {str(e)}',
                'error': str(e)
            }

    def get_refresh_csrf(self) -> Optional[str]:
        """
        获取刷新所需的CSRF令牌

        Returns:
            str: refresh_csrf 令牌
        """
        correspond_path = self._generate_correspond_path()
        encoded_path = urllib.parse.quote(correspond_path, safe='')

        url = f'https://www.bilibili.com/correspond/1/{encoded_path}'

        try:
            response = self.session.get(url)
            response.raise_for_status()

            # 从返回的HTML中提取refresh_csrf
            # 通常位于JavaScript变量中
            html_content = response.text

            # 尝试从HTML中提取refresh_csrf
            # 尝试多种模式匹配
            import re

            # 模式1: 匹配 "refresh_csrf":"value"
            patterns = [
                r'"refresh_csrf"\s*:\s*"([^"]+)"',
                r'"refresh_csrf"\s*:\s*"((?:[^"\\]|\\.)*)"',  # 处理转义字符
                r"refresh_csrf\s*=\s*'([^']+)'",
                r"refresh_csrf\s*=\s*\"([^\"]+)\"",
                r'"refresh_csrf"\s*:\s*([0-9a-f]+)',  # 匹配数字/字母组合（如MD5）
                r"refresh_csrf['\"]?\s*[:=]\s*['\"]?([0-9a-zA-Z_-]+)['\"]?"  # 更宽松的匹配
            ]

            for pattern in patterns:
                match = re.search(pattern, html_content, re.IGNORECASE)
                if match:
                    csrf_value = match.group(1)
                    # 验证值不为空且不是纯数字
                    if csrf_value and csrf_value.strip():
                        return csrf_value.strip()

            # 如果都失败，打印部分HTML用于调试
            # 找到包含refresh_csrf的行
            lines_with_keyword = [line for line in html_content.split('\n') if 'refresh_csrf' in line.lower()]
            if lines_with_keyword:
                self.logger.debug(f"找到包含refresh_csrf的行: {lines_with_keyword[:3]}")

            return None

        except Exception as e:
            return None

    def refresh_cookie(self, refresh_token: str = None) -> Tuple[bool, Dict]:
        """
        刷新Cookie

        Args:
            refresh_token: 刷新令牌，如果为None则使用初始化时设置的

        Returns:
            Tuple[bool, Dict]: (是否成功, 响应信息)
        """
        if not refresh_token and not self.refresh_token:
            return False, {'message': 'refresh_token不存在'}

        token = refresh_token or self.refresh_token

        # 获取refresh_csrf
        refresh_csrf = self.get_refresh_csrf()
        if not refresh_csrf:
            return False, {'message': '获取refresh_csrf失败'}

        # 获取CSRF token
        csrf_token = self._get_csrf_from_cookie()
        if not csrf_token:
            return False, {'message': '从Cookie中获取CSRF token失败'}

        # 刷新Cookie
        url = 'https://passport.bilibili.com/x/passport-login/web/cookie/refresh'

        params = {
            'csrf': csrf_token,
            'refresh_csrf': refresh_csrf,
            'refresh_token': token,
            'source': 'main_web'
        }

        try:
            response = self.session.post(url, data=params)
            response.raise_for_status()
            data = response.json()

            if data.get('code') == 0:
                response_data = data.get('data', {})

                # 更新refresh_token
                new_refresh_token = response_data.get('refresh_token')
                if new_refresh_token:
                    self.refresh_token = new_refresh_token

                # 确认刷新，使旧的refresh_token失效
                if self.confirm_refresh(new_refresh_token):
                    # 刷新成功后，需要从响应中获取新的 Cookie
                    # response.cookies 包含服务器返回的新 Cookie（如 set-cookie 头部）
                    if hasattr(response, 'cookies') and response.cookies:
                        # 将响应中的新 Cookie 更新到 session
                        for cookie_name, cookie_value in response.cookies.items():
                            self.session.cookies.set(cookie_name, cookie_value)
                            self.logger.debug(f"更新Cookie: {cookie_name}")

                    # 验证关键 Cookie 是否存在
                    sessdata = self.session.cookies.get('SESSDATA')
                    bili_jct = self.session.cookies.get('bili_jct')
                    if not sessdata or not bili_jct:
                        self.logger.warning(f"刷新后关键 Cookie 缺失: SESSDATA={bool(sessdata)}, bili_jct={bool(bili_jct)}")
                    else:
                        self.logger.debug("刷新后关键 Cookie 存在")

                    return True, {
                        'message': 'Cookie刷新成功',
                        'data': response_data,
                        'new_refresh_token': new_refresh_token,
                        'cookies': dict(self.session.cookies)
                    }
                else:
                    return False, {'message': 'Cookie刷新确认失败'}
            else:
                return False, {
                    'message': f'刷新失败: {data.get("message", "未知错误")}',
                    'code': data.get('code')
                }

        except Exception as e:
            return False, {
                'message': f'刷新请求异常: {str(e)}',
                'error': str(e)
            }

    def confirm_refresh(self, new_refresh_token: str) -> bool:
        """
        确认刷新，使旧的refresh_token失效

        Args:
            new_refresh_token: 新的刷新令牌

        Returns:
            bool: 是否成功
        """
        csrf_token = self._get_csrf_from_cookie()
        if not csrf_token:
            return False

        url = 'https://passport.bilibili.com/x/passport-login/web/confirm/refresh'

        params = {
            'csrf': csrf_token,
            'refresh_token': new_refresh_token
        }

        try:
            response = self.session.post(url, data=params)
            response.raise_for_status()
            data = response.json()

            return data.get('code') == 0

        except Exception as e:
            return False

    def get_cookie_str(self) -> str:
        """获取当前Cookie字符串"""
        return '; '.join([f'{k}={v}' for k, v in self.session.cookies.items()])

    def save_to_file(self, filename: str = 'bilibili_cookie.json'):
        """保存Cookie和refresh_token到文件"""
        data = {
            'cookie': dict(self.session.cookies),
            'refresh_token': self.refresh_token,
            'timestamp': time.time()
        }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_file(self, filename: str = 'bilibili_cookie.json') -> bool:
        """从文件加载Cookie和refresh_token"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if 'cookie' in data:
                for k, v in data['cookie'].items():
                    self.session.cookies.set(k, v)

            if 'refresh_token' in data:
                self.refresh_token = data['refresh_token']

            self.csrf_token = self._get_csrf_from_cookie()
            return True

        except Exception as e:
            return False

    def verify_cookie(self) -> Tuple[bool, Dict]:
        """
        验证当前Cookie是否有效（是否处于登录状态）

        Returns:
            Tuple[bool, Dict]: (是否有效, 状态信息)
        """
        # 检查关键Cookie是否存在
        sessdata = self.session.cookies.get('SESSDATA')
        bili_jct = self.session.cookies.get('bili_jct')
        if not sessdata or not bili_jct:
            return False, {'message': '关键Cookie缺失 (SESSDATA或bili_jct)'}

        # 调用B站API验证登录状态
        url = 'https://api.bilibili.com/x/space/myinfo'

        try:
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()

            if data.get('code') == 0:
                user_info = data.get('data', {})
                return True, {
                    'message': 'Cookie有效，已登录',
                    'user_info': {
                        'mid': user_info.get('mid'),
                        'name': user_info.get('name')
                    }
                }
            else:
                return False, {
                    'message': f'Cookie验证失败: {data.get("message", "未知错误")}',
                    'code': data.get('code')
                }
        except Exception as e:
            return False, {'message': f'验证请求异常: {str(e)}', 'error': str(e)}

    def auto_refresh_if_needed(self) -> Tuple[bool, Dict]:
        """
        自动检查并刷新Cookie（如果需要）

        Returns:
            Tuple[bool, Dict]: (是否需要刷新, 刷新结果)
        """
        # 检查Cookie状态
        status = self.check_cookie_status()

        if status.get('need_refresh'):
            return True, self.refresh_cookie()
        else:
            if status.get('code') == -101:  # 未登录
                return False, {'message': 'Cookie已过期，需要重新登录'}
            else:
                return False, {'message': 'Cookie状态正常，无需刷新'}


@dataclass
class Comment:
    """评论数据类"""
    comment_id: str
    content: str
    user: str
    uid: str
    time: int
    replied: bool = False


class BiliCommentBot:
    """B站评论自动回复机器人"""
    
    def __init__(self, config_path: str = "config.toml"):
        """初始化机器人"""
        self.config = self.load_config(config_path)
        self.setup_logging()
        self.session = requests.Session()

        # 初始化请求头池
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15'
        ]

        self.referers = [
            'https://www.bilibili.com/',
            'https://search.bilibili.com/',
            'https://t.bilibili.com/',
            'https://space.bilibili.com/'
        ]

        self.update_headers()

        # 初始化Cookie管理器
        self.cookie_manager = None
        self.last_cookie_refresh_time = 0
        self.cookie_refresh_interval = self.config['bilibili'].get('cookie_refresh_interval', 30) * 60  # 转换为秒
        self.auto_refresh_cookie = self.config['bilibili'].get('auto_refresh_cookie', True)

        if self.config['bilibili']['cookie']:
            # 尝试从文件加载Cookie
            self.cookie_manager = BilibiliCookieManager()
            if self.cookie_manager.load_from_file('bilibili_cookie.json'):
                self.logger.info("从文件加载Cookie成功")
                # 合并session
                self.session.cookies.update(self.cookie_manager.session.cookies)
            else:
                # 从配置文件加载Cookie
                cookie_str = self.config['bilibili']['cookie']
                refresh_token = self.config['bilibili'].get('refresh_token', '')
                self.cookie_manager = BilibiliCookieManager(cookie_str, refresh_token)
                self.session.cookies.update(self.cookie_manager.session.cookies)

            # 提取CSRF token
            self.csrf_token = self.cookie_manager._get_csrf_from_cookie()

            # 如果启用了自动刷新，启动时检查一次
            if self.auto_refresh_cookie and self.cookie_manager.refresh_token:
                self.logger.info("启动时检查Cookie状态...")
                self.refresh_cookie_if_needed()
        else:
            self.csrf_token = None

        self.processed_comments = set()
        self.history_file = "history.json"
        self.load_history()

        # 请求频率控制
        self.last_request_time = 0
        rate_limit_config = self.config.get('rate_limit', {})
        self.min_request_interval = rate_limit_config.get('min_request_interval', 2.0)
        self.max_retries = rate_limit_config.get('max_retries', 3)
        self.retry_delay = rate_limit_config.get('retry_delay', 5)

        # 缓存配置
        self.cache = {}
        self.cache_expire_time = 300  # 5分钟缓存过期时间

        # 动态间隔控制
        self.consecutive_failures = 0
        self.adaptive_interval = self.min_request_interval

        # 视频列表缓存配置（12小时）
        video_cache_config = self.config.get('video_cache', {})
        self.cached_videos = []
        self.last_video_fetch_time = 0
        self.video_cache_file = video_cache_config.get('cache_file', 'video_cache.json')
        self.video_cache_expire_time = video_cache_config.get('expire_time', 43200)  # 默认12小时
        self.load_video_cache()

        self.logger.info("B站评论自动回复机器人启动")
    
    def extract_csrf_token(self, cookie: str) -> Optional[str]:
        """从Cookie中提取CSRF token (bili_jct)"""
        import re
        match = re.search(r'bili_jct=([^;]+)', cookie)
        if match:
            return match.group(1)
        else:
            self.logger.warning("未在Cookie中找到bili_jct (CSRF token)")
            return None
    
    def load_history(self):
        """加载历史记录"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    # 从历史记录中恢复已处理的评论ID
                    self.processed_comments = set(item.get('comment_id') for item in history)
                    self.logger.info(f"加载历史记录，已处理 {len(self.processed_comments)} 条评论")
            else:
                self.logger.info("未找到历史记录文件，将创建新的历史记录")
        except Exception as e:
            self.logger.error(f"加载历史记录失败: {e}")
            self.processed_comments = set()
    
    def save_history(self, comment: Comment, reply_content: str):
        """保存回复历史"""
        try:
            history_item = {
                'comment_id': comment.comment_id,
                'content': comment.content,
                'user': comment.user,
                'uid': comment.uid,
                'time': comment.time,
                'reply_time': int(time.time()),
                'reply_content': reply_content,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # 读取现有历史记录
            history = []
            if os.path.exists(self.history_file):
                try:
                    with open(self.history_file, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                except:
                    history = []
            
            # 添加新记录
            history.append(history_item)
            
            # 保存到文件
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"保存回复历史: {comment.comment_id}")
        except Exception as e:
            self.logger.error(f"保存历史记录失败: {e}")
    
    def load_video_cache(self):
        """加载视频列表缓存"""
        try:
            if os.path.exists(self.video_cache_file):
                with open(self.video_cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    self.cached_videos = cache_data.get('videos', [])
                    self.last_video_fetch_time = cache_data.get('fetch_time', 0)
                    
                    cache_age = (time.time() - self.last_video_fetch_time) / 3600  # 转换为小时
                    self.logger.info(f"加载视频缓存，缓存{cache_age:.1f}小时，共{len(self.cached_videos)}个视频")
            else:
                self.logger.info("未找到视频缓存文件")
        except Exception as e:
            self.logger.error(f"加载视频缓存失败: {e}")
            self.cached_videos = []
            self.last_video_fetch_time = 0
    
    def save_video_cache(self, videos: List[Dict]):
        """保存视频列表缓存"""
        try:
            cache_data = {
                'videos': videos,
                'fetch_time': int(time.time()),
                'fetch_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            with open(self.video_cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"保存视频缓存，共{len(videos)}个视频")
        except Exception as e:
            self.logger.error(f"保存视频缓存失败: {e}")
    
    def update_headers(self):
        """更新请求头，随机化特征"""
        self.session.headers.update({
            'User-Agent': random.choice(self.user_agents),
            'Referer': random.choice(self.referers),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            # 不设置Accept-Encoding，让requests库自动处理解压
            # 'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        })
    
    def get_cache_key(self, url: str, params: dict = None) -> str:
        """生成缓存键"""
        import hashlib
        cache_data = f"{url}_{str(sorted(params.items()) if params else '')}"
        return hashlib.md5(cache_data.encode()).hexdigest()
    
    def get_from_cache(self, cache_key: str) -> Optional[dict]:
        """从缓存获取数据"""
        if cache_key in self.cache:
            data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_expire_time:
                self.logger.debug(f"使用缓存数据: {cache_key}")
                return data
            else:
                del self.cache[cache_key]
        return None
    
    def set_cache(self, cache_key: str, data: dict):
        """设置缓存"""
        self.cache[cache_key] = (data, time.time())
    
    def rate_limit_request(self):
        """动态请求频率限制"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        # 根据连续失败次数调整间隔
        if self.consecutive_failures > 0:
            self.adaptive_interval = min(
                self.min_request_interval * (1 + self.consecutive_failures * 0.5),
                self.min_request_interval * 5
            )
        else:
            self.adaptive_interval = self.min_request_interval
        
        if time_since_last_request < self.adaptive_interval:
            sleep_time = self.adaptive_interval - time_since_last_request
            # 添加随机抖动
            jitter = random.uniform(0, 0.5)
            total_sleep = sleep_time + jitter
            self.logger.debug(f"动态频率限制，等待 {total_sleep:.2f} 秒 (间隔: {self.adaptive_interval:.2f}s)")
            time.sleep(total_sleep)
        
        self.last_request_time = time.time()
        self.update_headers()  # 每次请求前更新请求头
    
    def make_request_with_retry(self, method: str, url: str, use_cache: bool = True, **kwargs) -> Optional[requests.Response]:
        """带重试机制的智能请求"""
        # 检查缓存（仅对GET请求）
        if use_cache and method.upper() == 'GET':
            cache_key = self.get_cache_key(url, kwargs.get('params'))
            cached_data = self.get_from_cache(cache_key)
            if cached_data:
                # 创建模拟响应对象
                class MockResponse:
                    def __init__(self, data):
                        self.status_code = 200
                        self.headers = {}
                        self.text = json.dumps(data) if data else ""
                        self._json = data
                    
                    def json(self):
                        if not self._json:
                            raise json.JSONDecodeError("Empty content", "", 0)
                        return self._json
                
                self.logger.debug(f"使用缓存响应: {cache_key}")
                return MockResponse(cached_data)
        
        for attempt in range(self.max_retries):
            try:
                # 应用动态频率限制
                self.rate_limit_request()
                
                response = self.session.request(method, url, **kwargs)
                
                # 检查响应状态
                if response.status_code == 429 or "请求过于频繁" in response.text:
                    self.consecutive_failures += 1
                    if attempt < self.max_retries - 1:
                        # 智能退避：检查Retry-After头部
                        retry_after = int(response.headers.get('Retry-After', self.retry_delay * (2 ** attempt)))
                        # 添加随机抖动避免同步重试
                        jitter = random.uniform(0, retry_after * 0.3)
                        wait_time = retry_after + jitter
                        
                        self.logger.warning(f"请求过于频繁，{wait_time:.1f}秒后重试 (尝试 {attempt + 1}/{self.max_retries})")
                        time.sleep(wait_time)
                        continue
                elif response.status_code >= 500:
                    self.consecutive_failures += 1
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 2)
                        self.logger.warning(f"服务器错误 {response.status_code}，{wait_time:.1f}秒后重试 (尝试 {attempt + 1}/{self.max_retries})")
                        time.sleep(wait_time)
                        continue
                else:
                    self.consecutive_failures = 0  # 重置失败计数
                
                # 检查响应内容是否为空
                if not response.text:
                    self.logger.warning(f"响应内容为空，状态码: {response.status_code}")
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 2)
                        self.logger.warning(f"{wait_time:.1f}秒后重试 (尝试 {attempt + 1}/{self.max_retries})")
                        time.sleep(wait_time)
                        continue
                    return None
                
                # 缓存成功的GET请求响应
                if use_cache and method.upper() == 'GET' and response.status_code == 200:
                    try:
                        response_text = self.decompress_response(response)
                        if response_text:
                            data = json.loads(response_text)
                            cache_key = self.get_cache_key(url, kwargs.get('params'))
                            self.set_cache(cache_key, data)
                    except:
                        pass  # 如果不是JSON响应，忽略缓存
                
                return response
                
            except requests.exceptions.RequestException as e:
                self.consecutive_failures += 1
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt) + random.uniform(0, 2)
                    self.logger.warning(f"请求异常，{wait_time:.1f}秒后重试: {e} (尝试 {attempt + 1}/{self.max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"请求失败，已达最大重试次数: {e}")
                    return None
        
        return None
    
    def load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return toml.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")
        except Exception as e:
            raise Exception(f"加载配置文件失败: {e}")
    
    def setup_logging(self):
        """设置日志"""
        log_config = self.config['logging']
        log_level = getattr(logging, log_config['level'].upper())
        
        # 创建日志目录
        log_file = log_config['file']
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 配置日志格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 设置根日志器
        self.logger = logging.getLogger('BiliCommentBot')
        self.logger.setLevel(log_level)
        
        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # 控制台处理器
        if log_config['console']:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
    
    def get_video_list(self) -> List[Dict]:
        """获取用户的视频列表（12小时缓存）"""
        uid = self.config['bilibili']['uid']
        if not uid:
            self.logger.error("未配置B站用户ID")
            return []
        
        current_time = time.time()
        time_since_last_fetch = current_time - self.last_video_fetch_time
        
        # 检查缓存是否有效
        if self.cached_videos and time_since_last_fetch < self.video_cache_expire_time:
            remaining_hours = (self.video_cache_expire_time - time_since_last_fetch) / 3600
            self.logger.info(f"使用视频列表缓存，{remaining_hours:.1f}小时后过期，共{len(self.cached_videos)}个视频")
            return self.cached_videos
        
        # 缓存过期或不存在，重新获取
        self.logger.info("视频列表缓存已过期，重新获取...")
        
        url = f"https://api.bilibili.com/x/space/arc/search"
        params = {
            'mid': uid,
            'ps': 20,
            'pn': 1,
            'order': 'pubdate'
        }
        
        try:
            response = self.make_request_with_retry('GET', url, params=params, use_cache=False)
            if not response:
                # 如果获取失败，尝试使用旧缓存
                if self.cached_videos:
                    self.logger.warning("获取视频列表失败，使用过期缓存")
                    return self.cached_videos
                return []
            
            # 解压响应内容
            response_text = self.decompress_response(response)
            
            if not response_text:
                self.logger.error("获取视频列表失败，响应内容为空")
                if self.cached_videos:
                    self.logger.warning("使用过期缓存")
                    return self.cached_videos
                return []
            
            # 尝试解析JSON
            try:
                data = json.loads(response_text)
            except json.JSONDecodeError as e:
                self.logger.error(f"视频列表JSON解析失败: {e}")
                self.logger.error(f"响应内容长度: {len(response_text)}, 前100字符: {response_text[:100]}")
                if self.cached_videos:
                    self.logger.warning("使用过期缓存")
                    return self.cached_videos
                return []
            
            if data.get('code') == 0:
                videos = data['data']['list']['vlist']
                self.cached_videos = videos
                self.last_video_fetch_time = current_time
                self.save_video_cache(videos)
                self.logger.info(f"成功获取视频列表，共 {len(videos)} 个视频")
                return videos
            else:
                self.logger.error(f"获取视频列表失败: {data.get('message')}")
                # 如果获取失败，尝试使用旧缓存
                if self.cached_videos:
                    self.logger.warning("使用过期缓存")
                    return self.cached_videos
                return []
        except Exception as e:
            self.logger.error(f"获取视频列表异常: {e}")
            # 如果获取失败，尝试使用旧缓存
            if self.cached_videos:
                self.logger.warning("使用过期缓存")
                return self.cached_videos
            return []
    
    def decompress_response(self, response) -> str:
        """解压响应内容"""
        import gzip
        import zlib
        
        try:
            # 如果response.text已经可用且不是乱码，直接返回
            if hasattr(response, 'text') and response.text:
                # 检查是否是有效的文本内容（不是二进制乱码）
                try:
                    # 尝试编码/解码来验证
                    response.text.encode('utf-8').decode('utf-8')
                    return response.text
                except:
                    pass
            
            # 获取原始内容
            content = response.content if hasattr(response, 'content') else response.text
            
            if not content:
                return ""
            
            # 检查是否是gzip压缩数据（gzip魔数：1f 8b）
            if content[:2] == b'\x1f\x8b':
                try:
                    decompressed = gzip.decompress(content)
                    return decompressed.decode('utf-8')
                except Exception as e:
                    self.logger.debug(f"gzip解压失败: {e}")
            
            # 检查是否是zlib/deflate压缩数据
            try:
                decompressed = zlib.decompress(content)
                return decompressed.decode('utf-8')
            except Exception as e:
                self.logger.debug(f"zlib解压失败: {e}")
            
            # 尝试直接解码
            if isinstance(content, bytes):
                return content.decode('utf-8', errors='ignore')
            else:
                return str(content)
            
        except Exception as e:
            self.logger.error(f"解压响应内容失败: {e}")
            # 返回原始text（如果有）
            if hasattr(response, 'text'):
                return response.text
            return ""
    
    def get_video_comments(self, bvid: str) -> List[Comment]:
        """获取视频评论（遍历所有页）"""
        url = "https://api.bilibili.com/x/v2/reply"
        aid = self.bvid_to_aid(bvid)
        
        if not aid:
            self.logger.error(f"视频 {bvid} 无法获取aid，跳过获取评论")
            return []
        
        all_comments = []
        pn = 1
        max_pn = 50  # 最大页数限制，防止无限循环
        page_size = 20  # 每页评论数（B站API限制，建议使用较小的值）
        
        while pn <= max_pn:
            params = {
                'type': 1,
                'oid': aid,
                'pn': pn,
                'ps': page_size,
                'sort': 2  # 按时间排序
            }
            
            try:
                response = self.make_request_with_retry('GET', url, params=params)
                if not response:
                    self.logger.warning(f"视频 {bvid} 第{pn}页请求失败，停止获取")
                    break
                
                # 解压响应内容
                response_text = self.decompress_response(response)
                
                if not response_text:
                    self.logger.error(f"视频 {bvid} 第{pn}页响应内容为空，停止获取")
                    break
                
                # 记录响应内容的前200个字符用于调试
                self.logger.debug(f"视频 {bvid} 第{pn}页响应内容预览: {response_text[:200]}")
                
                # 尝试解析JSON
                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    self.logger.error(f"视频 {bvid} 第{pn}页JSON解析失败: {e}")
                    self.logger.error(f"响应内容长度: {len(response_text)}, 前100字符: {response_text[:100]}")
                    break
                
                if data.get('code') == 0:
                    replies = data.get('data', {}).get('replies', [])
                    
                    if not replies:
                        # 没有更多评论了
                        self.logger.info(f"视频 {bvid} 第{pn}页无评论，停止获取")
                        break
                    
                    # 解析当前页的评论
                    for reply in replies:
                        comment = Comment(
                            comment_id=str(reply['rpid']),
                            content=reply['content']['message'],
                            user=reply['member']['uname'],
                            uid=str(reply['member']['mid']),
                            time=reply['ctime']
                        )
                        all_comments.append(comment)
                    
                    self.logger.info(f"视频 {bvid} 第{pn}页获取到 {len(replies)} 条评论，累计 {len(all_comments)} 条")
                    
                    # 检查是否还有更多页面
                    page_info = data.get('data', {}).get('page', {})
                    count = page_info.get('count', 0)  # 总评论数
                    size = page_info.get('size', page_size)  # 每页大小
                    
                    # 如果当前页的评论数小于页面大小，说明没有更多评论了
                    if len(replies) < size:
                        self.logger.info(f"视频 {bvid} 已获取所有评论，共 {len(all_comments)} 条")
                        break
                    
                    pn += 1
                else:
                    error_msg = data.get('message', '')
                    # 检查是否是ps参数超限错误
                    if 'ps out of bounds' in error_msg or '参数错误' in error_msg:
                        self.logger.warning(f"视频 {bvid} page_size={page_size} 超出限制，尝试使用更小的值")
                        # 如果第一页就失败且page_size > 10，尝试更小的值
                        if pn == 1 and page_size > 10:
                            page_size = max(10, page_size // 2)
                            self.logger.info(f"视频 {bvid} 调整 page_size 为 {page_size}，重试")
                            continue  # 使用新的page_size重试
                        else:
                            self.logger.error(f"视频 {bvid} 第{pn}页获取评论失败: {error_msg}")
                            break
                    else:
                        self.logger.error(f"视频 {bvid} 第{pn}页获取评论失败: {error_msg}")
                        break
            except Exception as e:
                self.logger.error(f"视频 {bvid} 第{pn}页获取评论异常: {e}")
                break
        
        if all_comments:
            self.logger.info(f"视频 {bvid} 总共获取到 {len(all_comments)} 条评论")
        else:
            self.logger.info(f"视频 {bvid} 暂无评论")
        
        return all_comments
    
    def bvid_to_aid(self, bvid: str) -> str:
        """将BV号转换为AV号"""
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {'bvid': bvid}
        
        try:
            response = self.make_request_with_retry('GET', url, params=params)
            if not response:
                self.logger.error(f"BV号 {bvid} 转换失败，无响应")
                return ""
            
            # 解压响应内容
            response_text = self.decompress_response(response)
            
            if not response_text:
                self.logger.error(f"BV号 {bvid} 转换失败，响应内容为空")
                return ""
            
            # 尝试解析JSON
            try:
                data = json.loads(response_text)
            except json.JSONDecodeError as e:
                self.logger.error(f"BV号 {bvid} JSON解析失败: {e}")
                self.logger.error(f"响应内容长度: {len(response_text)}, 前100字符: {response_text[:100]}")
                return ""
            
            if data.get('code') == 0:
                aid = data.get('data', {}).get('aid')
                if aid:
                    return str(aid)
                else:
                    self.logger.error(f"BV号 {bvid} 转换失败，未找到aid")
                    return ""
            else:
                self.logger.error(f"BV号 {bvid} 转换失败: {data.get('message')}")
                return ""
        except Exception as e:
            self.logger.error(f"BV号 {bvid} 转换异常: {e}")
            return ""
    
    def generate_reply(self, comment: str) -> Optional[str]:
        """使用DeepSeek API生成回复"""
        api_config = self.config['deepseek']

        headers = {
            'Authorization': f"Bearer {api_config['api_key']}",
            'Content-Type': 'application/json'
        }

        # 从配置文件读取系统提示词
        system_prompt = api_config.get('system_prompt',
            '你是一个友善的B站游戏区Minecraft UP主，请对评论做出自然、友好的回复。回复要简洁明了，控制在100字以内。')

        data = {
            'model': api_config['model'],
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': comment}
            ],
            'max_tokens': api_config['max_tokens'],
            'temperature': api_config['temperature']
        }

        try:
            response = requests.post(
                f"{api_config['base_url']}/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                reply = result['choices'][0]['message']['content'].strip()
                self.logger.info(f"DeepSeek生成回复: {reply}")
                return reply
            else:
                self.logger.error(f"DeepSeek API调用失败: {response.status_code}, {response.text}")
                return None
        except Exception as e:
            self.logger.error(f"DeepSeek API调用异常: {e}")
            return None
    
    def like_comment(self, bvid: str, comment_id: str) -> bool:
        """给评论点赞"""
        # 确保使用最新的CSRF token
        if self.cookie_manager:
            self.csrf_token = self.cookie_manager._get_csrf_from_cookie()

        if not self.csrf_token:
            self.logger.error("未找到CSRF token，无法点赞评论")
            return False

        url = "https://api.bilibili.com/x/v2/reply/action"

        data = {
            'type': 1,
            'oid': self.bvid_to_aid(bvid),
            'rpid': comment_id,
            'action': 1,  # 1表示点赞，2表示取消点赞
            'csrf': self.csrf_token
        }

        try:
            response = self.make_request_with_retry('POST', url, data=data)
            if not response:
                return False

            # 解压响应内容
            response_text = self.decompress_response(response)

            if not response_text:
                self.logger.error(f"点赞评论失败，响应内容为空")
                return False

            # 尝试解析JSON
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                self.logger.error(f"点赞评论JSON解析失败: {e}")
                self.logger.error(f"响应内容长度: {len(response_text)}, 前100字符: {response_text[:100]}")
                return False

            if result.get('code') == 0:
                self.logger.info(f"成功点赞评论 {comment_id}")
                return True
            else:
                self.logger.error(f"点赞评论失败: {result.get('message')}")
                return False
        except Exception as e:
            self.logger.error(f"点赞评论异常: {e}")
            return False
    
    def reply_comment(self, bvid: str, comment_id: str, content: str) -> bool:
        """回复评论"""
        # 确保使用最新的CSRF token
        if self.cookie_manager:
            self.csrf_token = self.cookie_manager._get_csrf_from_cookie()

        if not self.csrf_token:
            self.logger.error("未找到CSRF token，无法回复评论")
            return False

        url = "https://api.bilibili.com/x/v2/reply/add"

        # 添加回复前缀
        prefix = self.config['reply']['prefix']
        reply_content = f"{prefix}{content}"

        data = {
            'type': 1,
            'oid': self.bvid_to_aid(bvid),
            'root': comment_id,
            'parent': comment_id,
            'message': reply_content,
            'csrf': self.csrf_token
        }

        try:
            response = self.make_request_with_retry('POST', url, data=data)
            if not response:
                return False

            # 解压响应内容
            response_text = self.decompress_response(response)

            if not response_text:
                self.logger.error(f"回复评论失败，响应内容为空")
                return False

            # 尝试解析JSON
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                self.logger.error(f"回复评论JSON解析失败: {e}")
                self.logger.error(f"响应内容长度: {len(response_text)}, 前100字符: {response_text[:100]}")
                return False

            if result.get('code') == 0:
                self.logger.info(f"成功回复评论 {comment_id}: {reply_content}")
                return True
            else:
                self.logger.error(f"回复评论失败: {result.get('message')}")
                return False
        except Exception as e:
            self.logger.error(f"回复评论异常: {e}")
            return False
    
    def refresh_cookie_if_needed(self) -> bool:
        """
        检查并刷新Cookie（如果需要）

        Returns:
            bool: 是否执行了刷新操作
        """
        if not self.cookie_manager or not self.cookie_manager.refresh_token:
            return False

        # 检查是否到了刷新时间
        current_time = time.time()
        if current_time - self.last_cookie_refresh_time < self.cookie_refresh_interval:
            return False

        self.logger.info("检查Cookie状态...")
        need_refresh, result = self.cookie_manager.auto_refresh_if_needed()

        if need_refresh:
            success = result[0]
            if success:
                result_data = result[1]
                new_refresh_token = result_data.get('new_refresh_token')
                new_cookies = result_data.get('cookies')

                # 更新session的cookie
                self.session.cookies.clear()
                self.session.cookies.update(new_cookies)

                # 同步cookie_manager的cookie到main session
                self.session.cookies.update(self.cookie_manager.session.cookies)

                # 更新CSRF token
                self.csrf_token = self.cookie_manager._get_csrf_from_cookie()

                # 验证刷新后的Cookie是否有效
                self.logger.info("验证刷新后的Cookie...")
                is_valid, verify_result = self.cookie_manager.verify_cookie()
                if is_valid:
                    user_info = verify_result.get('user_info', {})
                    self.logger.info(f"刷新后的Cookie有效，用户: {user_info.get('name', 'N/A')}")
                else:
                    self.logger.warning(f"刷新后的Cookie验证失败: {verify_result.get('message')}")

                # 更新配置文件
                if new_refresh_token:
                    self.config['bilibili']['refresh_token'] = new_refresh_token
                    self.update_config_file()

                # 保存到文件
                self.cookie_manager.save_to_file('bilibili_cookie.json')

                self.last_cookie_refresh_time = current_time
                self.logger.info(f"Cookie刷新成功: {result_data.get('message')}")
                return True
            else:
                error_msg = result[1].get('message', '未知错误')
                self.logger.error(f"Cookie刷新失败: {error_msg}")
                if 'Cookie已过期' in error_msg:
                    self.logger.error("Cookie已过期，需要重新登录获取refresh_token")
        else:
            self.logger.debug(f"Cookie状态正常: {result.get('message')}")
            self.last_cookie_refresh_time = current_time

        return False

    def update_config_file(self):
        """更新配置文件"""
        try:
            with open('config.toml', 'w', encoding='utf-8') as f:
                toml.dump(self.config, f)
            self.logger.info("配置文件已更新（refresh_token）")
        except Exception as e:
            self.logger.error(f"更新配置文件失败: {e}")

    def process_comments(self):
        """处理评论"""
        # 检查并刷新Cookie（如果需要）
        if self.auto_refresh_cookie:
            self.refresh_cookie_if_needed()

        if not self.config['reply']['enabled']:
            self.logger.info("自动回复已禁用")
            return

        videos = self.get_video_list()
        if not videos:
            return

        max_process = self.config['reply']['max_process']
        processed_count = 0

        for video in videos:
            if processed_count >= max_process:
                break

            bvid = video['bvid']
            comments = self.get_video_comments(bvid)

            for comment in comments:
                if processed_count >= max_process:
                    break

                # 检查是否已处理过
                if comment.comment_id in self.processed_comments:
                    continue

                # 检查是否只处理新评论
                if self.config['reply']['only_new']:
                    # 这里可以添加更复杂的新评论判断逻辑
                    # 比如检查评论时间等
                    pass

                # 生成回复
                reply_content = self.generate_reply(comment.content)
                if reply_content:
                    # 如果启用了点赞功能，先点赞评论
                    if self.config['reply'].get('like_enabled', False):
                        self.like_comment(bvid, comment.comment_id)

                    # 发送回复
                    if self.reply_comment(bvid, comment.comment_id, reply_content):
                        self.processed_comments.add(comment.comment_id)
                        # 保存到历史记录
                        self.save_history(comment, reply_content)
                        processed_count += 1

                        # 延迟避免频繁操作
                        delay = self.config['reply']['reply_delay']
                        if delay > 0:
                            time.sleep(delay)
    
    def run(self):
        """运行机器人"""
        self.logger.info("开始运行B站评论自动回复机器人")

        try:
            while True:
                self.process_comments()

                # 等待下次检查
                interval = self.config['bilibili']['check_interval']
                self.logger.info(f"等待 {interval} 秒后进行下次检查")
                time.sleep(interval)

        except KeyboardInterrupt:
            self.logger.info("收到停止信号，机器人停止运行")
            # 退出前保存Cookie状态
            if self.cookie_manager:
                self.cookie_manager.save_to_file('bilibili_cookie.json')
                self.logger.info("Cookie状态已保存")
        except Exception as e:
            self.logger.error(f"运行异常: {e}")
            # 异常时也尝试保存Cookie状态
            if self.cookie_manager:
                try:
                    self.cookie_manager.save_to_file('bilibili_cookie.json')
                except:
                    pass
            raise


def main():
    """主函数"""
    try:
        bot = BiliCommentBot()
        bot.run()
    except Exception as e:
        print(f"启动失败: {e}")


if __name__ == "__main__":
    main()