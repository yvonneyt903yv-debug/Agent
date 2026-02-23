#!/usr/bin/env python3
"""
手动抓取 Siemens 2月12日文章并翻译
模拟今天是2月13日，抓取昨天（2月12日）的文章
"""

import hashlib
import time
import logging
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 模拟今天是2月13日
today = datetime(2026, 2, 13).date()
yesterday = today - timedelta(days=1)  # 2026-02-12

print(f"模拟日期：今天是 {today}, 抓取目标日期: {yesterday}")
print("=" * 80)

# Siemens 配置
PRESS_URL = "https://www.siemens-healthineers.com/press"
BASE_URL = "https://www.siemens-healthineers.com"

def setup_driver():
    """设置 Selenium WebDriver"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except Exception as e:
        logger.error(f"Failed to setup driver: {e}")
        return None

def get_article_links():
    """通过 Selenium 抓取 Press 页面获取文章链接"""
    driver = None
    try:
        logger.info(f"Fetching press page: {PRESS_URL}")
        
        driver = setup_driver()
        if not driver:
            return []
        
        driver.get(PRESS_URL)
        time.sleep(5)
        
        from selenium.webdriver.common.by import By
        
        links = []
        seen = set()
        
        # 查找所有文章链接 - 更精确的选择器
        # 只选择真正的文章链接，排除 cookie 政策等
        articles = driver.find_elements(By.CSS_SELECTOR, 
            "a[href*='/press/releases/'], a[href*='/press/features/']")
        
        logger.info(f"Found {len(articles)} potential links")
        
        for article in articles:
            try:
                href = article.get_attribute("href")
                if not href or href in seen:
                    continue
                
                # 跳过列表页链接和非文章链接
                if (href.endswith('/releases') or 
                    href.endswith('/features') or
                    'cookie' in href.lower() or
                    'privacy' in href.lower() or
                    'terms' in href.lower()):
                    continue
                
                seen.add(href)
                
                # 获取文章标题
                title = article.text.strip()
                if not title:
                    try:
                        title_elem = article.find_element(By.CSS_SELECTOR, "h3, h5, h6, .title, span")
                        title = title_elem.text.strip()
                    except:
                        title = href.split('/')[-1].replace('-', ' ').title()
                
                # 尝试获取日期
                date_str = ""
                try:
                    # 在父元素或相邻元素中查找日期
                    parent = article.find_element(By.XPATH, "./ancestor::article | ./ancestor::div[contains(@class, 'card')]")
                    if parent:
                        date_elem = parent.find_element(By.CSS_SELECTOR, 
                            "time, .date, [class*='date'], span[class*='time']")
                        date_str = date_elem.text.strip()
                except:
                    pass
                
                link_hash = hashlib.md5(href.encode()).hexdigest()
                links.append({
                    "link": href,
                    "link_hash": link_hash,
                    "date": date_str,
                    "title": title
                })
                logger.info(f"Found article: {title[:60]}... | Date: {date_str}")
                
            except Exception as e:
                continue
        
        logger.info(f"Filtered to {len(links)} valid article links")
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

def parse_date(date_str):
    """解析日期字符串"""
    if not date_str:
        return None
    
    date_str = date_str.strip()
    formats = [
        "%B %d, %Y",      # January 16, 2026
        "%b %d, %Y",      # Jan 16, 2026
        "%B %d %Y",       # January 16 2026
        "%Y-%m-%d",       # 2026-01-16
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    
    return None

def get_article_content_jina(url):
    """用 Jina Reader 获取文章内容"""
    import requests
    
    try:
        logger.info(f"Fetching with Jina Reader: {url[:80]}...")
        
        jina_url = f"https://r.jina.ai/{url}"
        headers = {
            'Accept': 'text/markdown',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(jina_url, headers=headers, timeout=60)
        response.raise_for_status()
        
        content = response.text
        
        # 从 Jina 返回的内容中提取标题
        lines = content.split('\n')
        title = ""
        for line in lines[:10]:
            if line.strip() and not line.startswith('Source:'):
                title = line.strip().replace('#', '').strip()
                break
        
        # 过滤掉 cookie 相关内容
        if 'cookie' in title.lower() or 'privacy' in title.lower():
            logger.warning(f"Skipping cookie/privacy page: {title}")
            return None
        
        logger.info(f"Got content: {len(content)} chars, title: {title[:50]}...")
        
        return {
            "title": title,
            "content": content,
            "url": url
        }
        
    except Exception as e:
        logger.error(f"Jina Reader failed: {e}")
        return None

def extract_date_from_content(content):
    """从文章内容中提取发布日期"""
    # Siemens 文章日期格式: "February 5, 2026"
    patterns = [
        r'Published[\s:]*([A-Za-z]+ \d{1,2},? \d{4})',
        r'([A-Za-z]+ \d{1,2},? \d{4})',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, content[:1000])  # 只在前1000字符中查找
        if match:
            date_str = match.group(1)
            parsed = parse_date(date_str)
            if parsed:
                return parsed
    
    return None

def translate_article(content, title):
    """翻译文章内容"""
    import sys
    sys.path.insert(0, '/Users/yvonne/Documents/Agent/src')
    
    try:
        from translator import translate_article as translate_text
        
        # 准备翻译内容（标题 + 正文）
        full_text = f"# {title}\n\n{content}"
        
        logger.info("Translating article...")
        translated = translate_text(full_text)
        
        return translated
        
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return None

def save_article(title, content, translated_content, article_date):
    """保存文章到文件"""
    import os
    
    output_dir = "/Users/yvonne/Documents/Agent/gps/siemens_articles"
    os.makedirs(output_dir, exist_ok=True)
    
    # 创建文件名
    safe_title = re.sub(r'[^\w\s-]', '', title)[:50]
    filename = f"{article_date}_{safe_title}"
    
    # 保存原文
    original_path = os.path.join(output_dir, f"{filename}_original.md")
    with open(original_path, 'w', encoding='utf-8') as f:
        f.write(content)
    logger.info(f"Saved original: {original_path}")
    
    # 保存译文
    if translated_content:
        translated_path = os.path.join(output_dir, f"{filename}_translated.md")
        with open(translated_path, 'w', encoding='utf-8') as f:
            f.write(translated_content)
        logger.info(f"Saved translation: {translated_path}")

def main():
    """主流程：抓取2月12日文章并翻译"""
    print("\n" + "=" * 80)
    print(f"抓取 Siemens Healthineers 文章")
    print(f"目标日期: {yesterday} (2026-02-12)")
    print("=" * 80 + "\n")
    
    # 1. 获取文章链接
    article_links = get_article_links()
    
    if not article_links:
        logger.error("No article links found")
        return
    
    # 2. 处理每篇文章
    processed_count = 0
    for item in article_links:
        link = item["link"]
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing: {item['title'][:60]}...")
        logger.info(f"URL: {link}")
        
        # 获取内容
        article = get_article_content_jina(link)
        
        if not article or not article.get("content"):
            logger.warning(f"Failed to get content for: {link}")
            continue
        
        # 从内容中提取日期
        article_date = extract_date_from_content(article["content"])
        
        if not article_date:
            logger.warning(f"Could not extract date, skipping: {article['title'][:50]}...")
            continue
        
        logger.info(f"Extracted date: {article_date}")
        
        # 检查是否是2月12日的文章
        if article_date != yesterday:
            logger.info(f"Not target date ({yesterday}), skipping: {article_date}")
            continue
        
        # 翻译文章
        translated = translate_article(article["content"], article["title"])
        
        if translated:
            # 保存文章
            save_article(
                article["title"],
                article["content"],
                translated,
                article_date
            )
            processed_count += 1
            logger.info(f"✅ Successfully processed: {article['title'][:60]}...")
        else:
            logger.error(f"❌ Translation failed for: {article['title'][:60]}...")
    
    logger.info(f"\n{'='*80}")
    logger.info(f"处理完成！共处理 {processed_count} 篇2月12日的文章")
    logger.info(f"{'='*80}\n")

if __name__ == "__main__":
    main()
