#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""macOS Mail.app 邮件通知模块"""

import subprocess
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")


def send_publish_notification(article_title, source, saved_path, wechat_published, retry_count=2):
    """发送文章处理完成的邮件通知"""
    if not NOTIFY_EMAIL:
        logger.warning("NOTIFY_EMAIL 未配置，跳过邮件通知")
        return False

    status = "发布成功" if wechat_published else "发布失败"
    status_emoji = "✅" if wechat_published else "❌"
    subject = f"[Agent] {status_emoji} {article_title[:30]}..."

    body = f"""文章处理完成通知

标题: {article_title}
来源: {source}
状态: {status}
路径: {saved_path or '未保存'}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
此邮件由 Agent 自动发送"""

    # 转义特殊字符
    subject_escaped = subject.replace('"', '\\"').replace('\n', ' ')
    body_escaped = body.replace('"', '\\"').replace('\n', '\\n')

    script = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{subject:"{subject_escaped}", content:"{body_escaped}", visible:false}}
        tell newMessage
            make new to recipient at end of to recipients with properties {{address:"{NOTIFY_EMAIL}"}}
        end tell
        send newMessage
    end tell
    '''

    for attempt in range(retry_count):
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=30)
            logger.info(f"邮件通知已发送: {article_title[:30]}...")
            return True
        except subprocess.TimeoutExpired:
            logger.warning(f"邮件发送超时 (尝试 {attempt + 1}/{retry_count})")
        except subprocess.CalledProcessError as e:
            logger.warning(f"邮件发送失败 (尝试 {attempt + 1}/{retry_count}): {e.stderr}")

    logger.error("邮件发送失败")
    return False
