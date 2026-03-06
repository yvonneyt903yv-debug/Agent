#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS 监控公共模块 - 可复用的核心功能

包含：
- 状态管理
- 日期处理
- Jina Reader 内容提取
- Selenium 备用方案
- 图片下载
- 文章处理流程（翻译 + 审核 + 发布）
- 输出到automated articles文件夹
"""

import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urlparse
from datetime import datetime, timedelta

# 代理与重试配置（自动判断 Linux/Mac）
from server_utils import PROXIES, requests_get_with_retry

# 导入翻译和审核模块（从 Agent/src 目录）
AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Agent/
sys.path.insert(0, os.path.join(AGENT_DIR, 'src'))
from singju_ds import setup_driver, translate_text_with_deepseek_api, save_to_markdown_file, convert_to_markdown_and_copy
from review_markdown_ds import review_markdown_content

try:
    from publish_to_wechat import publish_to_wechat
    WECHAT_PUBLISH_AVAILABLE = True  # 设为 False 则禁用微信发布
except ImportError:
    WECHAT_PUBLISH_AVAILABLE = False

try:
    from gemini_reviewer import review_markdown_for_wechat
    GEMINI_REVIEW_AVAILABLE = True
except ImportError:
    GEMINI_REVIEW_AVAILABLE = False

# 邮件通知（可选）
try:
    from email_notifier import send_publish_notification
    EMAIL_NOTIFY_AVAILABLE = True
except ImportError:
    EMAIL_NOTIFY_AVAILABLE = False


# ===== 状态管理 =====

def load_state(state_file):
    """加载处理状态"""
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            return json.load(f)
    return {"processed_links": []}


def save_state(state, state_file):
    """保存处理状态"""
    with open(state_file, 'w') as f:
        json.dump(state, f)


def load_processed(processed_file):
    """加载已处理文章记录"""
    if os.path.exists(processed_file):
        with open(processed_file, 'r') as f:
            return json.load(f)
    return {}


def save_processed(processed, processed_file):
    """保存已处理文章记录"""
    with open(processed_file, 'w') as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)


# ===== 日期处理 =====

def parse_date(date_str):
    """解析多种日期格式，返回 date 对象"""
    if not date_str:
        return None

    date_str = date_str.strip()

    formats = [
        "%B %d, %Y",      # January 16, 2026
        "%b %d, %Y",      # Jan 16, 2026
        "%B %d %Y",       # January 16 2026
        "%b %d %Y",       # Jan 16 2026
        "%Y-%m-%d",       # 2026-01-16
        "%d %B %Y",       # 16 January 2026
        "%d %b %Y",       # 16 Jan 2026
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    return None


def is_recent_article(date_str):
    """判断文章日期是否为今天或昨天"""
    article_date = parse_date(date_str)
    if not article_date:
        return False

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    return article_date in {today, yesterday}


def get_target_dates():
    """获取目标日期（过去7天）"""
    today = datetime.now().date()
    return {today - timedelta(days=i) for i in range(7)}


# ===== 内容提取 =====

def clean_content(content, logger=None):
    """清理内容中的 Cookie 政策、隐私政策等无关信息"""
    import re

    # 定义需要移除的内容模式
    # 注意：使用 re.MULTILINE 而非 re.DOTALL，避免 . 跨行匹配导致误删正文
    # 对于需要跨行匹配的"标题到下一个标题"模式，用 [\s\S]*? 并严格限定边界
    section_keywords = [
        'Cookie', '偏好Cookie',
        'Privacy Policy', '隐私政策', 'Datenschutz',
        'Consent', '同意', 'Einwilligung',
        'Legal Notice', '法律声明', 'Imprint', 'Impressum',
        'Terms of Use', '使用条款', 'Nutzungsbedingungen',
        'Share', '分享', 'Teilen',
    ]

    original_len = len(content)

    # 按 Markdown 标题分段，只删除标题匹配关键词的整个段落
    # 段落 = 从 # 标题行到下一个 # 标题行（或文末）
    for keyword in section_keywords:
        pattern = r'^#{1,3}\s*[^\n]*' + re.escape(keyword) + r'[^\n]*\n(?:(?!^#{1,3}\s)[\s\S])*'
        content = re.sub(pattern, '', content, flags=re.IGNORECASE | re.MULTILINE)

    # 单行模式清理：Cookie 表格行、导航链接块
    simple_patterns = [
        r'Cookie\s*(?:名称|Name)[^\n]*\n(?:[^\n]*\n){0,5}\n',
        r'##?\s*(?:Cookie\s*名称|Cookie\s*Name|服务提供商|Purpose|目的|有效期|Provider)[^\n]*\n(?:[^\n]*\n){0,10}\n',
        # 连续3个以上的 Markdown 链接（导航/页脚链接）
        r'(?:\[.*?\]\(.*?\)\s*){3,}',
    ]
    for pattern in simple_patterns:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE)

    # 清理 Cookie 表格（Markdown 表格形式）
    # 匹配包含 Cookie 关键词的表格
    lines = content.split('\n')
    cleaned_lines = []
    skip_table = False

    for line in lines:
        # 检测表格开始（包含 | 的行）
        if '|' in line and not skip_table:
            # 检查是否是 Cookie 相关表格
            if any(keyword in line.lower() for keyword in ['cookie', 'provider', 'purpose', '有效期', '服务提供商']):
                skip_table = True
                continue

        if skip_table:
            # 表格结束条件：空行或不含 | 的行
            if not line.strip() or '|' not in line:
                skip_table = False
            continue

        cleaned_lines.append(line)

    content = '\n'.join(cleaned_lines)

    # 移除连续的空白行
    content = re.sub(r'\n{3,}', '\n\n', content)

    cleaned_len = len(content)
    if logger and original_len != cleaned_len:
        logger.info(f"Content cleaned: removed {original_len - cleaned_len} chars of metadata")

    return content.strip()


def get_article_content_jina(url, logger):
    """用 Jina Reader 获取文章内容（更智能的内容提取）"""
    try:
        logger.info(f"Fetching with Jina Reader: {url[:80]}...")

        jina_url = f"https://r.jina.ai/{url}"

        headers = {
            'Accept': 'text/markdown',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        response = requests_get_with_retry(jina_url, headers=headers, timeout=60)
        response.raise_for_status()

        content = response.text.strip()

        # 从 Markdown 内容中提取标题（第一个 # 开头的行）
        title = ""
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('# '):
                title = line[2:].strip()
                break

        if not title:
            # 备用：从 URL 提取标题
            title = url.split('/')[-1].replace('-', ' ').replace('.html', '')

        # 清理内容中的 Cookie/隐私政策等无关信息
        content = clean_content(content, logger=logger)

        content_len = len(content)

        # Jina 对部分动态页面会返回大量 Cookie/导航文本，清洗后只剩很短内容
        # 这种情况下回退 Selenium，避免把“空正文”送去翻译/发布
        if content_len < 1200:
            logger.warning(
                f"Jina content too short after cleaning ({content_len} chars), "
                "falling back to Selenium for fuller content"
            )
            selenium_article = get_article_content_selenium(url, logger)
            if selenium_article and selenium_article.get("content"):
                selenium_content = clean_content(selenium_article["content"], logger=logger)
                if len(selenium_content) > content_len:
                    logger.info(
                        f"Selenium fallback used: {len(selenium_content)} chars "
                        f"(vs Jina {content_len})"
                    )
                    return {
                        "title": selenium_article.get("title") or title,
                        "content": selenium_content
                    }

        logger.info(f"Jina Reader success: {content_len} chars, title: {title[:50]}")
        return {"title": title, "content": content}

    except Exception as e:
        logger.error(f"Jina Reader failed: {e}")
        logger.info("Falling back to Selenium...")
        return get_article_content_selenium(url, logger)


def get_article_content_selenium(url, logger, title_selectors=None):
    """用 Selenium 获取文章内容（备用方案）"""
    if title_selectors is None:
        title_selectors = ["h1", ".title", ".news-title"]

    driver = setup_driver()
    if not driver:
        return None

    try:
        logger.info(f"Fetching with Selenium: {url[:80]}...")
        driver.get(url)
        time.sleep(5)

        from selenium.webdriver.common.by import By

        body = driver.find_element(By.TAG_NAME, "body")
        content = body.text.strip()

        title = ""
        for tag in title_selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, tag)
                for elem in elems:
                    t = elem.text.strip()
                    if t and len(t) > 10:
                        title = t
                        break
                if title:
                    break
            except:
                continue

        # 尝试从 meta 标签获取标题
        if not title:
            try:
                meta_title = driver.find_element(By.CSS_SELECTOR, "meta[property='og:title']")
                if meta_title:
                    title = meta_title.get_attribute("content").strip()
            except:
                pass

        return {"title": title, "content": content}
    except Exception as e:
        logger.error(f"Error fetching article: {e}")
        return None
    finally:
        if driver:
            driver.quit()


# ===== 图片处理 =====

def download_images_from_markdown(markdown_content, article_id, images_dir, logger):
    """
    从 Markdown 内容中提取图片链接并下载到本地
    返回替换了本地路径的 Markdown 内容
    """
    # 创建图片目录
    full_images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), images_dir, article_id)
    os.makedirs(full_images_dir, exist_ok=True)

    # 匹配 Markdown 图片语法: ![alt](url)
    img_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'

    def download_and_replace(match):
        alt_text = match.group(1)
        img_url = match.group(2)

        # 跳过已经是本地路径的图片
        if img_url.startswith('/') or img_url.startswith('./') or img_url.startswith('file://'):
            return match.group(0)

        # 跳过 data URI
        if img_url.startswith('data:'):
            return match.group(0)

        # 只处理真正的远程图片 URL，避免嵌套/损坏 Markdown 被当成 URL
        if not (img_url.startswith('http://') or img_url.startswith('https://')):
            return match.group(0)

        try:
            # 从 URL 提取文件名
            parsed = urlparse(img_url)
            filename = os.path.basename(parsed.path)
            if not filename or '.' not in filename:
                # 生成文件名
                ext = '.jpg'
                if 'png' in img_url.lower():
                    ext = '.png'
                elif 'gif' in img_url.lower():
                    ext = '.gif'
                elif 'webp' in img_url.lower():
                    ext = '.webp'
                filename = hashlib.md5(img_url.encode()).hexdigest()[:12] + ext

            local_path = os.path.join(full_images_dir, filename)

            # 下载图片
            logger.info(f"Downloading image: {img_url[:60]}...")
            response = requests_get_with_retry(img_url, timeout=30, stream=True)
            response.raise_for_status()

            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Image saved: {filename}")

            # 返回本地路径的 Markdown
            return f'![{alt_text}]({local_path})'

        except Exception as e:
            logger.warning(f"Failed to download image {img_url[:50]}: {e}")
            # 下载失败，保留原始链接
            return match.group(0)

    # 替换所有图片链接
    new_content = re.sub(img_pattern, download_and_replace, markdown_content)

    return new_content


# ===== 文章处理 =====

def process_single_article(content, title, images_dir, logger, article_id=None):
    """翻译并审校单篇文章，然后发布到微信"""
    try:
        # 生成文章 ID（用于图片目录）
        if not article_id:
            article_id = hashlib.md5(title.encode()).hexdigest()[:8]

        # 下载图片到本地
        logger.info(f"Downloading images: {title[:50]}...")
        content_with_local_images = download_images_from_markdown(content, article_id, images_dir, logger)

        logger.info(f"Translating: {title[:50]}...")

        translated = translate_text_with_deepseek_api(content_with_local_images)
        if not translated:
            logger.error(f"Translation failed for: {title}")
            return None

        logger.info(f"Reviewing (DeepSeek): {title[:50]}...")
        reviewed = review_markdown_content(translated)
        if not reviewed:
            logger.error(f"Review failed for: {title}")
            reviewed = translated

        # Gemini 发布前审核（格式优化、去除无关内容）
        if GEMINI_REVIEW_AVAILABLE:
            logger.info(f"Gemini pre-publish review: {title[:50]}...")
            try:
                reviewed = review_markdown_for_wechat(reviewed)
                logger.info(f"Gemini review completed: {title[:50]}")
            except Exception as e:
                logger.warning(f"Gemini review failed, using DeepSeek result: {e}")

        safe_title = title[:50].strip()

        logger.info(f"Saving: {safe_title}...")
        saved_path = save_to_markdown_file(reviewed, safe_title)
        convert_to_markdown_and_copy(reviewed)

        # 发布到微信公众号（skip_review=True 因为已经做过 Gemini 审核）
        wechat_published = False
        if WECHAT_PUBLISH_AVAILABLE and saved_path:
            try:
                logger.info(f"Publishing to WeChat: {safe_title}...")
                logger.info("请准备好微信扫码登录（如果未登录）")
                
                # 使用更长的超时时间给扫码登录
                import threading
                import time
                
                publish_result = None
                publish_error = None
                
                def do_publish():
                    nonlocal publish_result, publish_error
                    try:
                        publish_result = publish_to_wechat(saved_path, theme="grace", skip_review=True)
                    except Exception as e:
                        publish_error = e
                
                # 在后台线程中运行发布
                publish_thread = threading.Thread(target=do_publish)
                publish_thread.start()
                
                # 等待最多8分钟（给扫码登录足够时间）
                publish_thread.join(timeout=480)
                
                if publish_thread.is_alive():
                    logger.warning(f"WeChat publish timeout (8 min): {safe_title}")
                    logger.info("文章已保存为草稿，请手动完成发布")
                    wechat_published = False
                elif publish_error:
                    raise publish_error
                elif publish_result:
                    logger.info(f"WeChat publish success: {safe_title}")
                    wechat_published = True
                else:
                    logger.warning(f"WeChat publish returned false: {safe_title}")
                    logger.info("文章已保存，请检查微信编辑器")
                    
            except Exception as e:
                logger.error(f"WeChat publish error: {e}")
                logger.info("文章已翻译保存，但发布失败，请手动发布")
                import traceback
                logger.debug(traceback.format_exc())

        # 发送邮件通知
        if EMAIL_NOTIFY_AVAILABLE:
            try:
                send_publish_notification(
                    article_title=safe_title,
                    source="RSS Monitor",
                    saved_path=saved_path,
                    wechat_published=wechat_published
                )
            except Exception as e:
                logger.warning(f"邮件通知失败: {e}")

        # 返回结果，包含发布状态
        return {"content": reviewed, "wechat_published": wechat_published, "saved_path": saved_path}
    except Exception as e:
        logger.error(f"Error processing article: {e}")
        import traceback
        traceback.print_exc()
        return None


# ===== 主处理流程 =====

def process_articles_generic(get_article_links_func, state_file, processed_file, images_dir, logger):
    """
    通用的文章处理流程

    参数:
        get_article_links_func: 获取文章链接的函数
        state_file: 状态文件路径
        processed_file: 已处理记录文件路径
        images_dir: 图片保存目录
        logger: 日志记录器
    """
    logger.info("Checking for new articles...")

    state = load_state(state_file)
    processed = load_processed(processed_file)
    processed_links = set(state.get("processed_links", []))

    article_links = get_article_links_func()

    new_count = 0
    for item in article_links:
        link = item["link"]
        link_hash = item["link_hash"]

        if link_hash in processed_links:
            continue

        new_count += 1
        logger.info(f"New article: {link[:80]} ({item.get('date', '')})")

        article = get_article_content_jina(link, logger)

        if article and article.get("content"):
            content_len = len(article["content"])
            logger.info(f"Got content ({content_len} chars)")

            result = process_single_article(article["content"], article["title"], images_dir, logger)

            if result:
                processed_links.add(link_hash)
                state["processed_links"] = list(processed_links)
                save_state(state, state_file)

                processed[link_hash] = {
                    "title": article["title"],
                    "url": link,
                    "content_length": content_len,
                    "translated_length": len(result),
                    "processed_at": datetime.now().isoformat()
                }
                save_processed(processed, processed_file)
                logger.info(f"Completed: {article['title'][:50]}")
        else:
            logger.warning(f"Failed to get content for: {link}")

    if new_count == 0:
        logger.info("No new articles found (only today/yesterday articles are processed)")
    else:
        logger.info(f"Processed {new_count} new article(s)")

    logger.info("Processing complete")
