#!/usr/bin/env python3
"""
手动抓取 Siemens 2月12日文章并翻译 - 使用 requests + BeautifulSoup
模拟今天是2月13日，抓取昨天（2月12日）的文章
"""

import hashlib
import time
import logging
import re
from datetime import datetime, timedelta
import requests
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

def get_article_links():
    """通过 requests + BeautifulSoup 抓取 Press 页面获取文章链接"""
    try:
        logger.info(f"Fetching press page: {PRESS_URL}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        response = requests.get(PRESS_URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = []
        seen = set()
        
        # 查找所有文章链接
        # Siemens 网站的文章链接通常在 releases 或 features 路径下
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            
            # 检查是否是文章链接
            if '/press/releases/' in href or '/press/features/' in href:
                # 转换为完整URL
                if href.startswith('/'):
                    full_url = BASE_URL + href
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # 跳过列表页链接和重复链接
                if (full_url.endswith('/releases') or 
                    full_url.endswith('/features') or
                    full_url in seen):
                    continue
                
                # 跳过 cookie、privacy 等非文章链接
                if any(x in full_url.lower() for x in ['cookie', 'privacy', 'terms', 'legal']):
                    continue
                
                seen.add(full_url)
                
                # 获取标题
                title = a_tag.get_text(strip=True)
                if not title:
                    title = href.split('/')[-1].replace('-', ' ').title()
                
                # 尝试获取日期
                date_str = ""
                # 在父元素或相邻元素中查找日期
                parent = a_tag.find_parent(['article', 'div', 'li'])
                if parent:
                    time_elem = parent.find(['time', 'span'], class_=lambda x: x and 'date' in x.lower())
                    if time_elem:
                        date_str = time_elem.get_text(strip=True)
                
                link_hash = hashlib.md5(full_url.encode()).hexdigest()
                links.append({
                    "link": full_url,
                    "link_hash": link_hash,
                    "date": date_str,
                    "title": title
                })
                
                logger.info(f"Found article: {title[:60]}... | Date: {date_str}")
        
        logger.info(f"Total valid links: {len(links)}")
        return links
        
    except Exception as e:
        logger.error(f"Error fetching press page: {e}")
        return []

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
        
        # 从 Jina 返回的内容中提取标题（第一行通常是标题）
        lines = content.split('\n')
        title = ""
        for line in lines[:10]:
            line = line.strip()
            if line and not line.startswith('Source:') and not line.startswith('http'):
                title = line.replace('#', '').strip()
                break
        
        # 过滤掉 cookie/privacy 页面
        if any(x in title.lower() for x in ['cookie', 'privacy policy', 'terms of use']):
            logger.warning(f"Skipping non-article page: {title}")
            return None
        
        logger.info(f"Got content: {len(content)} chars")
        logger.info(f"Title: {title[:60]}...")
        
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
    
    # 在前2000字符中查找日期
    search_text = content[:2000]
    
    for pattern in patterns:
        match = re.search(pattern, search_text)
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
        
        logger.info("Starting translation...")
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
    
    # 创建安全文件名
    safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()
    safe_title = re.sub(r'\s+', '_', safe_title)
    filename = f"{article_date}_{safe_title}"
    
    # 保存原文
    original_path = os.path.join(output_dir, f"{filename}_original.md")
    with open(original_path, 'w', encoding='utf-8') as f:
        f.write(f"# {title}\n\n")
        f.write(f"Source: {content[:200]}...\n\n")
        f.write(content)
    logger.info(f"✓ Saved original: {original_path}")
    
    # 保存译文
    if translated_content:
        translated_path = os.path.join(output_dir, f"{filename}_translated.md")
        with open(translated_path, 'w', encoding='utf-8') as f:
            f.write(translated_content)
        logger.info(f"✓ Saved translation: {translated_path}")
        return translated_path
    
    return None

def main():
    """主流程：抓取2月12日文章并翻译"""
    print("\n" + "=" * 80)
    print(f"📰 Siemens Healthineers 文章抓取")
    print(f"🎯 目标日期: {yesterday} (2026-02-12)")
    print(f"📅 模拟今天: {today} (2026-02-13)")
    print("=" * 80 + "\n")
    
    # 1. 获取文章链接
    article_links = get_article_links()
    
    if not article_links:
        logger.error("❌ No article links found")
        print("\n可能的原因：")
        print("1. 网站结构发生变化")
        print("2. 需要处理反爬虫机制（如 JavaScript 渲染）")
        print("3. 网站暂时不可用")
        return
    
    print(f"\n📋 Found {len(article_links)} article links")
    print("=" * 80 + "\n")
    
    # 2. 处理每篇文章
    processed_count = 0
    target_date_count = 0
    
    for i, item in enumerate(article_links, 1):
        link = item["link"]
        
        print(f"\n{'='*80}")
        print(f"📄 [{i}/{len(article_links)}] Processing: {item['title'][:60]}...")
        print(f"🔗 URL: {link}")
        print(f"📅 Page date: {item['date']}")
        
        # 获取内容
        article = get_article_content_jina(link)
        
        if not article or not article.get("content"):
            logger.warning(f"⚠️  Failed to get content")
            continue
        
        # 从内容中提取日期
        article_date = extract_date_from_content(article["content"])
        
        if not article_date:
            logger.warning(f"⚠️  Could not extract date from content")
            # 尝试从URL推断日期
            if '2026' in link:
                # URL可能包含日期
                date_match = re.search(r'2026[\-/](\d{2})[\-/](\d{2})', link)
                if date_match:
                    try:
                        article_date = datetime(2026, int(date_match.group(1)), int(date_match.group(2))).date()
                        logger.info(f"📅 Extracted date from URL: {article_date}")
                    except:
                        pass
        
        if article_date:
            logger.info(f"📅 Article date: {article_date}")
        else:
            logger.warning(f"⚠️  No date found, using current date as fallback")
            article_date = yesterday  # 假设是目标日期
        
        # 检查是否是2月12日的文章
        if article_date != yesterday:
            logger.info(f"⏭️  Not target date ({yesterday}), skipping")
            continue
        
        target_date_count += 1
        
        # 翻译文章
        print(f"\n📝 Translating article...")
        translated = translate_article(article["content"], article["title"])
        
        if translated:
            # 保存文章
            saved_path = save_article(
                article["title"],
                article["content"],
                translated,
                article_date
            )
            if saved_path:
                processed_count += 1
                print(f"\n✅ Successfully processed and saved!")
                print(f"   Translation: {saved_path}")
        else:
            logger.error(f"❌ Translation failed")
    
    print(f"\n{'='*80}")
    print(f"📊 SUMMARY")
    print(f"{'='*80}")
    print(f"Total links found: {len(article_links)}")
    print(f"Target date ({yesterday}) articles: {target_date_count}")
    print(f"Successfully processed: {processed_count}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
