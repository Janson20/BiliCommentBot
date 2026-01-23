#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
频率限制监控工具
用于监控和分析API请求频率，提供优化建议
"""

import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from collections import defaultdict, deque

class RateLimitMonitor:
    """频率限制监控器"""
    
    def __init__(self, window_size: int = 300):
        """
        初始化监控器
        
        Args:
            window_size: 监控窗口大小（秒），默认5分钟
        """
        self.window_size = window_size
        self.requests = deque()  # 存储请求时间戳
        self.failures = deque()   # 存储失败时间戳
        self.response_times = deque()  # 存储响应时间
        self.status_codes = defaultdict(int)  # 状态码统计
        
        # 统计数据
        self.total_requests = 0
        self.total_failures = 0
        self.total_429 = 0  # 429错误计数
        
        self.logger = logging.getLogger(__name__)
    
    def record_request(self, status_code: int, response_time: float, is_failure: bool = False):
        """
        记录请求
        
        Args:
            status_code: HTTP状态码
            response_time: 响应时间（秒）
            is_failure: 是否为失败请求
        """
        current_time = time.time()
        
        # 记录请求
        self.requests.append(current_time)
        self.response_times.append(response_time)
        self.status_codes[status_code] += 1
        self.total_requests += 1
        
        # 记录失败
        if is_failure or status_code == 429:
            self.failures.append(current_time)
            self.total_failures += 1
            if status_code == 429:
                self.total_429 += 1
        
        # 清理过期数据
        self._cleanup_old_data(current_time)
    
    def _cleanup_old_data(self, current_time: float):
        """清理过期数据"""
        cutoff_time = current_time - self.window_size
        
        while self.requests and self.requests[0] < cutoff_time:
            self.requests.popleft()
        
        while self.failures and self.failures[0] < cutoff_time:
            self.failures.popleft()
        
        while self.response_times and len(self.response_times) > len(self.requests):
            self.response_times.popleft()
    
    def get_current_rate(self) -> float:
        """获取当前请求频率（请求/秒）"""
        if not self.requests:
            return 0.0
        return len(self.requests) / self.window_size
    
    def get_failure_rate(self) -> float:
        """获取当前失败率"""
        if not self.requests:
            return 0.0
        return len(self.failures) / len(self.requests) if self.requests else 0.0
    
    def get_avg_response_time(self) -> float:
        """获取平均响应时间"""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)
    
    def get_recommendations(self) -> List[str]:
        """获取优化建议"""
        recommendations = []
        current_rate = self.get_current_rate()
        failure_rate = self.get_failure_rate()
        
        # 频率建议
        if current_rate > 0.5:  # 超过每秒0.5个请求
            recommendations.append(f"当前请求频率较高({current_rate:.2f}/s)，建议增加请求间隔")
        
        # 失败率建议
        if failure_rate > 0.1:  # 失败率超过10%
            recommendations.append(f"失败率较高({failure_rate:.1%})，建议检查请求参数或增加重试间隔")
        
        # 429错误建议
        if self.total_429 > 0:
            recommendations.append(f"检测到{self.total_429}次429错误，建议大幅降低请求频率")
        
        # 响应时间建议
        avg_time = self.get_avg_response_time()
        if avg_time > 2.0:  # 响应时间超过2秒
            recommendations.append(f"平均响应时间较长({avg_time:.2f}s)，可能存在网络问题")
        
        # 状态码分析
        if self.status_codes.get(403, 0) > 0:
            recommendations.append("检测到403错误，可能需要更新Cookie或User-Agent")
        
        if not recommendations:
            recommendations.append("请求状态良好，当前配置合适")
        
        return recommendations
    
    def get_statistics(self) -> Dict:
        """获取详细统计信息"""
        return {
            'time_window': self.window_size,
            'current_rate': self.get_current_rate(),
            'failure_rate': self.get_failure_rate(),
            'avg_response_time': self.get_avg_response_time(),
            'total_requests': self.total_requests,
            'total_failures': self.total_failures,
            'total_429': self.total_429,
            'status_codes': dict(self.status_codes),
            'recommendations': self.get_recommendations()
        }
    
    def print_report(self):
        """打印监控报告"""
        stats = self.get_statistics()
        
        print("\n" + "="*50)
        print("频率限制监控报告")
        print("="*50)
        print(f"监控窗口: {stats['time_window']}秒")
        print(f"当前请求频率: {stats['current_rate']:.2f} 请求/秒")
        print(f"当前失败率: {stats['failure_rate']:.1%}")
        print(f"平均响应时间: {stats['avg_response_time']:.2f}秒")
        print(f"总请求数: {stats['total_requests']}")
        print(f"总失败数: {stats['total_failures']}")
        print(f"429错误数: {stats['total_429']}")
        
        print("\n状态码统计:")
        for code, count in stats['status_codes'].items():
            print(f"  {code}: {count}")
        
        print("\n优化建议:")
        for i, rec in enumerate(stats['recommendations'], 1):
            print(f"  {i}. {rec}")
        
        print("="*50)
    
    def save_report(self, filename: str = None):
        """保存监控报告到文件"""
        if filename is None:
            filename = f"rate_limit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        stats = self.get_statistics()
        stats['timestamp'] = datetime.now().isoformat()
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"监控报告已保存到: {filename}")


# 使用示例
if __name__ == "__main__":
    # 创建监控器
    monitor = RateLimitMonitor(window_size=300)
    
    # 模拟一些请求
    for i in range(10):
        status = 200 if i % 3 != 0 else 429
        response_time = 0.5 + (i % 3) * 0.2
        is_failure = status == 429
        
        monitor.record_request(status, response_time, is_failure)
        time.sleep(1)  # 模拟请求间隔
    
    # 打印报告
    monitor.print_report()
    
    # 保存报告
    monitor.save_report()