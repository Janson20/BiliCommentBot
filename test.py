#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站评论自动回复机器人测试脚本
测试各项功能是否正常工作
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from main import BiliCommentBot, Comment

# 设置测试日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title):
    """打印测试分节标题"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def test_config_loading():
    """测试配置加载"""
    print_section("测试配置加载")
    try:
        bot = BiliCommentBot()
        logger.info("✓ 配置文件加载成功")
        logger.info(f"  - UID: {bot.config['bilibili'].get('uid', '未配置')}")
        logger.info(f"  - 检查间隔: {bot.config['bilibili'].get('check_interval', 0)}秒")
        logger.info(f"  - DeepSeek模型: {bot.config['deepseek'].get('model', 'N/A')}")
        logger.info(f"  - 回复启用: {bot.config['reply'].get('enabled', False)}")
        logger.info(f"  - 上下文评论数: {bot.config['reply'].get('context_comments_count', 0)}")
        return bot
    except Exception as e:
        logger.error(f"✗ 配置加载失败: {e}")
        return None


def test_cookie_manager(bot):
    """测试Cookie管理"""
    print_section("测试Cookie管理")

    if not bot.cookie_manager:
        logger.warning("⚠ Cookie管理器未初始化，跳过测试")
        return

    # 检查CSRF token
    csrf_token = bot.cookie_manager._get_csrf_from_cookie()
    if csrf_token:
        logger.info(f"✓ CSRF token存在: {csrf_token[:10]}...")
    else:
        logger.error("✗ 未找到CSRF token (bili_jct)")
        return

    # 验证Cookie有效性
    is_valid, result = bot.cookie_manager.verify_cookie()
    if is_valid:
        user_info = result.get('user_info', {})
        logger.info(f"✓ Cookie有效，用户: {user_info.get('name', 'N/A')} (ID: {user_info.get('mid', 'N/A')})")
    else:
        logger.warning(f"⚠ Cookie验证失败: {result.get('message')}")

    # 检查Cookie状态
    status = bot.cookie_manager.check_cookie_status()
    logger.info(f"  - 需要刷新: {status.get('need_refresh', False)}")
    logger.info(f"  - 状态消息: {status.get('message')}")


def test_video_list(bot):
    """测试视频列表获取"""
    print_section("测试视频列表获取")

    videos = bot.get_video_list()

    if videos:
        logger.info(f"✓ 成功获取视频列表，共 {len(videos)} 个视频")
        # 显示前3个视频
        for i, video in enumerate(videos[:3], 1):
            logger.info(f"\n  视频 {i}:")
            logger.info(f"    - BV号: {video.get('bvid')}")
            logger.info(f"    - 标题: {video.get('title')}")
            logger.info(f"    - 描述: {video.get('description', 'N/A')[:50]}...")
            logger.info(f"    - 播放量: {video.get('play', 0)}, 评论数: {video.get('comment', 0)}")
        return videos
    else:
        logger.warning("⚠ 未获取到视频列表")
        return []


def test_comment_fetching(bot, videos):
    """测试评论获取"""
    print_section("测试评论获取")

    if not videos:
        logger.warning("⚠ 没有可测试的视频")
        return []

    # 选择第一个视频进行测试
    video = videos[0]
    bvid = video['bvid']
    logger.info(f"测试视频: {video.get('title')} ({bvid})")

    comments = bot.get_video_comments(bvid)

    if comments:
        logger.info(f"✓ 成功获取评论，共 {len(comments)} 条")
        # 显示前3条评论
        for i, comment in enumerate(comments[:3], 1):
            logger.info(f"\n  评论 {i}:")
            logger.info(f"    - ID: {comment.comment_id}")
            logger.info(f"    - 用户: {comment.user}")
            logger.info(f"    - 内容: {comment.content}")
            logger.info(f"    - 时间: {datetime.fromtimestamp(comment.time).strftime('%Y-%m-%d %H:%M:%S')}")
        return comments
    else:
        logger.warning("⚠ 该视频暂无评论")
        return []


def test_reply_generation(bot, comments):
    """测试回复生成（带上下文和不带上下文）"""
    print_section("测试回复生成")

    if not comments:
        logger.warning("⚠ 没有可测试的评论")
        return

    # 选择第二条评论进行测试（第一条可能没有上下文）
    if len(comments) < 2:
        logger.warning("⚠ 评论数量不足，无法测试上下文功能")
        test_comment = comments[0]
    else:
        test_comment = comments[1]

    logger.info(f"测试评论: {test_comment.content}")

    # 测试1: 不带上下文
    logger.info("\n--- 测试1: 不带上下文生成回复 ---")
    reply_without_context = bot.generate_reply(test_comment.content, context=None)
    if reply_without_context:
        logger.info(f"✓ 回复生成成功: {reply_without_context}")
    else:
        logger.error("✗ 回复生成失败")

    # 测试2: 带上下文
    context_count = bot.config['reply'].get('context_comments_count', 10)
    if len(comments) > 1 and context_count > 0:
        logger.info(f"\n--- 测试2: 带上下文生成回复 (使用前 {min(context_count, comments.index(test_comment))} 条评论) ---")

        # 获取上下文评论
        idx = comments.index(test_comment)
        start_idx = max(0, idx - context_count)
        context_comments = comments[start_idx:idx]

        logger.info("上下文评论:")
        for i, ctx in enumerate(context_comments, 1):
            logger.info(f"  {i}. {ctx.user}: {ctx.content}")

        reply_with_context = bot.generate_reply(test_comment.content, context_comments)
        if reply_with_context:
            logger.info(f"✓ 回复生成成功: {reply_with_context}")
        else:
            logger.error("✗ 回复生成失败")


def test_cache_mechanism(bot):
    """测试缓存机制"""
    print_section("测试缓存机制")

    # 测试响应缓存
    logger.info("--- 测试响应缓存 ---")
    cache_size = len(bot.cache)
    logger.info(f"当前缓存数量: {cache_size}")

    # 测试视频缓存
    logger.info("\n--- 测试视频缓存 ---")
    if bot.cached_videos:
        cache_age = (time.time() - bot.last_video_fetch_time) / 3600
        logger.info(f"✓ 视频缓存存在，缓存时长: {cache_age:.1f} 小时")
        logger.info(f"  - 缓存视频数: {len(bot.cached_videos)}")
        logger.info(f"  - 缓存过期时间: {bot.video_cache_expire_time} 秒")
    else:
        logger.info("视频缓存为空")


def test_rate_limit(bot):
    """测试频率限制"""
    print_section("测试频率限制")

    logger.info(f"最小请求间隔: {bot.min_request_interval} 秒")
    logger.info(f"最大重试次数: {bot.max_retries}")
    logger.info(f"重试基础延迟: {bot.retry_delay} 秒")
    logger.info(f"当前自适应间隔: {bot.adaptive_interval:.2f} 秒")
    logger.info(f"连续失败次数: {bot.consecutive_failures}")


def test_history_loading(bot):
    """测试历史记录加载"""
    print_section("测试历史记录")

    if os.path.exists(bot.history_file):
        try:
            with open(bot.history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
            logger.info(f"✓ 历史记录文件存在，共 {len(history)} 条记录")

            if history:
                # 显示最近3条记录
                logger.info("\n最近回复记录:")
                for item in history[-3:]:
                    logger.info(f"  - 评论: {item.get('content', 'N/A')[:40]}...")
                    logger.info(f"    回复: {item.get('reply_content', 'N/A')[:40]}...")
                    logger.info(f"    时间: {item.get('timestamp', 'N/A')}")
        except Exception as e:
            logger.error(f"✗ 读取历史记录失败: {e}")
    else:
        logger.info("历史记录文件不存在")


def dry_run_reply_test(bot, comments):
    """模拟回复测试（不实际发送）"""
    print_section("模拟回复测试 (不实际发送)")

    if not comments:
        logger.warning("⚠ 没有可测试的评论")
        return

    # 限制测试数量，避免过多请求
    test_count = min(2, len(comments))
    logger.info(f"将测试前 {test_count} 条评论的回复生成\n")

    for i, comment in enumerate(comments[:test_count], 1):
        logger.info(f"--- 测试评论 {i} ---")
        logger.info(f"用户: {comment.user}")
        logger.info(f"内容: {comment.content}")

        # 获取上下文
        context_count = bot.config['reply'].get('context_comments_count', 10)
        context_comments = []
        if context_count > 0 and i > 1:
            idx = comments.index(comment)
            start_idx = max(0, idx - context_count)
            context_comments = comments[start_idx:idx]
            logger.info(f"使用 {len(context_comments)} 条评论作为上下文")

        # 生成回复
        reply = bot.generate_reply(comment.content, context_comments)
        if reply:
            logger.info(f"✓ 回复: {reply}")
        else:
            logger.error("✗ 回复生成失败")

        # 模拟延迟
        if i < test_count:
            time.sleep(2)


def main():
    """主测试函数"""
    print("\n" + "#"*60)
    print("#  B站评论自动回复机器人 - 测试脚本")
    print(f"#  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#"*60)

    # 1. 测试配置加载
    bot = test_config_loading()
    if not bot:
        logger.error("配置加载失败，测试终止")
        return

    # 2. 测试Cookie管理
    test_cookie_manager(bot)

    # 3. 测试历史记录加载
    test_history_loading(bot)

    # 4. 测试频率限制配置
    test_rate_limit(bot)

    # 5. 测试视频列表获取
    videos = test_video_list(bot)

    # 6. 测试评论获取
    comments = test_comment_fetching(bot, videos)

    # 7. 测试缓存机制
    test_cache_mechanism(bot)

    # 8. 测试回复生成
    if comments:
        test_reply_generation(bot, comments)

    # 9. 模拟回复测试
    if comments and bot.config['reply'].get('enabled', False):
        logger.info("\n是否进行模拟回复测试？（不实际发送到B站）")
        logger.info("注意: 这将调用DeepSeek API，可能产生API费用")
        choice = input("输入 'y' 继续测试，其他键跳过: ").strip().lower()
        if choice == 'y':
            dry_run_reply_test(bot, comments)

    # 测试总结
    print_section("测试总结")
    logger.info("✓ 基础功能测试完成")
    logger.info("提示: 如果所有测试通过，可以运行 python main.py 启动机器人")
    logger.info("注意: 建议先在测试模式或少量评论上运行，确认功能正常后再长期运行")

    print("\n测试结束\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n测试被用户中断")
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}", exc_info=True)
        sys.exit(1)
