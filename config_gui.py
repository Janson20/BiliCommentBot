#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站评论自动回复机器人配置工具
GUI界面用于编辑config.toml配置文件
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import tomllib
import tomli_w
from pathlib import Path
from typing import Any


class ConfigEditor:
    def __init__(self, root: tk.Tk, config_path: str):
        self.root = root
        self.config_path = Path(config_path)
        self.config_data = {}
        self.widgets = {}
        
        self.root.title("B站评论机器人配置工具")
        self.root.geometry("800x700")
        self.root.minsize(700, 600)
        
        # 创建主框架
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建Notebook（标签页）
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 底部按钮框架
        self.button_frame = ttk.Frame(self.main_frame)
        self.button_frame.pack(fill=tk.X)
        
        # 加载配置
        self.load_config()
        
        # 创建各配置页面
        self.create_bilibili_tab()
        self.create_rate_limit_tab()
        self.create_cache_tab()
        self.create_deepseek_tab()
        self.create_reply_tab()
        self.create_logging_tab()
        
        # 添加按钮
        self.create_buttons()
    
    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_path, "rb") as f:
                self.config_data = tomllib.load(f)
        except FileNotFoundError:
            messagebox.showwarning("警告", f"配置文件 {self.config_path} 不存在，将创建新配置")
            self.config_data = {}
        except Exception as e:
            messagebox.showerror("错误", f"加载配置文件失败: {e}")
            self.config_data = {}
    
    def save_config(self):
        """保存配置文件"""
        try:
            # 收集所有输入值
            self.collect_values()
            
            # 写入文件
            with open(self.config_path, "wb") as f:
                tomli_w.dump(self.config_data, f)
            
            messagebox.showinfo("成功", "配置已保存！")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")
    
    def collect_values(self):
        """从控件收集值"""
        for key, widget_info in self.widgets.items():
            widget, field_type = widget_info
            section, field = key.split(".", 1)
            
            if section not in self.config_data:
                self.config_data[section] = {}
            
            if field_type == "bool":
                self.config_data[section][field] = widget.get()
            elif field_type == "int":
                value = widget.get().strip()
                self.config_data[section][field] = int(value) if value else 0
            elif field_type == "float":
                value = widget.get().strip()
                self.config_data[section][field] = float(value) if value else 0.0
            elif field_type == "string":
                self.config_data[section][field] = widget.get().strip()
            elif field_type == "text":
                self.config_data[section][field] = widget.get("1.0", tk.END).strip()
    
    def get_value(self, section: str, field: str, default: Any = "") -> Any:
        """获取配置值"""
        try:
            return self.config_data.get(section, {}).get(field, default)
        except:
            return default
    
    def create_bilibili_tab(self):
        """创建B站配置标签页"""
        frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(frame, text="B站配置")
        
        # Cookie配置
        ttk.Label(frame, text="B站Cookie（从浏览器获取）:").pack(anchor=tk.W)
        cookie_text = scrolledtext.ScrolledText(frame, height=4, width=60)
        cookie_text.pack(fill=tk.X, pady=(0, 10))
        cookie_text.insert("1.0", self.get_value("bilibili", "cookie", ""))
        self.widgets["bilibili.cookie"] = (cookie_text, "text")
        
        # 刷新令牌
        ttk.Label(frame, text="刷新令牌（用于自动刷新Cookie）:").pack(anchor=tk.W)
        refresh_token_entry = ttk.Entry(frame, width=60)
        refresh_token_entry.pack(fill=tk.X, pady=(0, 10))
        refresh_token_entry.insert(0, self.get_value("bilibili", "refresh_token", ""))
        self.widgets["bilibili.refresh_token"] = (refresh_token_entry, "string")
        
        # 用户ID
        ttk.Label(frame, text="B站用户ID:").pack(anchor=tk.W)
        uid_entry = ttk.Entry(frame, width=60)
        uid_entry.pack(fill=tk.X, pady=(0, 10))
        uid_entry.insert(0, self.get_value("bilibili", "uid", ""))
        self.widgets["bilibili.uid"] = (uid_entry, "string")
        
        # 检查间隔
        ttk.Label(frame, text="检查评论间隔时间（秒）:").pack(anchor=tk.W)
        check_interval_entry = ttk.Entry(frame, width=20)
        check_interval_entry.pack(anchor=tk.W, pady=(0, 10))
        check_interval_entry.insert(0, str(self.get_value("bilibili", "check_interval", 60)))
        self.widgets["bilibili.check_interval"] = (check_interval_entry, "int")
        
        # 自动刷新Cookie
        auto_refresh_var = tk.BooleanVar(value=self.get_value("bilibili", "auto_refresh_cookie", True))
        auto_refresh_check = ttk.Checkbutton(frame, text="启用Cookie自动刷新", variable=auto_refresh_var)
        auto_refresh_check.pack(anchor=tk.W, pady=(0, 10))
        self.widgets["bilibili.auto_refresh_cookie"] = (auto_refresh_var, "bool")
        
        # Cookie刷新间隔
        ttk.Label(frame, text="Cookie刷新检查间隔（分钟）:").pack(anchor=tk.W)
        refresh_interval_entry = ttk.Entry(frame, width=20)
        refresh_interval_entry.pack(anchor=tk.W, pady=(0, 10))
        refresh_interval_entry.insert(0, str(self.get_value("bilibili", "cookie_refresh_interval", 30)))
        self.widgets["bilibili.cookie_refresh_interval"] = (refresh_interval_entry, "int")

        # 最大评论页数
        ttk.Label(frame, text="获取评论的最大页数:").pack(anchor=tk.W)
        max_pages_entry = ttk.Entry(frame, width=20)
        max_pages_entry.pack(anchor=tk.W, pady=(0, 10))
        max_pages_entry.insert(0, str(self.get_value("bilibili", "max_comment_pages", 10)))
        self.widgets["bilibili.max_comment_pages"] = (max_pages_entry, "int")
    
    def create_rate_limit_tab(self):
        """创建频率限制配置标签页"""
        frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(frame, text="频率限制")
        
        # 最小请求间隔
        ttk.Label(frame, text="最小请求间隔（秒）:").pack(anchor=tk.W)
        min_interval_entry = ttk.Entry(frame, width=20)
        min_interval_entry.pack(anchor=tk.W, pady=(0, 10))
        min_interval_entry.insert(0, str(self.get_value("rate_limit", "min_request_interval", 2.0)))
        self.widgets["rate_limit.min_request_interval"] = (min_interval_entry, "float")
        
        # 最大重试次数
        ttk.Label(frame, text="最大重试次数:").pack(anchor=tk.W)
        max_retries_entry = ttk.Entry(frame, width=20)
        max_retries_entry.pack(anchor=tk.W, pady=(0, 10))
        max_retries_entry.insert(0, str(self.get_value("rate_limit", "max_retries", 3)))
        self.widgets["rate_limit.max_retries"] = (max_retries_entry, "int")
        
        # 重试延迟
        ttk.Label(frame, text="重试基础延迟（秒）:").pack(anchor=tk.W)
        retry_delay_entry = ttk.Entry(frame, width=20)
        retry_delay_entry.pack(anchor=tk.W, pady=(0, 10))
        retry_delay_entry.insert(0, str(self.get_value("rate_limit", "retry_delay", 5)))
        self.widgets["rate_limit.retry_delay"] = (retry_delay_entry, "int")
    
    def create_cache_tab(self):
        """创建缓存配置标签页"""
        frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(frame, text="缓存配置")
        
        # 缓存启用
        cache_enabled_var = tk.BooleanVar(value=self.get_value("cache", "enabled", True))
        cache_enabled_check = ttk.Checkbutton(frame, text="启用缓存", variable=cache_enabled_var)
        cache_enabled_check.pack(anchor=tk.W, pady=(0, 10))
        self.widgets["cache.enabled"] = (cache_enabled_var, "bool")
        
        # 缓存过期时间
        ttk.Label(frame, text="缓存过期时间（秒）:").pack(anchor=tk.W)
        cache_expire_entry = ttk.Entry(frame, width=20)
        cache_expire_entry.pack(anchor=tk.W, pady=(0, 20))
        cache_expire_entry.insert(0, str(self.get_value("cache", "expire_time", 300)))
        self.widgets["cache.expire_time"] = (cache_expire_entry, "int")
        
        # 分隔线
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(frame, text="视频列表缓存配置", font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        # 视频缓存过期时间
        ttk.Label(frame, text="视频列表缓存时间（秒，默认43200=12小时）:").pack(anchor=tk.W)
        video_cache_expire_entry = ttk.Entry(frame, width=20)
        video_cache_expire_entry.pack(anchor=tk.W, pady=(0, 10))
        video_cache_expire_entry.insert(0, str(self.get_value("video_cache", "expire_time", 43200)))
        self.widgets["video_cache.expire_time"] = (video_cache_expire_entry, "int")
        
        # 缓存文件路径
        ttk.Label(frame, text="缓存文件路径:").pack(anchor=tk.W)
        cache_file_entry = ttk.Entry(frame, width=40)
        cache_file_entry.pack(anchor=tk.W, pady=(0, 10))
        cache_file_entry.insert(0, self.get_value("video_cache", "cache_file", "video_cache.json"))
        self.widgets["video_cache.cache_file"] = (cache_file_entry, "string")
    
    def create_deepseek_tab(self):
        """创建DeepSeek配置标签页"""
        frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(frame, text="DeepSeek配置")
        
        # API密钥
        ttk.Label(frame, text="DeepSeek API密钥:").pack(anchor=tk.W)
        api_key_entry = ttk.Entry(frame, width=60)
        api_key_entry.pack(fill=tk.X, pady=(0, 10))
        api_key_entry.insert(0, self.get_value("deepseek", "api_key", ""))
        self.widgets["deepseek.api_key"] = (api_key_entry, "string")
        
        # API基础URL
        ttk.Label(frame, text="API基础URL:").pack(anchor=tk.W)
        base_url_entry = ttk.Entry(frame, width=60)
        base_url_entry.pack(fill=tk.X, pady=(0, 10))
        base_url_entry.insert(0, self.get_value("deepseek", "base_url", "https://api.deepseek.com/v1"))
        self.widgets["deepseek.base_url"] = (base_url_entry, "string")
        
        # 模型
        ttk.Label(frame, text="使用的模型:").pack(anchor=tk.W)
        model_entry = ttk.Entry(frame, width=40)
        model_entry.pack(anchor=tk.W, pady=(0, 10))
        model_entry.insert(0, self.get_value("deepseek", "model", "deepseek-chat"))
        self.widgets["deepseek.model"] = (model_entry, "string")
        
        # 最大回复长度
        ttk.Label(frame, text="最大回复长度（tokens）:").pack(anchor=tk.W)
        max_tokens_entry = ttk.Entry(frame, width=20)
        max_tokens_entry.pack(anchor=tk.W, pady=(0, 10))
        max_tokens_entry.insert(0, str(self.get_value("deepseek", "max_tokens", 200)))
        self.widgets["deepseek.max_tokens"] = (max_tokens_entry, "int")
        
        # 温度参数
        ttk.Label(frame, text="温度参数（0-1，控制回复随机性）:").pack(anchor=tk.W)
        temperature_entry = ttk.Entry(frame, width=20)
        temperature_entry.pack(anchor=tk.W, pady=(0, 10))
        temperature_entry.insert(0, str(self.get_value("deepseek", "temperature", 0.7)))
        self.widgets["deepseek.temperature"] = (temperature_entry, "float")
        
        # 系统提示词
        ttk.Label(frame, text="系统提示词（定义AI角色和行为）:").pack(anchor=tk.W)
        system_prompt_text = scrolledtext.ScrolledText(frame, height=6, width=60)
        system_prompt_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        system_prompt_text.insert("1.0", self.get_value("deepseek", "system_prompt", ""))
        self.widgets["deepseek.system_prompt"] = (system_prompt_text, "text")
    
    def create_reply_tab(self):
        """创建回复配置标签页"""
        frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(frame, text="回复配置")
        
        # 启用自动回复
        enabled_var = tk.BooleanVar(value=self.get_value("reply", "enabled", True))
        enabled_check = ttk.Checkbutton(frame, text="启用自动回复", variable=enabled_var)
        enabled_check.pack(anchor=tk.W, pady=(0, 10))
        self.widgets["reply.enabled"] = (enabled_var, "bool")
        
        # 回复前缀
        ttk.Label(frame, text="回复前缀:").pack(anchor=tk.W)
        prefix_entry = ttk.Entry(frame, width=40)
        prefix_entry.pack(anchor=tk.W, pady=(0, 10))
        prefix_entry.insert(0, self.get_value("reply", "prefix", "🤖 "))
        self.widgets["reply.prefix"] = (prefix_entry, "string")
        
        # 只回复未处理的评论
        only_new_var = tk.BooleanVar(value=self.get_value("reply", "only_new", True))
        only_new_check = ttk.Checkbutton(frame, text="只回复未处理的评论", variable=only_new_var)
        only_new_check.pack(anchor=tk.W, pady=(0, 10))
        self.widgets["reply.only_new"] = (only_new_var, "bool")
        
        # 每次最多处理的评论数
        ttk.Label(frame, text="每次最多处理的评论数:").pack(anchor=tk.W)
        max_process_entry = ttk.Entry(frame, width=20)
        max_process_entry.pack(anchor=tk.W, pady=(0, 10))
        max_process_entry.insert(0, str(self.get_value("reply", "max_process", 10)))
        self.widgets["reply.max_process"] = (max_process_entry, "int")
        
        # 回复延迟
        ttk.Label(frame, text="回复延迟（秒，避免频繁操作）:").pack(anchor=tk.W)
        reply_delay_entry = ttk.Entry(frame, width=20)
        reply_delay_entry.pack(anchor=tk.W, pady=(0, 10))
        reply_delay_entry.insert(0, str(self.get_value("reply", "reply_delay", 2)))
        self.widgets["reply.reply_delay"] = (reply_delay_entry, "int")
        
        # 点赞功能
        like_enabled_var = tk.BooleanVar(value=self.get_value("reply", "like_enabled", True))
        like_enabled_check = ttk.Checkbutton(frame, text="回复评论时同时点赞", variable=like_enabled_var)
        like_enabled_check.pack(anchor=tk.W, pady=(0, 10))
        self.widgets["reply.like_enabled"] = (like_enabled_var, "bool")
        
        # 上下文评论数
        ttk.Label(frame, text="生成回复时使用前N条评论作为上下文（0表示不使用）:").pack(anchor=tk.W)
        context_count_entry = ttk.Entry(frame, width=20)
        context_count_entry.pack(anchor=tk.W, pady=(0, 10))
        context_count_entry.insert(0, str(self.get_value("reply", "context_comments_count", 10)))
        self.widgets["reply.context_comments_count"] = (context_count_entry, "int")
    
    def create_logging_tab(self):
        """创建日志配置标签页"""
        frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(frame, text="日志配置")
        
        # 日志级别
        ttk.Label(frame, text="日志级别:").pack(anchor=tk.W)
        level_combo = ttk.Combobox(frame, values=["DEBUG", "INFO", "WARNING", "ERROR"], width=20, state="readonly")
        level_combo.pack(anchor=tk.W, pady=(0, 10))
        level_combo.set(self.get_value("logging", "level", "INFO"))
        self.widgets["logging.level"] = (level_combo, "string")
        
        # 日志文件路径
        ttk.Label(frame, text="日志文件路径:").pack(anchor=tk.W)
        log_file_entry = ttk.Entry(frame, width=40)
        log_file_entry.pack(anchor=tk.W, pady=(0, 10))
        log_file_entry.insert(0, self.get_value("logging", "file", "logs/bot.log"))
        self.widgets["logging.file"] = (log_file_entry, "string")
        
        # 控制台输出
        console_var = tk.BooleanVar(value=self.get_value("logging", "console", True))
        console_check = ttk.Checkbutton(frame, text="输出到控制台", variable=console_var)
        console_check.pack(anchor=tk.W, pady=(0, 10))
        self.widgets["logging.console"] = (console_var, "bool")
    
    def create_buttons(self):
        """创建底部按钮"""
        # 保存按钮
        save_btn = ttk.Button(self.button_frame, text="保存配置", command=self.save_config)
        save_btn.pack(side=tk.RIGHT, padx=5)
        
        # 重置按钮
        reset_btn = ttk.Button(self.button_frame, text="重新加载", command=self.reset_config)
        reset_btn.pack(side=tk.RIGHT, padx=5)
    
    def reset_config(self):
        """重新加载配置"""
        if messagebox.askyesno("确认", "确定要重新加载配置吗？当前未保存的修改将丢失。"):
            self.load_config()
            # 刷新所有标签页
            self.notebook.destroy()
            self.widgets.clear()
            
            self.notebook = ttk.Notebook(self.main_frame)
            self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
            
            self.create_bilibili_tab()
            self.create_rate_limit_tab()
            self.create_cache_tab()
            self.create_deepseek_tab()
            self.create_reply_tab()
            self.create_logging_tab()


def main():
    """主函数"""
    # 获取配置文件路径
    config_path = Path(__file__).parent / "config.toml"
    
    root = tk.Tk()
    app = ConfigEditor(root, str(config_path))
    root.mainloop()


if __name__ == "__main__":
    main()
