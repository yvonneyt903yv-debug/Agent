"""
crawler.py —— 三层冗余版（无 Selenium/Chromium）

文章列表抓取优先级：
  层1: RSS Feed（最轻量，优先）
  层2: requests + BeautifulSoup 爬列表页（RSS 挂了兜底）

文章正文抓取优先级：
  层1: Jina Reader API（干净 Markdown）
  层2: requests + BeautifulSoup 直接解析（Jina 失败兜底）

彻底去掉 Selenium / Chromium，从根源消除 VPS 崩溃问题。
"""

import time
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import dateutil.parser

URL_SITE_1 = "https://singjupost.com"
RSS_FEED_URL = "https://singjupost.com/feed/"
JINA_READER_BASE = "https://r.jina.ai/"
RECENT_WINDOW_HOURS = 24
JINA_TIMEOUT_SECONDS = 60
LIST_TIMEOUT_SECONDS = 30

print("✅ crawler: RSS + Jina Reader + BS4 三层冗余 (Selenium-free)")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# 时间窗口计算
# ---------------------------------------------------------------------------
def _get_cutoff_utc() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=RECENT_WINDOW_HOURS)


# ---------------------------------------------------------------------------
# 层1：RSS Feed 抓取文章 URL
# ---------------------------------------------------------------------------
def _fetch_urls_from_rss() -> list[str]:
    """
    通过 RSS Feed 获取近 RECENT_WINDOW_HOURS 内的文章 URL。
    成功返回 URL 列表；失败或结果为空返回 []。
    """
    cutoff_utc = _get_cutoff_utc()
    print(f"  📡 尝试 RSS: {RSS_FEED_URL}")

    try:
        import socket
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(LIST_TIMEOUT_SECONDS)

        feed = feedparser.parse(
            RSS_FEED_URL,
            agent=HEADERS["User-Agent"],
            request_headers={"Accept": "application/rss+xml, application/xml, text/xml"}
        )

        socket.setdefaulttimeout(old_timeout)

        if feed.bozo and not feed.entries:
            print(f"  ⚠️ RSS 解析失败: {feed.bozo_exception}")
            return []

        urls = []
        for entry in feed.entries:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pass

            if published and published < cutoff_utc:
                continue

            link = entry.get("link", "").strip()
            if link:
                urls.append(link)

        print(f"  ✅ RSS 成功: 找到 {len(urls)} 篇")
        return urls

    except Exception as e:
        print(f"  ⚠️ RSS 异常: {e}")
        return []


# ---------------------------------------------------------------------------
# 层2：requests + BS4 爬列表页（RSS 失败时的备用）
# ---------------------------------------------------------------------------
def _fetch_urls_from_html(max_pages: int = 3) -> list[str]:
    """
    直接爬首页 HTML，用 BS4 解析文章列表。
    """
    cutoff_utc = _get_cutoff_utc()
    print(f"  🔄 降级到 BS4 爬列表页...")

    article_urls: list[str] = []
    stop_paginating = False

    for page in range(1, max_pages + 1):
        page_url = URL_SITE_1 if page == 1 else f"{URL_SITE_1}/page/{page}/"
        print(f"    📄 列表页 {page}: {page_url}")

        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=LIST_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"    ❌ 列表页请求失败: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        articles = soup.select("article.post")
        if not articles:
            print(f"    ⚠️ 第 {page} 页未找到 article.post，停止翻页")
            break

        for article in articles:
            parsed_dt = None
            time_el = article.select_one("time.entry-date")
            if time_el:
                dt_str = time_el.get("datetime") or time_el.get_text(strip=True)
                if dt_str:
                    try:
                        parsed_dt = dateutil.parser.parse(dt_str)
                    except Exception:
                        pass

            if parsed_dt:
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                parsed_utc = parsed_dt.astimezone(timezone.utc)
                if parsed_utc < cutoff_utc:
                    stop_paginating = True
                    continue

            link_el = article.select_one("h2.entry-title a")
            if link_el and link_el.get("href"):
                article_urls.append(link_el["href"])

        if stop_paginating:
            print(f"    ⏹️ 遇到超出时间窗口的文章，停止翻页")
            break

    seen: set[str] = set()
    unique_urls = []
    for u in article_urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    print(f"  ✅ BS4 列表页: 找到 {len(unique_urls)} 篇")
    return unique_urls


# ---------------------------------------------------------------------------
# 文章列表入口：RSS → BS4 降级
# ---------------------------------------------------------------------------
def fetch_article_urls() -> list[str]:
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = _get_cutoff_utc()
    print(
        f"🕒 抓取发布时间 >= {cutoff_utc.isoformat()} "
        f"(回看 {RECENT_WINDOW_HOURS} 小时, 当前UTC {now_utc.isoformat()})"
    )

    # 层1：RSS
    urls = _fetch_urls_from_rss()
    if urls:
        print(f"🔍 RSS 共找到 {len(urls)} 篇候选文章")
        return urls

    # 层2：BS4 列表页
    urls = _fetch_urls_from_html()
    print(f"🔍 BS4 共找到 {len(urls)} 篇候选文章")
    return urls


# ---------------------------------------------------------------------------
# 正文层1：Jina Reader
# ---------------------------------------------------------------------------
def fetch_with_jina(url: str, timeout: int = JINA_TIMEOUT_SECONDS) -> str | None:
    """
    使用 Jina Reader API 获取干净的 Markdown 正文。
    """
    jina_url = f"{JINA_READER_BASE}{url}"
    headers = {
        "Accept": "text/markdown",
        "User-Agent": HEADERS["User-Agent"],
    }
    try:
        print(f"    🌐 Jina Reader: {url[:70]}...")
        resp = requests.get(jina_url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            content = resp.text.strip()
            if len(content) > 200:
                print(f"    ✅ Jina 成功: {len(content)} 字符")
                return content
            else:
                print(f"    ⚠️ Jina 内容过短: {len(content)} 字符")
                return None
        else:
            print(f"    ⚠️ Jina HTTP {resp.status_code}")
            return None
    except requests.exceptions.Timeout:
        print("    ⚠️ Jina 超时")
        return None
    except requests.exceptions.RequestException as e:
        print(f"    ⚠️ Jina 请求异常: {e}")
        return None


# ---------------------------------------------------------------------------
# 正文层2：requests + BS4 直接解析（Jina 失败时的备用）
# ---------------------------------------------------------------------------
def _fetch_article_with_requests(url: str, timeout: int = 30) -> str | None:
    """
    直接用 requests 下载页面，BS4 提取正文，转为简单 Markdown。
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        body = None
        for selector in ["article", ".entry-content", ".post-content", "main"]:
            body = soup.select_one(selector)
            if body:
                break

        if not body:
            print("    ⚠️ 未找到文章容器")
            return None

        title = "Untitled"
        for sel in ["h1.entry-title", "h1.post-title", "h1"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                title = el.get_text(strip=True)
                break

        lines = [f"# {title}", ""]
        for el in body.find_all(["h1", "h2", "h3", "p", "blockquote"]):
            text = el.get_text(strip=True)
            if not text:
                continue
            tag = el.name
            if tag == "h1":
                if text != title:
                    lines.append(f"# {text}")
            elif tag == "h2":
                lines.append(f"## {text}")
            elif tag == "h3":
                lines.append(f"### {text}")
            elif tag == "blockquote":
                lines.append(f"> {text}")
            else:
                lines.append(text)
            lines.append("")

        result = "\n".join(lines).strip()
        return result if len(result) > 200 else None

    except Exception as e:
        print(f"    ❌ BS4 直接解析失败: {e}")
        return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def fetch_latest_articles() -> list[str]:
    """
    抓取最新文章内容列表（Markdown 格式）。

    文章列表：RSS → BS4 列表页（自动降级）
    文章正文：Jina Reader → BS4 直接解析（自动降级）

    返回：Markdown 字符串列表
    """
    article_urls = fetch_article_urls()

    if not article_urls:
        print("⚠️ 没有找到符合条件的文章链接")
        return []

    articles: list[str] = []

    for url in article_urls:
        print(f"\n➡️  处理: {url}")

        # 正文层1：Jina Reader
        content = fetch_with_jina(url)

        # 正文层2：BS4 直接解析
        if not content:
            print("    🔄 Jina 失败，降级到 BS4 直接解析...")
            content = _fetch_article_with_requests(url)

        if content:
            print(f"    ✅ 获取成功 ({len(content)} 字符)")
            articles.append(content)
        else:
            print("    ❌ 两种方式均失败，跳过")

        time.sleep(1)  # 礼貌延迟

    print(f"\n📦 本轮共获取 {len(articles)} 篇文章内容")
    return articles
