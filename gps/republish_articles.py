#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重新发布未成功发布到微信的文章

用法：
    python3 republish_articles.py          # 交互式选择
    python3 republish_articles.py --all    # 发布所有未发布的文章
"""

import os
import sys
import glob
import json
from datetime import datetime

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from publish_to_wechat import publish_to_wechat

# 文章保存目录
ARTICLES_DIR = os.path.expanduser("~/Documents/Automated_Articles")
PROCESSED_FILE = "ph_processed.json"


def load_processed():
    """加载已处理记录"""
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_processed(processed):
    """保存处理记录"""
    with open(PROCESSED_FILE, 'w') as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)


def find_philips_articles(days=3):
    """查找最近几天的 Philips 相关文章"""
    patterns = [
        "philips*", "ultrasound*", "preciseonco*", "seismic*",
        "radiology*", "azurion*", "cardiac*", "inkspace*"
    ]

    articles = []
    for pattern in patterns:
        for day_offset in range(days):
            date = datetime.now().date()
            from datetime import timedelta
            target_date = date - timedelta(days=day_offset)
            date_str = target_date.strftime("%Y-%m-%d")

            full_pattern = os.path.join(ARTICLES_DIR, f"{date_str}-{pattern}.md")
            articles.extend(glob.glob(full_pattern, recursive=False))

    # 去重并排序
    articles = sorted(set(articles), reverse=True)
    return articles


def republish_article(md_path):
    """重新发布单篇文章"""
    print(f"\n{'='*60}")
    print(f"📤 正在发布: {os.path.basename(md_path)}")
    print(f"{'='*60}")

    result = publish_to_wechat(md_path, theme="grace", skip_review=True)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description='重新发布未成功的文章到微信')
    parser.add_argument('--all', action='store_true', help='发布所有找到的文章')
    parser.add_argument('--days', type=int, default=3, help='查找最近几天的文章')
    args = parser.parse_args()

    print("\n" + "="*60)
    print("📱 Philips 文章重新发布工具")
    print("="*60 + "\n")

    # 查找文章
    articles = find_philips_articles(days=args.days)

    if not articles:
        print("❌ 没有找到需要发布的文章")
        return

    print(f"找到 {len(articles)} 篇文章：\n")
    for idx, article in enumerate(articles, 1):
        filename = os.path.basename(article)
        size = os.path.getsize(article) / 1024
        print(f"  [{idx}] {filename} ({size:.1f} KB)")

    if args.all:
        # 发布所有文章
        print(f"\n🚀 开始发布所有 {len(articles)} 篇文章...\n")
        success_count = 0
        for article in articles:
            if republish_article(article):
                success_count += 1
            else:
                print(f"⚠️ 发布失败，继续下一篇...")

        print(f"\n{'='*60}")
        print(f"✅ 发布完成: {success_count}/{len(articles)} 篇成功")
        print(f"{'='*60}\n")
    else:
        # 交互式选择
        try:
            choice = input("\n请输入要发布的文章编号 (多个用逗号分隔，输入 'all' 发布全部，'q' 退出): ").strip()

            if choice.lower() == 'q':
                print("👋 已取消\n")
                return

            if choice.lower() == 'all':
                indices = list(range(len(articles)))
            else:
                indices = [int(x.strip()) - 1 for x in choice.split(',')]

            for idx in indices:
                if 0 <= idx < len(articles):
                    republish_article(articles[idx])
                else:
                    print(f"⚠️ 无效编号: {idx + 1}")

        except ValueError:
            print("❌ 请输入有效的数字\n")
        except KeyboardInterrupt:
            print("\n\n👋 已取消\n")


if __name__ == "__main__":
    main()
