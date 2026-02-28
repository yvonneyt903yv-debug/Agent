#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立的微信公众号发布脚本

使用方法：
    python publish_to_wechat.py <markdown文件路径> [主题] [--skip-review]

示例：
    python publish_to_wechat.py output/final_published/PUBLISH_20260125_183148_ID0_被访者为数学家兼哲学.md
    python publish_to_wechat.py article.md grace --skip-review
"""

import os
import sys
import subprocess
import glob
from pathlib import Path

# 项目根目录 (Agent/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))


def find_baoyu_script():
    """查找 baoyu-post-to-wechat 脚本路径"""
    env_override = os.environ.get("BAOYU_WECHAT_SCRIPT")
    if env_override and os.path.exists(env_override):
        return env_override

    project_root = Path(PROJECT_ROOT)
    script_dir = Path(__file__).resolve().parent
    search_roots = [
        project_root,
        project_root.parent,
        script_dir,
        script_dir.parent,
        Path.cwd(),
    ]
    candidate_suffixes = [
        "baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-article.ts",
        "baoyu-skills/baoyu-post-to-wechat/scripts/wechat-article.ts",
        "gps/baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-article.ts",
        "gps/baoyu-skills/baoyu-post-to-wechat/scripts/wechat-article.ts",
        "gps/src/baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-article.ts",
        "gps/src/baoyu-skills/baoyu-post-to-wechat/scripts/wechat-article.ts",
    ]

    checked = set()
    for root in search_roots:
        for suffix in candidate_suffixes:
            candidate = (root / suffix).resolve()
            candidate_str = str(candidate)
            if candidate_str in checked:
                continue
            checked.add(candidate_str)
            if candidate.exists():
                return candidate_str

    # 兜底：在常见根目录下做一次轻量搜索，适配不同部署结构
    glob_patterns = [
        "**/baoyu-post-to-wechat/scripts/wechat-article.ts",
        "**/skills/baoyu-post-to-wechat/scripts/wechat-article.ts",
    ]
    for root in search_roots:
        if not root.exists():
            continue
        for pattern in glob_patterns:
            for match in root.glob(pattern):
                if match.is_file():
                    return str(match.resolve())

    return None


def list_published_articles():
    """列出所有已发布的文章"""
    final_dir = os.path.join(PROJECT_ROOT, "output/final_published")

    if not os.path.exists(final_dir):
        print(f"❌ 发布目录不存在: {final_dir}")
        return []

    md_files = sorted(glob.glob(os.path.join(final_dir, "PUBLISH_*.md")), reverse=True)
    return md_files


def review_markdown_with_gemini(md_file_path):
    """
    使用 Gemini 审核 Markdown 文件

    返回:
        审核后的文件路径
    """
    try:
        from gemini_reviewer import review_markdown_for_wechat
    except ImportError:
        print("⚠️ 未找到 gemini_reviewer 模块，跳过审核")
        return md_file_path

    print(f"\n{'='*60}")
    print(f"🔍 正在使用 Gemini 审核文章...")
    print(f"{'='*60}\n")

    # 读取原始内容
    with open(md_file_path, 'r', encoding='utf-8') as f:
        original_content = f.read()

    # Gemini 审核
    reviewed_content = review_markdown_for_wechat(original_content)

    # 保存审核后的文件
    reviewed_path = md_file_path.replace('.md', '_reviewed.md')
    with open(reviewed_path, 'w', encoding='utf-8') as f:
        f.write(reviewed_content)

    print(f"\n✅ 审核完成，已保存到: {reviewed_path}")

    return reviewed_path


def publish_to_wechat(md_file_path, theme="grace", skip_review=False):
    """
    发布文章到微信公众号

    参数:
        md_file_path: Markdown 文件的完整路径
        theme: 主题名称，默认为 grace（优雅风格）
               可选: grace, cyan, purple, green, orange, red, blue, wechat-nice
        skip_review: 是否跳过 Gemini 审核
    """
    # 检查文件是否存在
    if not os.path.exists(md_file_path):
        print(f"❌ 文件不存在: {md_file_path}")
        return False

    # Gemini 审核（除非跳过）
    if not skip_review:
        md_file_path = review_markdown_with_gemini(md_file_path)

    # 查找 baoyu 脚本
    baoyu_script = find_baoyu_script()
    if not baoyu_script:
        print("❌ 未找到 baoyu-post-to-wechat 脚本")
        print("请确保 baoyu-skills 文件夹存在，或设置 BAOYU_WECHAT_SCRIPT 指向 wechat-article.ts")
        return False

    print(f"\n{'='*60}")
    print(f"📤 准备发布文章到微信公众号")
    print(f"{'='*60}")
    print(f"📄 文章文件: {os.path.basename(md_file_path)}")
    print(f"🎨 使用主题: {theme}")
    print(f"{'='*60}\n")

    # 构建命令
    cmd = [
        "npx", "-y", "bun",
        baoyu_script,
        "--markdown", md_file_path,
        "--theme", theme
    ]

    # 设置环境变量以禁用代理
    env = os.environ.copy()
    env['NO_PROXY'] = '127.0.0.1,localhost'

    print("🌐 正在启动浏览器自动化...")
    print("\n⚠️  重要提示：")
    print("  1. 请确保 Chrome 浏览器已安装")
    print("  2. 准备好微信扫码登录")
    print("  3. 发布过程中请勿操作浏览器窗口")
    print("  4. 等待自动化完成\n")

    try:
        # 执行命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5分钟超时
            cwd=os.path.dirname(baoyu_script),
            env=env
        )

        if result.returncode == 0:
            print(f"\n{'='*60}")
            print(f"✅ 文章已成功发布到微信公众号！")
            print(f"{'='*60}\n")
            return True
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            print(f"\n{'='*60}")
            print(f"❌ 发布失败")
            print(f"{'='*60}")
            print(f"错误信息: {error_msg[:500]}\n")
            return False

    except subprocess.TimeoutExpired:
        print(f"\n{'='*60}")
        print(f"⚠️ 发布超时（可能需要手动扫码）")
        print(f"{'='*60}")
        print("请检查浏览器窗口是否需要扫码登录\n")
        return False

    except FileNotFoundError:
        print(f"\n{'='*60}")
        print(f"❌ 未安装 Node.js 或 Bun")
        print(f"{'='*60}")
        print("请先安装 Node.js: https://nodejs.org/")
        print("或安装 Bun: https://bun.sh/\n")
        return False

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ 发布异常: {str(e)}")
        print(f"{'='*60}\n")
        return False


def interactive_mode():
    """交互式选择文章发布"""
    print("\n" + "="*60)
    print("📱 微信公众号文章发布工具")
    print("="*60 + "\n")

    # 列出所有文章
    articles = list_published_articles()

    if not articles:
        print("❌ 没有找到已发布的文章")
        print("请先运行 Agent 生成文章\n")
        return

    print(f"找到 {len(articles)} 篇文章：\n")

    for idx, article in enumerate(articles, 1):
        filename = os.path.basename(article)
        # 提取文件大小和修改时间
        size = os.path.getsize(article) / 1024  # KB
        mtime = os.path.getmtime(article)
        from datetime import datetime
        mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')

        print(f"  [{idx}] {filename}")
        print(f"      大小: {size:.1f} KB | 修改时间: {mtime_str}\n")

    # 选择文章
    try:
        choice = input("请输入要发布的文章编号 (输入 q 退出): ").strip()

        if choice.lower() == 'q':
            print("👋 已取消\n")
            return

        idx = int(choice)
        if idx < 1 or idx > len(articles):
            print(f"❌ 无效的编号，请输入 1-{len(articles)}\n")
            return

        selected_article = articles[idx - 1]

        # 选择主题
        print("\n可用主题:")
        themes = ["grace", "wechat-nice", "cyan", "purple", "green", "orange", "red", "blue"]
        for i, theme in enumerate(themes, 1):
            print(f"  [{i}] {theme}")

        theme_choice = input("\n请选择主题编号 (直接回车使用默认 grace): ").strip()

        if theme_choice:
            theme_idx = int(theme_choice)
            if 1 <= theme_idx <= len(themes):
                theme = themes[theme_idx - 1]
            else:
                theme = "grace"
        else:
            theme = "grace"

        # 是否跳过审核
        skip_review = input("\n是否跳过 Gemini 审核? (y/n, 默认 n): ").strip().lower() == 'y'

        # 确认发布
        print(f"\n即将发布:")
        print(f"  文章: {os.path.basename(selected_article)}")
        print(f"  主题: {theme}")
        print(f"  Gemini 审核: {'跳过' if skip_review else '启用'}")

        confirm = input("\n确认发布? (y/n): ").strip().lower()

        if confirm == 'y':
            publish_to_wechat(selected_article, theme, skip_review)
        else:
            print("👋 已取消发布\n")

    except ValueError:
        print("❌ 请输入有效的数字\n")
    except KeyboardInterrupt:
        print("\n\n👋 已取消\n")


def main():
    """主函数"""
    # 解析命令行参数
    args = sys.argv[1:]
    skip_review = '--skip-review' in args
    if skip_review:
        args.remove('--skip-review')

    if len(args) > 0:
        # 命令行模式：直接指定文件
        md_file = args[0]
        theme = args[1] if len(args) > 1 else "grace"

        # 如果是相对路径，转换为绝对路径
        if not os.path.isabs(md_file):
            md_file = os.path.join(PROJECT_ROOT, md_file)

        publish_to_wechat(md_file, theme, skip_review)
    else:
        # 交互式模式：列出文章供选择
        interactive_mode()


if __name__ == "__main__":
    main()
