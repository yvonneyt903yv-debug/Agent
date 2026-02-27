#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GE HealthCare RSS 监控脚本

监控 GE HealthCare 新闻并自动翻译、发布到微信公众号
- 数据源：主站 RSS + 投资者页面 + Newsroom 列表页
- 每 4 小时运行一次
- 默认处理最近 7 天（可配置）
- 增加每日回补任务，降低时区/延迟导致的漏抓
"""

import hashlib
import os
import time
import logging
import xml.etree.ElementTree as ET
import requests
import re
import fcntl
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler

# 导入公共模块
from rss_monitor_base import (
    load_state, save_state, load_processed, save_processed,
    parse_date,
    get_article_content_jina,
    process_single_article,
    setup_driver
)

try:
    from email_notifier import send_publish_notification
    EMAIL_NOTIFY_AVAILABLE = True
except ImportError:
    EMAIL_NOTIFY_AVAILABLE = False

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
NEWSROOM_URL = "https://www.gehealthcare.com/about/newsroom/press-releases"
STATE_FILE = os.path.join(SCRIPT_DIR, "ge_state.json")
PROCESSED_FILE = os.path.join(SCRIPT_DIR, "ge_processed.json")
IMAGES_DIR = "downloaded_images/ge"
LOCK_FILE = os.path.join(SCRIPT_DIR, "ge_processing.lock")
RECENT_DAYS = max(2, int(os.getenv("GE_RECENT_DAYS", "7")))
EMPTY_RUN_ALERT_THRESHOLD = max(3, int(os.getenv("GE_EMPTY_RUN_ALERT_THRESHOLD", "3")))
TRACKING_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "mc_cid", "mc_eid"
}
DATE_PATTERN = re.compile(
    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
    re.IGNORECASE
)


def normalize_link(url):
    """统一 URL，移除常见追踪参数，避免同一文章重复或误判"""
    try:
        parts = urlsplit((url or "").strip())
        if not parts.scheme or not parts.netloc:
            return (url or "").strip()
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        filtered_pairs = [(k, v) for k, v in query_pairs if k.lower() not in TRACKING_QUERY_KEYS]
        normalized_query = urlencode(filtered_pairs, doseq=True)
        normalized_path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), normalized_path, normalized_query, ""))
    except Exception:
        return (url or "").strip()


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


def get_target_dates(days):
    """生成最近 days 天的目标日期集合（含今天）"""
    today = datetime.now().date()
    return {today - timedelta(days=i) for i in range(days)}


def extract_date_from_text(text):
    """从文本中提取日期字符串并解析成 date，失败返回 None"""
    if not text:
        return None
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    return parse_date(match.group(0))


def try_acquire_lock():
    """跨进程互斥锁，防止多实例重复发布"""
    fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd.write(str(os.getpid()))
        fd.flush()
        return fd
    except BlockingIOError:
        fd.close()
        return None


def release_lock(fd):
    """释放跨进程锁"""
    if not fd:
        return
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    finally:
        fd.close()


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

        target_dates = get_target_dates(RECENT_DAYS)
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
            link = normalize_link(link_elem.text.strip())
            title = title_elem.text.strip() if title_elem is not None else ""

            article_date = parse_ge_rss_date(pub_date_str)
            logger.debug(f"RSS item: {title[:30]}... date={pub_date_str} -> {article_date}")

            # RSS 日期异常时也保留，避免漏抓
            if (not article_date) or (article_date in target_dates):
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
                    logger.info(f"[Main RSS] Found: {title[:50]}... ({article_date or 'unknown_date'})")

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

        target_dates = get_target_dates(RECENT_DAYS)
        logger.info(f"Target dates for investor page ({RECENT_DAYS} days): {target_dates}")

        links = []
        seen = set()

        # 查找所有包含新闻链接的元素
        all_links = driver.find_elements(By.TAG_NAME, "a")
        logger.info(f"Found {len(all_links)} total links on investor page")

        news_link_count = 0
        for link_elem in all_links:
            try:
                href = normalize_link(link_elem.get_attribute("href") or "")
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
                            match = DATE_PATTERN.search(parent_text)
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
                # 投资者页面日期提取偶发失败，允许无日期项进入候选，避免漏抓
                if (not article_date) or (article_date in target_dates):
                    link_hash = hashlib.md5(href.encode()).hexdigest()
                    links.append({
                        "link": href,
                        "link_hash": link_hash,
                        "date": date_str,
                        "title": title,
                        "source": "investor"
                    })
                    logger.info(f"[Investor] Found: {title[:50]}... ({article_date or 'unknown_date'})")

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


def get_newsroom_press_links():
    """从 Newsroom Press Releases 列表页抓取链接（兜底 RSS 漏发）"""
    driver = None
    try:
        logger.info(f"Fetching newsroom page: {NEWSROOM_URL}")
        driver = setup_driver()
        if not driver:
            logger.error("Failed to setup Selenium driver for newsroom page")
            return []

        driver.get(NEWSROOM_URL)
        time.sleep(8)

        from selenium.webdriver.common.by import By

        target_dates = get_target_dates(RECENT_DAYS)
        logger.info(f"Target dates for newsroom page ({RECENT_DAYS} days): {target_dates}")

        links = []
        seen = set()
        all_links = driver.find_elements(By.TAG_NAME, "a")
        logger.info(f"Found {len(all_links)} total links on newsroom page")

        for link_elem in all_links:
            try:
                href = normalize_link(link_elem.get_attribute("href") or "")
                if "/about/newsroom/press-releases/" not in href:
                    continue
                if href in seen:
                    continue

                text = (link_elem.text or "").strip()
                article_date = None
                # 日期可能在父元素，向上尝试提取
                for level in range(1, 5):
                    try:
                        parent = link_elem.find_element(By.XPATH, "./" + "/.." * level)
                        parent_text = (parent.text or "").strip()
                        article_date = extract_date_from_text(parent_text)
                        if article_date:
                            break
                    except Exception:
                        continue

                # 无日期也纳入候选，避免列表结构变化导致漏抓
                if article_date and article_date not in target_dates:
                    continue

                seen.add(href)
                link_hash = hashlib.md5(href.encode()).hexdigest()
                links.append({
                    "link": href,
                    "link_hash": link_hash,
                    "date": article_date.isoformat() if article_date else "",
                    "title": text if text else href.split("/")[-1].replace("-", " ").replace("_", " "),
                    "source": "newsroom_page"
                })
            except Exception:
                continue

        logger.info(f"[Newsroom] Found {len(links)} candidate articles")
        return links
    except Exception as e:
        logger.error(f"Error fetching newsroom page: {e}")
        return []
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


def get_article_links():
    """合并主站 RSS、投资者网站和 Newsroom 列表页的文章链接"""
    logger.info("=" * 60)
    logger.info("Fetching articles from all sources...")
    logger.info("=" * 60)

    all_links = []

    main_links = get_rss_links()
    all_links.extend(main_links)

    investor_links = get_investor_links()
    all_links.extend(investor_links)

    newsroom_links = get_newsroom_press_links()
    all_links.extend(newsroom_links)

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

def process_articles(run_mode="regular"):
    """主流程：检测 → 获取内容 → 翻译 → 审核 → 发布"""
    lock_fd = try_acquire_lock()
    if not lock_fd:
        logger.warning("Another GE process is already running, skip this cycle to avoid duplicate publishes.")
        return

    logger.info(f"Checking for new articles... (mode={run_mode})")

    try:
        state = load_state(STATE_FILE)
        processed = load_processed(PROCESSED_FILE)
        processed_links = set(state.get("processed_links", []))

        article_links = get_article_links()
        state["last_run_at"] = datetime.now().isoformat()
        state["last_run_mode"] = run_mode
        state["last_candidate_count"] = len(article_links)

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

                    processed[link_hash] = {
                        "title": article["title"],
                        "url": link,
                        "source": item.get("source", "unknown"),
                        "content_length": content_len,
                        "translated_length": len(result.get("content", "")),
                        "processed_at": datetime.now().isoformat(),
                        "wechat_published": bool(result.get("wechat_published", False)),
                        "saved_path": result.get("saved_path", "")
                    }
                    save_processed(processed, PROCESSED_FILE)
                    logger.info(f"Completed: {article['title'][:50]}")
            else:
                logger.warning(f"Failed to get content for: {link}")

        if new_count == 0:
            empty_runs = int(state.get("consecutive_empty_runs", 0)) + 1
            state["consecutive_empty_runs"] = empty_runs
            logger.info(f"No new articles found (empty_runs={empty_runs})")
            if empty_runs >= EMPTY_RUN_ALERT_THRESHOLD:
                today_str = datetime.now().strftime("%Y-%m-%d")
                last_alert_day = state.get("last_empty_alert_day", "")
                msg = (
                    f"GE monitor empty for {empty_runs} consecutive runs. "
                    f"Please verify source freshness / network / parser."
                )
                logger.warning(msg)
                if EMAIL_NOTIFY_AVAILABLE and last_alert_day != today_str:
                    try:
                        send_publish_notification(
                            article_title=f"GE监控连续空跑告警({empty_runs}次)",
                            source="GE RSS Monitor",
                            saved_path=None,
                            wechat_published=False
                        )
                        state["last_empty_alert_day"] = today_str
                    except Exception as e:
                        logger.warning(f"Empty-run email alert failed: {e}")
        else:
            state["consecutive_empty_runs"] = 0
            logger.info(f"Processed {new_count} new article(s)")

        save_state(state, STATE_FILE)
        logger.info("Processing complete")
    finally:
        release_lock(lock_fd)


def process_articles_backfill():
    """每日回补任务：执行同一流程，但标记运行模式"""
    process_articles(run_mode="backfill")


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
    # 每天固定回补一次，兜底时区差和源端延迟
    scheduler.add_job(
        process_articles_backfill,
        'cron',
        hour=9,
        minute=10,
        id='daily_backfill_job',
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1
    )
    scheduler.start()

    logger.info("GE HealthCare RSS Polling service started.")
    logger.info("- Monitoring 3 sources: Main RSS + Investor page + Newsroom page")
    logger.info(f"- Processes recent {RECENT_DAYS} days (default=7)")
    logger.info("- Runs every 4 hours (at least 6 times per day)")
    logger.info("- Daily backfill at 09:10 local time")
    logger.info(f"- Empty run alert threshold: {EMPTY_RUN_ALERT_THRESHOLD}")
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
