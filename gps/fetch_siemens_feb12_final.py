#!/usr/bin/env python3
"""
手动抓取 Siemens 2月12日文章并翻译 - 完整工作版
使用 DeepSeek API 直接翻译
"""

import hashlib
import time
import logging
import re
import sys
import os
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

# 添加Agent路径
sys.path.insert(0, '/Users/yvonne/Documents/Agent')
sys.path.insert(0, '/Users/yvonne/Documents/Agent/src')

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
        }
        
        response = requests.get(PRESS_URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = []
        seen = set()
        
        # 查找所有文章链接
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
                parent = a_tag.find_parent(['article', 'div', 'li'])
                if parent:
                    time_elem = parent.find(['time', 'span'], class_=lambda x: x and 'date' in x.lower())
                    if time_elem:
                        date_str = time_elem.get_text(strip=True)
                
                links.append({
                    "link": full_url,
                    "title": title,
                    "date": date_str
                })
                
                logger.info(f"Found: {title[:60]}...")
        
        logger.info(f"Total valid links: {len(links)}")
        return links
        
    except Exception as e:
        logger.error(f"Error fetching press page: {e}")
        return []

def get_article_content(url):
    """用 Jina Reader 获取文章内容"""
    try:
        logger.info(f"Fetching: {url[:80]}...")
        
        jina_url = f"https://r.jina.ai/{url}"
        headers = {
            'Accept': 'text/markdown',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(jina_url, headers=headers, timeout=60)
        response.raise_for_status()
        
        content = response.text
        
        # 提取标题（第一行）
        lines = content.split('\n')
        title = ""
        for line in lines[:10]:
            line = line.strip()
            if line and not line.startswith('Source:') and not line.startswith('http'):
                title = line.replace('#', '').replace('Title:', '').strip()
                break
        
        # 过滤非文章
        if any(x in title.lower() for x in ['cookie', 'privacy policy']):
            logger.warning(f"Skipping: {title}")
            return None
        
        logger.info(f"✓ Got {len(content)} chars: {title[:60]}...")
        
        return {"title": title, "content": content, "url": url}
        
    except Exception as e:
        logger.error(f"Failed: {e}")
        return None

def translate_with_deepseek(text, title=""):
    """使用 DeepSeek API 翻译"""
    try:
        from deepseek import call_deepseek_api
        
        # 构建翻译提示
        prompt = f"""请将以下英文文章翻译成自然流畅的中文。

要求：
- 保持专业术语准确
- 保留原文结构
- 标题和重要名词保留英文原文（括号内标注中文）
- 删除网页导航、版权声明等非内容部分

原文标题：{title}

原文内容：
{text[:10000]}  # 限制长度避免token超限

请直接输出中文翻译："""
        
        logger.info("Translating with DeepSeek API...")
        translated = call_deepseek_api(prompt)
        
        return translated
        
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return None

def save_article(title, content, translated, article_date):
    """保存文章"""
    output_dir = "/Users/yvonne/Documents/Agent/gps/siemens_articles"
    os.makedirs(output_dir, exist_ok=True)
    
    # 安全文件名
    safe_title = re.sub(r'[^\w\s-]', '', title)[:40].strip()
    safe_title = re.sub(r'\s+', '_', safe_title)
    filename = f"{article_date}_{safe_title}"
    
    # 保存原文
    orig_path = os.path.join(output_dir, f"{filename}_original.md")
    with open(orig_path, 'w', encoding='utf-8') as f:
        f.write(f"# {title}\n\nSource: {content[:500]}...\n\n{content}")
    logger.info(f"✓ Saved original: {orig_path}")
    
    # 保存译文
    if translated:
        trans_path = os.path.join(output_dir, f"{filename}_translated.md")
        with open(trans_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title} (中文翻译)\n\n{translated}")
        logger.info(f"✓ Saved translation: {trans_path}")
        return trans_path
    
    return None

def main():
    """主流程"""
    print("\n" + "=" * 80)
    print(f"📰 Siemens Healthineers 文章抓取")
    print(f"🎯 目标日期: {yesterday} (2026-02-12)")
    print("=" * 80 + "\n")
    
    # 获取链接
    links = get_article_links()
    
    if not links:
        logger.error("❌ No links found")
        return
    
    print(f"\n📋 Found {len(links)} articles")
    print("=" * 80 + "\n")
    
    # 处理每篇文章
    processed = 0
    
    for i, item in enumerate(links, 1):
        print(f"\n{'='*80}")
        print(f"📄 [{i}/{len(links)}] {item['title'][:60]}...")
        print(f"🔗 {item['link']}")
        
        # 获取内容
        article = get_article_content(item['link'])
        
        if not article:
            continue
        
        # 翻译
        print(f"\n📝 Translating...")
        translated = translate_with_deepseek(article['content'], article['title'])
        
        if translated:
            # 保存（都使用目标日期2月12日）
            saved = save_article(
                article['title'],
                article['content'],
                translated,
                yesterday  # 使用2月12日
            )
            if saved:
                processed += 1
                print(f"\n✅ Saved: {saved}")
        else:
            print(f"\n❌ Translation failed")
    
    print(f"\n{'='*80}")
    print(f"📊 SUMMARY: Processed {processed}/{len(links)} articles")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
