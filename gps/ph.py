#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Philips RSS 监控脚本

监控 Philips 新闻并自动翻译、发布到微信公众号
- 数据源：Philips RSS feed
- 每 4 小时运行一次
- 仅处理今天和昨天的文章
"""

import hashlib
import time
import logging
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# 导入公共模块
from rss_monitor_base import (
    PROXIES,
    load_state, save_state, load_processed, save_processed,
    get_target_dates,
    clean_content,
    get_article_content_jina,
    process_single_article
)
from server_utils import requests_get_with_retry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== Philips 特有配置 =====
LIST_URL = "https://www.philips.com/a-w/about/news-and-insights/all.html"
RSS_URL = "https://www.philips.com/content/corporate/en_AA/feed.rss.xml?pageSize=15&startIndex=0&src=/content/corporate/en_AA/about/news/archive&sortMode=createdDate"
STATE_FILE = "ph_state.json"
PROCESSED_FILE = "ph_processed.json"
IMAGES_DIR = "downloaded_images/ph"


# ===== Philips 特有的日期解析 =====

def parse_philips_rss_date(pub_date_str):
    """解析 Philips RSS 日期格式: 'Feb 10, 2026 08:10:38 +0100'"""
    try:
        # 去掉时区部分，只保留日期
        date_part = pub_date_str.split()[0:3]  # ['Feb', '10,', '2026']
        date_str = ' '.join(date_part).replace(',', '')  # 'Feb 10 2026'
        return datetime.strptime(date_str, "%b %d %Y").date()
    except (ValueError, IndexError) as e:
        logger.warning(f"Failed to parse date '{pub_date_str}': {e}")
        return None


# ===== Philips 特有的正文质量检查与回退提取 =====

LOW_QUALITY_MARKERS = [
    "you are leaving the philips global content page",
    "you are about to visit a philips global content page",
    "by clicking on the link, you will be leaving",
    "our site can best be viewed with the latest version",
    "our site is best viewed using the latest version",
    "i understand",
    "continue",
    "cookie",
    "privacy policy",
    "microsoft edge, google chrome or firefox",
    "通过点击此链接，您将离开皇家飞利浦",
    "您即将访问飞利浦的全球内容页面",
]


def is_low_quality_content(content):
    """判断提取结果是否为壳内容（导航/声明/Cookie）"""
    if not content:
        return True

    normalized = re.sub(r'\s+', ' ', content).strip().lower()
    marker_hits = sum(1 for marker in LOW_QUALITY_MARKERS if marker in normalized)

    # Markdown 导航链接占比过高通常不是正文
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    link_lines = [line for line in lines if line.startswith('*   [') or line.startswith('- [')]
    link_ratio = (len(link_lines) / len(lines)) if lines else 0

    # 过短正文通常是壳层页面或抽取失败
    if len(content) < 450:
        return True

    # 标题 + 声明 + 浏览器提示，基本可判定为无效正文
    too_short_with_noise = len(content) < 900 and marker_hits >= 2

    return too_short_with_noise or marker_hits >= 4 or link_ratio >= 0.35


def _extract_main_text_from_html(html):
    """
    从 Philips 页面 HTML 中提取正文文本。
    若 bs4 不可用则返回空字符串，保持兼容。
    """
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # 去掉明显噪声节点
    for tag in soup.select("script, style, nav, footer, header, form, button, noscript, svg"):
        tag.decompose()

    selectors = [
        "article",
        "main article",
        "main",
        "[itemprop='articleBody']",
        ".article-content",
        ".news-article-content",
        ".cmp-text",
        ".richtext",
    ]

    best_text = ""
    for selector in selectors:
        for elem in soup.select(selector):
            text = elem.get_text("\n", strip=True)
            if len(text) > len(best_text):
                best_text = text

    # 兜底：从段落拼接
    if len(best_text) < 400:
        paragraphs = [p.get_text(" ", strip=True) for p in soup.select("p")]
        paragraphs = [p for p in paragraphs if len(p) >= 40]
        best_text = "\n".join(paragraphs[:60])

    return best_text.strip()


def get_article_content_philips(url, rss_title=""):
    """
    Philips 专用内容提取：
    1) 先走 Jina（通用路径）
    2) 若命中壳内容，再尝试直连页面提取正文
    """
    article = get_article_content_jina(url, logger)
    if article and article.get("content"):
        jina_content = article["content"]
        jina_len = len(jina_content)
        low_quality = is_low_quality_content(jina_content)

        if not low_quality:
            return article

        # Philips 页面常把正文与导航混在一起返回；长文本通常仍包含可用主体内容
        if jina_len >= 8000:
            logger.warning(
                f"Jina flagged low-quality but content is long ({jina_len} chars), "
                "using Jina result to avoid false negative"
            )
            return article

    logger.warning("Jina result appears low-quality for Philips page, trying direct extraction...")

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }
        response = requests_get_with_retry(url, headers=headers, timeout=45)

        # 防止 requests 错误猜测编码导致乱码
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"

        raw_text = _extract_main_text_from_html(response.text)
        if not raw_text:
            return article

        title = rss_title.strip()
        if not title:
            title = url.split("/")[-1].replace("-", " ").replace(".html", "")

        merged = f"# {title}\n\n{raw_text}"
        cleaned = clean_content(merged, logger=logger)

        if is_low_quality_content(cleaned):
            logger.warning("Direct extraction is still low-quality; skip this article to avoid bad content.")
            return None

        logger.info(f"Direct extraction success: {len(cleaned)} chars")
        return {"title": title, "content": cleaned}
    except Exception as e:
        logger.error(f"Direct Philips extraction failed: {e}")
        return article


# ===== Philips 特有的数据源 =====

def get_article_links():
    """通过 RSS feed 获取今天/昨天发布的文章链接"""
    try:
        logger.info(f"Fetching RSS feed: {RSS_URL}")

        response = requests.get(RSS_URL, proxies=PROXIES, timeout=30)
        response.raise_for_status()

        # 解析 RSS XML
        root = ET.fromstring(response.content)

        target_dates = get_target_dates()
        logger.info(f"Target dates: {sorted(target_dates)}")

        links = []
        seen = set()

        # 遍历所有 item
        for item in root.findall('.//item'):
            pub_date_elem = item.find('pubDate')
            link_elem = item.find('link')
            title_elem = item.find('title')

            if pub_date_elem is None or link_elem is None:
                continue

            pub_date_str = pub_date_elem.text.strip()
            link = link_elem.text.strip()
            title = title_elem.text.strip() if title_elem is not None else ""

            article_date = parse_philips_rss_date(pub_date_str)
            if not article_date:
                continue

            if article_date in target_dates:
                if link not in seen:
                    seen.add(link)
                    link_hash = hashlib.md5(link.encode()).hexdigest()
                    links.append({
                        "link": link,
                        "link_hash": link_hash,
                        "date": pub_date_str,
                        "title": title
                    })
                    logger.info(f"Found article: {title[:50]}... ({article_date})")

        logger.info(f"Found {len(links)} recent article links (today or yesterday)")
        return links
    except Exception as e:
        logger.error(f"Error fetching RSS: {e}")
        return []


# ===== 主处理流程 =====

def process_articles():
    """主流程：检测 → 获取内容 → 翻译 → 审核 → 发布"""
    logger.info("Checking for new articles...")

    state = load_state(STATE_FILE)
    processed = load_processed(PROCESSED_FILE)
    processed_links = set(state.get("processed_links", []))

    article_links = get_article_links()

    new_count = 0
    for item in article_links:
        link = item["link"]
        link_hash = item["link_hash"]

        # 检查是否已处理（同时检查 state 和 processed 文件）
        if link_hash in processed_links or link_hash in processed:
            logger.debug(f"Skipping already processed: {link[:50]}...")
            continue

        new_count += 1
        logger.info(f"New article: {link[:80]} ({item.get('date', '')})")

        # 使用 Jina Reader 获取内容
        article = get_article_content_philips(link, rss_title=item.get("title", ""))

        if article and article.get("content"):
            content_len = len(article["content"])
            logger.info(f"Got content ({content_len} chars)")

            # 使用公共模块处理文章
            result = process_single_article(
                article["content"],
                article["title"],
                IMAGES_DIR,
                logger
            )

            # 无论成功与否，都标记为已处理，避免重复尝试
            processed_links.add(link_hash)
            state["processed_links"] = list(processed_links)
            save_state(state, STATE_FILE)

            if result:
                # 处理新的返回格式（dict 或 str 兼容）
                if isinstance(result, dict):
                    content = result.get("content", "")
                    wechat_published = result.get("wechat_published", False)
                    saved_path = result.get("saved_path", "")
                else:
                    content = result
                    wechat_published = False
                    saved_path = ""

                status = "success" if wechat_published else "translated_only"
                processed[link_hash] = {
                    "title": article["title"],
                    "url": link,
                    "content_length": content_len,
                    "translated_length": len(content) if content else 0,
                    "content_preview": (content[:1000] if content else ""),
                    "content_preview_length": min(len(content), 1000) if content else 0,
                    "processed_at": datetime.now().isoformat(),
                    "status": status,
                    "wechat_published": wechat_published,
                    "saved_path": saved_path
                }
                save_processed(processed, PROCESSED_FILE)
                logger.info(f"Completed: {article['title'][:50]} (WeChat: {'✓' if wechat_published else '✗'})")
            else:
                # 记录失败的文章，但不重试
                processed[link_hash] = {
                    "title": article.get("title", "Unknown"),
                    "url": link,
                    "content_length": content_len,
                    "processed_at": datetime.now().isoformat(),
                    "status": "failed"
                }
                save_processed(processed, PROCESSED_FILE)
                logger.warning(f"Processing failed for: {article['title'][:50]}")
        else:
            # 获取内容失败，也标记为已处理
            processed_links.add(link_hash)
            state["processed_links"] = list(processed_links)
            save_state(state, STATE_FILE)
            processed[link_hash] = {
                "title": item.get("title", "Unknown"),
                "url": link,
                "processed_at": datetime.now().isoformat(),
                "status": "fetch_failed"
            }
            save_processed(processed, PROCESSED_FILE)
            logger.warning(f"Failed to get content for: {link}")

    if new_count == 0:
        logger.info("No new articles found (only today/yesterday articles are processed)")
    else:
        logger.info(f"Processed {new_count} new article(s)")

    logger.info("Processing complete")


def main():
    scheduler = BackgroundScheduler()
    # 每4小时运行一次，misfire_grace_time=None 表示错过后总会执行，coalesce=True 合并多次错过的执行
    scheduler.add_job(
        process_articles,
        'interval',
        hours=4,
        id='polling_job',
        misfire_grace_time=None,  # Always run missed jobs when system wakes from sleep
        coalesce=True,
        max_instances=1  # 同一时间只允许1个实例运行，防止任务重叠
    )
    scheduler.start()

    logger.info("Philips RSS Polling service started.")
    logger.info("- Only processes articles from today and yesterday")
    logger.info("- Runs every 4 hours (at least 6 times per day)")
    logger.info("- Auto-publishes to WeChat after processing")
    logger.info("- Missed jobs will run when system wakes (grace time: 5 min)")

    # 启动时立即执行一次
    logger.info("Running initial check...")
    process_articles()

    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    main()
