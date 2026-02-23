#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GE HealthCare RSS 监控脚本

监控 GE HealthCare 新闻并自动翻译、发布到微信公众号
- 数据源：主站 RSS + 投资者页面
- 每 4 小时运行一次
- 仅处理今天和昨天的文章
"""

import hashlib
import os
import time
import logging
import xml.etree.ElementTree as ET
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler

# 导入公共模块
from rss_monitor_base import (
    load_state, save_state, load_processed, save_processed,
    get_target_dates, parse_date,
    get_article_content_jina,
    process_single_article,
    setup_driver
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "log.txt")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== GE 特有配置 =====
RSS_URL = "https://www.gehealthcare.com/about/newsroom/feed.xml"
INVESTOR_URL = "https://investor.gehealthcare.com/news-events/news-releases"
STATE_FILE = "ge_state.json"
PROCESSED_FILE = "ge_processed.json"
IMAGES_DIR = "downloaded_images/ge"


# ===== GE 特有的日期解析 =====

def parse_ge_rss_date(date_str):
    """解析 GE RSS 日期格式: 'Thu, 05 Feb 2026 14:00:03 Z'"""
    try:
        parts = date_str.split()
        if len(parts) >= 5:
            date_part = f"{parts[1]} {parts[2]} {parts[3]}"  # "05 Feb 2026"
            return datetime.strptime(date_part, "%d %b %Y").date()
    except (ValueError, IndexError):
        pass
    return None


# ===== GE 特有的数据源 =====

def get_rss_links():
    """通过 Selenium 获取 RSS feed（绕过 403 封禁）"""
    driver = None
    try:
        logger.info(f"Fetching RSS feed via Selenium: {RSS_URL}")

        driver = setup_driver()
        if not driver:
            logger.error("Failed to setup Selenium driver for RSS")
            return []

        driver.get(RSS_URL)
        time.sleep(3)

        # 获取页面源码（XML 内容）
        page_source = driver.page_source
        logger.debug(f"RSS page source length: {len(page_source)}")

        # 尝试从页面中提取 XML 内容
        # Selenium 可能会将 XML 包装在 HTML 中，需要提取原始内容
        try:
            # 尝试直接解析
            root = ET.fromstring(page_source.encode('utf-8'))
        except ET.ParseError:
            # 如果失败，尝试从 pre 标签中提取
            logger.debug("Direct XML parse failed, trying to extract from HTML")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(page_source, 'html.parser')
            # 浏览器可能将 XML 显示在 pre 标签中
            pre_tag = soup.find('pre')
            if pre_tag:
                xml_content = pre_tag.get_text()
                root = ET.fromstring(xml_content.encode('utf-8'))
            else:
                # 尝试查找 body 中的内容
                body = soup.find('body')
                if body:
                    xml_content = body.get_text()
                    root = ET.fromstring(xml_content.encode('utf-8'))
                else:
                    raise Exception("Cannot extract XML content from page")

        today = datetime.now().date()
        target_dates = {today - timedelta(days=i) for i in range(2)}
        logger.info(f"Target dates: {target_dates}")

        links = []
        seen = set()

        items = root.findall('.//item')
        logger.info(f"Found {len(items)} items in RSS feed")

        for item in items:
            pub_date_elem = item.find('pubDate')
            link_elem = item.find('link')
            title_elem = item.find('title')

            if pub_date_elem is None or link_elem is None:
                continue

            pub_date_str = pub_date_elem.text.strip()
            link = link_elem.text.strip()
            title = title_elem.text.strip() if title_elem is not None else ""

            article_date = parse_ge_rss_date(pub_date_str)
            logger.debug(f"RSS item: {title[:30]}... date={pub_date_str} -> {article_date}")

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
                        "title": title,
                        "source": "main_rss"
                    })
                    logger.info(f"[Main RSS] Found: {title[:50]}... ({article_date})")

        logger.info(f"[Main RSS] Found {len(links)} recent articles")
        return links
    except Exception as e:
        logger.error(f"Error fetching main RSS: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return []
    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass


def get_investor_links():
    """从投资者网站获取文章链接（无 RSS，抓取 HTML）"""
    driver = None
    try:
        logger.info(f"Fetching investor page: {INVESTOR_URL}")

        driver = setup_driver()
        if not driver:
            logger.error("Failed to setup Selenium driver for investor page")
            return []

        driver.get(INVESTOR_URL)
        time.sleep(8)  # 等待页面渲染

        from selenium.webdriver.common.by import By

        today = datetime.now().date()
        target_dates = {today - timedelta(days=i) for i in range(2)}
        logger.info(f"Target dates for investor page (2 days): {target_dates}")

        links = []
        seen = set()

        # 查找所有包含新闻链接的元素
        all_links = driver.find_elements(By.TAG_NAME, "a")
        logger.info(f"Found {len(all_links)} total links on investor page")

        news_link_count = 0
        for link_elem in all_links:
            try:
                href = link_elem.get_attribute("href") or ""
                text = link_elem.text.strip()

                # 只处理新闻详情页链接
                if "/news-release-details/" not in href:
                    continue

                news_link_count += 1
                logger.debug(f"News link found: {href}")

                if href in seen:
                    continue
                seen.add(href)

                # 获取日期 - 向上查找最多3层父元素
                date_str = ""
                try:
                    # 尝试从第1层到第3层父元素查找日期
                    for level in range(1, 4):
                        try:
                            parent = link_elem.find_element(By.XPATH, "./" + "/.." * level)
                            parent_text = parent.text.strip()
                            logger.debug(f"Parent level {level} text: {parent_text[:150]}...")

                            # 尝试从父元素提取日期
                            match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}', parent_text, re.IGNORECASE)
                            if match:
                                date_str = match.group(0)
                                logger.debug(f"Date found at level {level}: {date_str}")
                                break
                        except Exception as e:
                            logger.debug(f"Error at parent level {level}: {e}")
                            continue
                except Exception as e:
                    logger.debug(f"Error extracting date: {e}")

                # 使用链接中的 slug 作为备用标题
                title = text if text else href.split("/")[-1].replace("-", " ").replace("_", " ")

                if not href:
                    continue

                article_date = parse_date(date_str)
                if not article_date:
                    logger.debug(f"No date found, skipping: {href}")
                    continue

                if article_date in target_dates:
                    link_hash = hashlib.md5(href.encode()).hexdigest()
                    links.append({
                        "link": href,
                        "link_hash": link_hash,
                        "date": date_str,
                        "title": title,
                        "source": "investor"
                    })
                    logger.info(f"[Investor] Found: {title[:50]}... ({article_date})")

            except Exception as e:
                continue

        logger.info(f"[Investor] Found {len(links)} recent articles")
        return links

    except Exception as e:
        logger.error(f"Error fetching investor page: {e}")
        return []
    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass


def get_article_links():
    """合并主站 RSS 和投资者网站的文章链接"""
    logger.info("=" * 60)
    logger.info("Fetching articles from all sources...")
    logger.info("=" * 60)

    all_links = []

    main_links = get_rss_links()
    all_links.extend(main_links)

    investor_links = get_investor_links()
    all_links.extend(investor_links)

    # 去重
    seen = set()
    unique_links = []
    for link in all_links:
        if link["link"] not in seen:
            seen.add(link["link"])
            unique_links.append(link)

    logger.info(f"Total unique articles found: {len(unique_links)}")
    return unique_links


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

        if link_hash in processed_links:
            continue

        new_count += 1
        logger.info(f"New article: {link[:80]} ({item.get('date', '')})")

        # 使用 Jina Reader 获取内容
        article = get_article_content_jina(link, logger)

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

            if result:
                processed_links.add(link_hash)
                state["processed_links"] = list(processed_links)
                save_state(state, STATE_FILE)

                processed[link_hash] = {
                    "title": article["title"],
                    "url": link,
                    "source": item.get("source", "unknown"),
                    "content_length": content_len,
                    "translated_length": len(result),
                    "processed_at": datetime.now().isoformat()
                }
                save_processed(processed, PROCESSED_FILE)
                logger.info(f"Completed: {article['title'][:50]}")
        else:
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

    logger.info("GE HealthCare RSS Polling service started.")
    logger.info("- Monitoring 2 sources: Main RSS + Investor page")
    logger.info("- Only processes articles from today and yesterday")
    logger.info("- Runs every 4 hours (at least 6 times per day)")
    logger.info("- Auto-publishes to WeChat after processing")

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
