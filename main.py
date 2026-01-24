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
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass


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
        
        if self.config['bilibili']['cookie']:
            self.session.headers.update({
                'Cookie': self.config['bilibili']['cookie']
            })
            # 提取CSRF token
            self.csrf_token = self.extract_csrf_token(self.config['bilibili']['cookie'])
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
            'Accept-Encoding': 'gzip, deflate, br',
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
                        self.text = json.dumps(data)
                        self._json = data
                    
                    def json(self):
                        return self._json
                
                return MockResponse(cached_data)
        
        for attempt in range(self.max_retries):
            try:
                # 应用动态频率限制
                self.rate_limit_request()
                
                response = self.session.request(method, url, **kwargs)
                
                # 检查是否为频率限制错误
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
                else:
                    self.consecutive_failures = 0  # 重置失败计数
                
                # 缓存成功的GET请求响应
                if use_cache and method.upper() == 'GET' and response.status_code == 200:
                    try:
                        data = response.json()
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
            'ps': 30,
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
            
            data = response.json()
            
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
    
    def get_video_comments(self, bvid: str) -> List[Comment]:
        """获取视频评论"""
        url = "https://api.bilibili.com/x/v2/reply"
        params = {
            'type': 1,
            'oid': self.bvid_to_aid(bvid),
            'pn': 1,
            'ps': 20,
            'sort': 2  # 按时间排序
        }
        
        try:
            response = self.make_request_with_retry('GET', url, params=params)
            if not response:
                return []
            
            data = response.json()
            
            if data.get('code') == 0:
                comments = []
                for reply in data['data']['replies']:
                    comment = Comment(
                        comment_id=str(reply['rpid']),
                        content=reply['content']['message'],
                        user=reply['member']['uname'],
                        uid=str(reply['member']['mid']),
                        time=reply['ctime']
                    )
                    comments.append(comment)
                
                self.logger.info(f"视频 {bvid} 获取到 {len(comments)} 条评论")
                return comments
            else:
                self.logger.error(f"获取评论失败: {data.get('message')}")
                return []
        except Exception as e:
            self.logger.error(f"获取评论异常: {e}")
            return []
    
    def bvid_to_aid(self, bvid: str) -> str:
        """将BV号转换为AV号"""
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {'bvid': bvid}
        
        try:
            response = self.make_request_with_retry('GET', url, params=params)
            if not response:
                return []
            
            data = response.json()
            
            if data.get('code') == 0:
                return str(data['data']['aid'])
            else:
                self.logger.error(f"BV号转换失败: {data.get('message')}")
                return ""
        except Exception as e:
            self.logger.error(f"BV号转换异常: {e}")
            return ""
    
    def generate_reply(self, comment: str) -> Optional[str]:
        """使用DeepSeek API生成回复"""
        api_config = self.config['deepseek']
        
        headers = {
            'Authorization': f"Bearer {api_config['api_key']}",
            'Content-Type': 'application/json'
        }
        
        prompt = f"""你是一个友善的B站游戏区Minecraft UP主，请对以下评论做出自然、友好的回复。回复要简洁明了，控制在100字以内。

评论内容：{comment}

请直接给出回复内容，不要包含其他解释。"""
        
        data = {
            'model': api_config['model'],
            'messages': [
                {'role': 'user', 'content': prompt}
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
    
    def reply_comment(self, bvid: str, comment_id: str, content: str) -> bool:
        """回复评论"""
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
            
            result = response.json()
            
            if result.get('code') == 0:
                self.logger.info(f"成功回复评论 {comment_id}: {reply_content}")
                return True
            else:
                self.logger.error(f"回复评论失败: {result.get('message')}")
                return False
        except Exception as e:
            self.logger.error(f"回复评论异常: {e}")
            return False
    
    def process_comments(self):
        """处理评论"""
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
        except Exception as e:
            self.logger.error(f"运行异常: {e}")
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