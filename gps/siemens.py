#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Siemens Healthineers 新闻监控脚本

监控 Siemens Healthineers 新闻并自动翻译、发布到微信公众号
- 数据源：Press 页面（无 RSS，需 Selenium 抓取）
- 每 4 小时运行一次
- 仅处理今天和昨天的文章
"""

import hashlib
import time
import logging
import os
import re
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from apscheduler.schedulers.background import BackgroundScheduler

from rss_monitor_base import (
    load_state, save_state, load_processed, save_processed,
    parse_date,
    get_article_content_jina,
    process_single_article,
    setup_driver
)
from server_utils import requests_get_with_retry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "siemens.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== Siemens 特有配置 =====
PRESS_URL = "https://www.siemens-healthineers.com/press"
BASE_URL = "https://www.siemens-healthineers.com"
RELEASES_URL = "https://www.siemens-healthineers.com/press/releases"
STATE_FILE = "siemens_state.json"
PROCESSED_FILE = "siemens_processed.json"
IMAGES_DIR = "downloaded_images/siemens"

from urllib.parse import urljoin


def get_siemens_target_dates():
    """Siemens 仅处理今天和昨天。"""
    today = datetime.now().date()
    return {today - timedelta(days=i) for i in range(2)}


def _parse_lastmod_date(lastmod_text):
    """解析 sitemap 的 lastmod 字段为 date 对象。"""
    if not lastmod_text:
        return None
    text = lastmod_text.strip()
    if not text:
        return None

    # 常见格式: 2026-03-04T12:34:56Z / 2026-03-04
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _slug_to_title(url):
    slug = url.rstrip("/").split("/")[-1]
    slug = re.sub(r"[-_]+", " ", slug).strip()
    slug = re.sub(r"\s+", " ", slug)
    return slug or "Unknown"


def extract_release_links_from_html(page_html):
    """从页面源码中提取 /press/releases/ 链接（含脚本/隐藏块中的链接）。"""
    if not page_html:
        return []

    links = set()
    patterns = [
        r'https?://www\.siemens-healthineers\.com/press/releases/[a-zA-Z0-9\-_/]+',
        r'"/press/releases/[a-zA-Z0-9\-_/]+"',
        r"'/press/releases/[a-zA-Z0-9\-_/]+'",
    ]
    for pat in patterns:
        for m in re.findall(pat, page_html):
            url = m.strip('"').strip("'")
            if url.startswith("/"):
                url = f"https://www.siemens-healthineers.com{url}"
            # 去掉尾随标点或查询参数片段
            url = url.split("#", 1)[0]
            links.add(url.rstrip("/"))

    cleaned = []
    for u in links:
        if "/press/releases/" not in u:
            continue
        if "/press/features/" in u:
            continue
        tail = u.rsplit("/", 1)[-1]
        if not tail or tail in {"releases", "features"}:
            continue
        cleaned.append(u)
    return cleaned


def fetch_release_links_from_sitemaps(target_dates, logger):
    """
    从 sitemap 兜底抓取 /press/releases/ 链接，避免前端列表页漏展示。
    优先保留 lastmod 在目标日期内的链接。
    """
    base = "https://www.siemens-healthineers.com"
    sitemap_indexes = [
        f"{base}/sitemap.xml",
        f"{base}/sitemap-index.xml",
    ]

    release_links = []
    seen = set()
    unknown_lastmod_candidates = []

    def add_candidate(url, lastmod_text=""):
        if "/press/releases/" not in url or "/press/features/" in url:
            return
        if url in seen:
            return
        seen.add(url)

        lm_date = _parse_lastmod_date(lastmod_text)
        item = {
            "link": url,
            "link_hash": hashlib.md5(url.encode()).hexdigest(),
            "date": lastmod_text or "",
            "title": _slug_to_title(url),
            "lastmod_date": lm_date,
        }
        if lm_date in target_dates:
            release_links.append(item)
        elif lm_date is None:
            unknown_lastmod_candidates.append(item)

    sitemap_urls = []
    for idx_url in sitemap_indexes:
        try:
            resp = requests.get(idx_url, timeout=15)
            if resp.status_code >= 400:
                logger.info(f"Sitemap index not available: {idx_url} ({resp.status_code})")
                continue
            root = ET.fromstring(resp.content)
            root_name = root.tag.split("}", 1)[-1]
            if root_name == "sitemapindex":
                for node in root.findall(".//{*}sitemap"):
                    loc = (node.findtext("{*}loc") or "").strip()
                    if loc:
                        sitemap_urls.append(loc)
            elif root_name == "urlset":
                for node in root.findall(".//{*}url"):
                    loc = (node.findtext("{*}loc") or "").strip()
                    lastmod = (node.findtext("{*}lastmod") or "").strip()
                    if loc:
                        add_candidate(loc, lastmod)
        except Exception as e:
            logger.debug(f"Sitemap index fetch failed: {idx_url} ({e})")

    for sm_url in sitemap_urls:
        # 只优先扫可能相关的 sitemap，降低请求开销
        sm_lower = sm_url.lower()
        if "press" not in sm_lower and "release" not in sm_lower and "news" not in sm_lower:
            continue
        try:
            resp = requests.get(sm_url, timeout=15)
            if resp.status_code >= 400:
                continue
            root = ET.fromstring(resp.content)
            if root.tag.split("}", 1)[-1] != "urlset":
                continue
            for node in root.findall(".//{*}url"):
                loc = (node.findtext("{*}loc") or "").strip()
                lastmod = (node.findtext("{*}lastmod") or "").strip()
                if loc:
                    add_candidate(loc, lastmod)
        except Exception as e:
            logger.debug(f"Sitemap fetch failed: {sm_url} ({e})")

    # 对缺少 lastmod 的候选做小规模兜底，避免漏抓但不至于全量扫历史
    if unknown_lastmod_candidates:
        release_links.extend(unknown_lastmod_candidates[:20])

    if release_links:
        logger.info(f"Sitemap fallback found {len(release_links)} release link(s)")
    else:
        logger.info("Sitemap fallback found 0 release links")
    return release_links


def extract_article_date_from_content(content):
    """
    从正文中提取文章日期，支持常见格式：
    - March 5, 2026 / Mar 5, 2026
    - 2026-03-05
    """
    if not content:
        return None

    lines = [ln.strip() for ln in content.split('\n') if ln.strip()]
    head_lines = lines[:120]

    month_pat = (
        r"(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}"
    )
    iso_pat = r"\b\d{4}-\d{2}-\d{2}\b"

    for line in head_lines:
        cleaned = line.replace("**", " ").replace("Published:", " ").replace("Publish date:", " ")
        cleaned = " ".join(cleaned.split())

        m = re.search(month_pat, cleaned, flags=re.IGNORECASE)
        if m:
            d = parse_date(m.group(0))
            if d:
                return d

        m = re.search(iso_pat, cleaned)
        if m:
            d = parse_date(m.group(0))
            if d:
                return d

    return None


def _extract_date_from_text(raw_text):
    """从任意文本片段中提取日期。"""
    if not raw_text:
        return None

    text = " ".join(str(raw_text).split()).strip(" '\"\t\r\n,;")
    if not text:
        return None

    # 先直接尝试公共解析器
    direct = parse_date(text)
    if direct:
        return direct

    # ISO 日期/时间
    iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?)?\b", text)
    if iso_match:
        iso_raw = iso_match.group(0)
        parsed_iso = _parse_lastmod_date(iso_raw)
        if parsed_iso:
            return parsed_iso
        fallback_iso = parse_date(iso_raw[:10])
        if fallback_iso:
            return fallback_iso

    # 英文月份格式
    month_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}",
        text,
        flags=re.IGNORECASE
    )
    if month_match:
        parsed_month = parse_date(month_match.group(0))
        if parsed_month:
            return parsed_month

    return None


def extract_article_date_from_page(url, logger):
    """从页面 HTML 的 meta/time/json-ld 中提取发布日期。"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }
        resp = requests_get_with_retry(url, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.debug(f"Date extraction from page failed to fetch html: {e}")
        return None, ""

    # 先用 Last-Modified 头兜底，Siemens Press 页面通常会提供准确修改时间
    try:
        last_modified = (resp.headers.get("Last-Modified") or "").strip()
        if last_modified:
            parsed_dt = parsedate_to_datetime(last_modified)
            if parsed_dt:
                return parsed_dt.date(), "header:last-modified"
    except Exception:
        pass

    patterns = [
        ("meta:article:published_time", r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']'),
        ("meta:publish-date", r'<meta[^>]+(?:name|property)=["\'](?:publish-date|pubdate|datePublished|date)["\'][^>]+content=["\']([^"\']+)["\']'),
        ("jsonld:datePublished", r'"datePublished"\s*:\s*"([^"]+)"'),
        ("time:datetime", r'<time[^>]+datetime=["\']([^"\']+)["\']'),
        ("html:text", r'(?:Published|Publication date|Date)\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})'),
    ]

    for source, pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip()
        parsed = _extract_date_from_text(candidate)
        if parsed:
            return parsed, source

    return None, ""

def extract_images_with_selenium(url, logger):
    """
    使用 Selenium 提取页面中的图片 URL
    返回图片 URL 列表
    """
    driver = None
    image_urls = []

    try:
        driver = setup_driver()
        if not driver:
            return image_urls

        logger.info(f"Extracting images with Selenium: {url[:60]}...")
        driver.get(url)
        time.sleep(3)

        from selenium.webdriver.common.by import By

        # 查找所有图片元素
        img_elements = driver.find_elements(By.TAG_NAME, "img")

        for img in img_elements:
            try:
                # 尝试获取不同的图片属性
                src = img.get_attribute("src")
                data_src = img.get_attribute("data-src")
                data_original = img.get_attribute("data-original")

                # 优先使用高分辨率图片
                img_url = data_original or data_src or src

                if img_url:
                    # 转换为绝对 URL
                    if img_url.startswith('/'):
                        img_url = urljoin(BASE_URL, img_url)
                    elif not img_url.startswith('http'):
                        img_url = urljoin(url, img_url)

                    # 过滤掉图标、logo 等小图片
                    if any(skip in img_url.lower() for skip in ['icon', 'logo', 'avatar', 'placeholder', 'spacer']):
                        continue

                    # 检查图片尺寸（通过 width/height 属性）
                    width = img.get_attribute("width")
                    height = img.get_attribute("height")
                    if width and height:
                        try:
                            w, h = int(width), int(height)
                            if w < 100 or h < 100:  # 跳过太小的图片
                                continue
                        except:
                            pass

                    image_urls.append(img_url)
                    logger.info(f"Found image: {img_url[:80]}...")

            except Exception as e:
                continue

        # 去重
        image_urls = list(dict.fromkeys(image_urls))
        logger.info(f"Found {len(image_urls)} images")

    except Exception as e:
        logger.error(f"Error extracting images: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

    return image_urls


def enhance_content_with_images(content, url, logger):
    """
    增强内容中的图片：
    1. 将纯文本图片链接转换为 Markdown 图片格式
    2. 使用 Selenium 提取更多图片
    3. 下载图片到本地
    """
    from rss_monitor_base import download_images_from_markdown

    article_id = hashlib.md5(url.encode()).hexdigest()[:8]
    full_images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), IMAGES_DIR, article_id)
    os.makedirs(full_images_dir, exist_ok=True)

    # Step 1: 转换内容中的纯文本图片链接为 Markdown 格式
    # 匹配常见的图片 URL 模式
    image_patterns = [
        r'(https?://[^\s<>"\']+\.(?:jpg|jpeg|png|gif|webp))',
        r'\[Image\]:?\s*(https?://[^\s<>"\']+)',
        r'Image:\s*(https?://[^\s<>"\']+)',
    ]

    for pattern in image_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for img_url in matches:
            if 'markdown' not in content.lower() or f'![{img_url}' not in content:
                # 下载图片
                try:
                    filename = os.path.basename(img_url.split('?')[0])
                    if not filename or '.' not in filename:
                        ext = '.jpg'
                        if 'png' in img_url.lower():
                            ext = '.png'
                        elif 'gif' in img_url.lower():
                            ext = '.gif'
                        filename = hashlib.md5(img_url.encode()).hexdigest()[:12] + ext

                    local_path = os.path.join(full_images_dir, filename)

                    logger.info(f"Downloading image from content: {img_url[:60]}...")
                    response = requests_get_with_retry(img_url, timeout=30, stream=True)
                    response.raise_for_status()

                    with open(local_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)

                    logger.info(f"Image saved: {filename}")

                    # 替换内容中的链接
                    markdown_img = f'\n\n![{filename}]({local_path})\n\n'
                    content = content.replace(img_url, markdown_img)

                except Exception as e:
                    logger.warning(f"Failed to download image {img_url[:50]}: {e}")
                    # 仍转换为 Markdown 格式，但不下载
                    markdown_img = f'\n\n![image]({img_url})\n\n'
                    content = content.replace(img_url, markdown_img)

    # Step 2: 使用 Selenium 提取更多图片
    logger.info("Extracting additional images with Selenium...")
    additional_images = extract_images_with_selenium(url, logger)

    for img_url in additional_images:
        try:
            filename = os.path.basename(img_url.split('?')[0])
            if not filename or '.' not in filename:
                ext = '.jpg'
                if 'png' in img_url.lower():
                    ext = '.png'
                elif 'gif' in img_url.lower():
                    ext = '.gif'
                filename = hashlib.md5(img_url.encode()).hexdigest()[:12] + ext

            local_path = os.path.join(full_images_dir, filename)

            # 检查是否已经存在
            if os.path.exists(local_path):
                logger.info(f"Image already exists: {filename}")
                continue

            logger.info(f"Downloading image: {img_url[:60]}...")
            response = requests_get_with_retry(img_url, timeout=30, stream=True)
            response.raise_for_status()

            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Image saved: {filename}")

            # 在文章内容后添加图片
            markdown_img = f'\n\n![{filename}]({local_path})\n\n'
            content += markdown_img

        except Exception as e:
            logger.warning(f"Failed to download image {img_url[:50]}: {e}")

    return content


# ===== Siemens 特有的文章链接获取 =====

def get_article_links():
    """通过 Selenium 抓取 Press 页面获取文章链接"""
    driver = None
    try:
        # 优先抓 releases 列表页，press 首页受地区/活动卡片影响更大
        source_pages = [RELEASES_URL, PRESS_URL]
        logger.info(f"Fetching press pages: {source_pages}")

        driver = setup_driver()
        if not driver:
            return []

        from selenium.webdriver.common.by import By

        target_dates = get_siemens_target_dates()
        logger.info(f"Target dates: {sorted(target_dates)}")

        links = []
        seen = set()
        ignored_cta = 0
        cta_titles = {
            "learn more",
            "read more",
            "more",
            "details",
            "find out more",
        }

        for source_page in source_pages:
            try:
                driver.get(source_page)
                time.sleep(4)

                # releases 列表页常有“加载更多/更多”按钮，点击几轮尽量展开
                for _ in range(4):
                    clicked = False
                    for xp in [
                        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'load more')]",
                        "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'more')]",
                        "//a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'load more')]",
                    ]:
                        try:
                            btns = driver.find_elements(By.XPATH, xp)
                            visible_btns = [b for b in btns if b.is_displayed() and b.is_enabled()]
                            if not visible_btns:
                                continue
                            driver.execute_script("arguments[0].click();", visible_btns[0])
                            clicked = True
                            time.sleep(2)
                            break
                        except Exception:
                            continue
                    if not clicked:
                        break

                # releases 页面是无限滚动，很多条目不会通过按钮加载，需主动滚动触发懒加载
                prev_count = len(driver.find_elements(By.CSS_SELECTOR, "a[href*='/press/releases/']"))
                stable_rounds = 0
                for _ in range(12):
                    try:
                        driver.execute_script(
                            "window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'});"
                        )
                        # 某些布局使用独立滚动容器
                        driver.execute_script(
                            """
                            const scrollers = document.querySelectorAll('.infinite-scroll-component');
                            scrollers.forEach((el) => { el.scrollTop = el.scrollHeight; });
                            """
                        )
                    except Exception:
                        pass

                    time.sleep(1.5)
                    current_count = len(driver.find_elements(By.CSS_SELECTOR, "a[href*='/press/releases/']"))
                    if current_count > prev_count:
                        prev_count = current_count
                        stable_rounds = 0
                    else:
                        stable_rounds += 1
                        if stable_rounds >= 3:
                            break

                # 只抓取 releases，不抓取 features（features 页面包含大量 Cookie 等元数据）
                articles = driver.find_elements(By.CSS_SELECTOR, "a[href*='/press/releases/']")

                for article in articles:
                    try:
                        href = article.get_attribute("href")
                        if not href or href in seen:
                            continue

                        # 跳过列表页链接
                        if href.endswith('/releases') or href.endswith('/features'):
                            continue

                        # 跳过 features 页面（包含大量 Cookie 等元数据）
                        if '/press/features/' in href:
                            continue

                        seen.add(href)

                        # 尽量从链接附近的卡片容器提取真实标题，避免把 CTA 的 "Learn more" 当作标题
                        scope = article
                        try:
                            scope = article.find_element(
                                By.XPATH,
                                "./ancestor::*[self::article or self::li or contains(@class,'teaser') or contains(@class,'tile') or contains(@class,'card')][1]"
                            )
                        except Exception:
                            pass

                        title_candidates = [
                            article.text.strip(),
                            (article.get_attribute("aria-label") or "").strip(),
                            (article.get_attribute("title") or "").strip(),
                        ]
                        selector_candidates = [
                            "h1", "h2", "h3", "h4", "h5", "h6",
                            "[class*='title']",
                            "[class*='headline']",
                            "[class*='teaser']",
                            "[class*='copy']",
                        ]
                        for selector in selector_candidates:
                            try:
                                elems = scope.find_elements(By.CSS_SELECTOR, selector)
                            except Exception:
                                continue
                            for elem in elems:
                                text = " ".join(elem.text.split()).strip()
                                if text:
                                    title_candidates.append(text)

                        title = ""
                        for candidate in title_candidates:
                            normalized = " ".join(candidate.split()).strip()
                            if not normalized:
                                continue
                            if normalized.lower() in cta_titles:
                                continue
                            if len(normalized) < 8:
                                continue
                            title = normalized
                            break

                        if not title:
                            # CTA 链接经常只有 "Learn more"，此时退回到 URL slug，至少保住真实 release 链接
                            slug = href.rstrip("/").split("/")[-1]
                            slug = re.sub(r"[-_]+", " ", slug).strip()
                            slug = re.sub(r"\s+", " ", slug)
                            if slug and len(slug) >= 6 and slug.lower() not in cta_titles:
                                title = slug
                            else:
                                ignored_cta += 1
                                continue

                        # 尝试获取日期（在父元素或相邻元素中查找）
                        date_str = ""
                        try:
                            date_elem = scope.find_element(By.CSS_SELECTOR, "time, .date, [class*='date']")
                            date_str = date_elem.text.strip()
                        except Exception:
                            pass

                        link_hash = hashlib.md5(href.encode()).hexdigest()
                        links.append({
                            "link": href,
                            "link_hash": link_hash,
                            "date": date_str,
                            "title": title
                        })
                        logger.info(f"Found article: {title[:50]}...")

                    except Exception:
                        continue

                # 兜底：从页面源码抽取 release 链接（可见区域之外的脚本数据也能覆盖）
                source_html_links = extract_release_links_from_html(driver.page_source)
                for href in source_html_links:
                    if href in seen:
                        continue
                    seen.add(href)
                    link_hash = hashlib.md5(href.encode()).hexdigest()
                    links.append({
                        "link": href,
                        "link_hash": link_hash,
                        "date": "",
                        "title": _slug_to_title(href)
                    })
                    logger.info(f"Found article (source): {_slug_to_title(href)[:50]}...")
            except Exception as e:
                logger.warning(f"Failed scanning page {source_page}: {e}")
                continue

        # 兜底：从 sitemap 抓取 releases 链接，避免前端列表页漏展示
        sitemap_links = fetch_release_links_from_sitemaps(target_dates, logger)
        for item in sitemap_links:
            href = item["link"]
            if href in seen:
                continue
            seen.add(href)
            links.append({
                "link": href,
                "link_hash": item["link_hash"],
                "date": item.get("date", ""),
                "title": item.get("title", "")
            })
            logger.info(f"Found article (sitemap): {item.get('title', '')[:50]}...")

        if ignored_cta:
            logger.info(f"Ignored {ignored_cta} CTA-style release links")
        logger.info(f"Found {len(links)} article links")
        return links

    except Exception as e:
        logger.error(f"Error fetching press page: {e}")
        return []
    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass


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
        logger.info(f"New article: {link[:80]}")

        # 使用 Jina Reader 获取内容
        article = get_article_content_jina(link, logger)

        if article and article.get("content"):
            content = article["content"]
            content_len = len(content)
            logger.info(f"Got content ({content_len} chars)")

            # 内容已经在 get_article_content_jina 中通过 clean_content() 清理
            # 如果清理后内容太少，则跳过
            if len(content) < 200:
                logger.info(f"Content too short after cleaning, skipping: {link[:50]}")
                continue

            # 增强内容中的图片
            logger.info("Enhancing content with images...")
            content = enhance_content_with_images(content, link, logger)

            # 从正文提取日期，无法提取时跳过并标记，避免历史文章反复被推送
            target_dates = get_siemens_target_dates()

            article_date = None
            article_date_source = ""

            list_date = _extract_date_from_text(item.get("date", ""))
            if list_date:
                article_date = list_date
                article_date_source = "list_page"

            if not article_date:
                content_date = extract_article_date_from_content(content)
                if content_date:
                    article_date = content_date
                    article_date_source = "content_text"

            if not article_date:
                page_date, page_source = extract_article_date_from_page(link, logger)
                if page_date:
                    article_date = page_date
                    article_date_source = page_source or "page_html"

            if not article_date:
                logger.warning(
                    f"Skipping article with unknown date: {link[:80]} "
                    f"(title={item.get('title', '')[:40]!r}, list_date={item.get('date', '')!r})"
                )
                processed_links.add(link_hash)
                state["processed_links"] = list(processed_links)
                save_state(state, STATE_FILE)
                processed[link_hash] = {
                    "title": article.get("title", "Unknown"),
                    "url": link,
                    "processed_at": datetime.now().isoformat(),
                    "status": "skipped_unknown_date",
                    "list_date_raw": item.get("date", "")
                }
                save_processed(processed, PROCESSED_FILE)
                continue

            logger.info(f"Resolved article date: {article_date} (source={article_date_source})")

            if article_date not in target_dates:
                logger.info(f"Skipping old article: {article_date} {link[:80]}")
                processed_links.add(link_hash)
                state["processed_links"] = list(processed_links)
                save_state(state, STATE_FILE)
                processed[link_hash] = {
                    "title": article.get("title", "Unknown"),
                    "url": link,
                    "processed_at": datetime.now().isoformat(),
                    "status": "skipped_old",
                    "article_date": article_date.isoformat()
                }
                save_processed(processed, PROCESSED_FILE)
                continue

            # 生成 article_id，确保与 enhance_content_with_images 中使用的相同
            article_id = hashlib.md5(link.encode()).hexdigest()[:8]

            # 使用公共模块处理文章
            result = process_single_article(
                content,
                article["title"],
                IMAGES_DIR,
                logger,
                article_id=article_id
            )

            if result:
                processed_links.add(link_hash)
                state["processed_links"] = list(processed_links)
                save_state(state, STATE_FILE)

                processed[link_hash] = {
                    "title": article["title"],
                    "url": link,
                    "content_length": content_len,
                    "translated_length": len(result.get("content", "")) if isinstance(result, dict) else len(str(result)),
                    "processed_at": datetime.now().isoformat(),
                    "status": "success",
                    "article_date": article_date.isoformat()
                }
                save_processed(processed, PROCESSED_FILE)
                logger.info(f"Completed: {article['title'][:50]}")
        else:
            logger.warning(f"Failed to get content for: {link}")

    if new_count == 0:
        logger.info("No new articles found")
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

    logger.info("Siemens Healthineers Polling service started.")
    logger.info("- Only processes articles from today and yesterday")
    logger.info("- Runs every 4 hours")
    logger.info("- Auto-publishes to WeChat after processing")

    logger.info("Running initial check...")
    process_articles()

    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    main()
