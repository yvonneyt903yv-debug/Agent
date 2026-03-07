#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译+审校一体化工具
功能：整合 translate_to_word_ds.py 和 review_markdown_ds.py
     先翻译，用户确认后，再审校
"""

import os
import sys
import subprocess
import argparse

# 优先补充常见源码路径，避免强依赖“同目录放模块”
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXTRA_IMPORT_DIRS = [
    SCRIPT_DIR,
    os.path.join(SCRIPT_DIR, "spiders"),
    os.path.join(SCRIPT_DIR, "Agent"),
    os.path.join(SCRIPT_DIR, "Agent", "src"),
]
for extra_dir in EXTRA_IMPORT_DIRS:
    if os.path.isdir(extra_dir) and extra_dir not in sys.path:
        sys.path.insert(0, extra_dir)

# ==================== 直接导入原有脚本的函数 ====================

# 导入翻译与格式转换函数
try:
    from src import translator
except ImportError:
    try:
        import translator
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
        print("请确保可用路径包含：当前目录 / spiders / Agent / Agent/src")
        sys.exit(1)

try:
    from singju_ds import convert_to_markdown_and_copy
    import pypandoc
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    print("请确保可用路径包含：当前目录 / spiders / Agent / Agent/src")
    print("请确保已安装: pip install pypandoc")
    sys.exit(1)

# 从 review_markdown_ds.py 导入审校相关函数
try:
    from review_markdown_ds import (
        review_markdown_content,      # 审校函数
        save_reviewed_markdown         # 保存函数
    )
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    print("请确保 review_markdown_ds.py 位于当前目录、spiders 或 Agent/src")
    sys.exit(1)


# ==================== 辅助函数 ====================

def print_section(title):
    """打印分隔线"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def ask_user_confirmation(auto_mode=False):
    """询问用户是否继续审校"""
    if auto_mode:
        print("\n[自动模式] 跳过用户确认，直接进入审校...")
        return True
    
    while True:
        print("\n" + "="*70)
        print("  ⏸️  用户确认")
        print("="*70)
        print("\n📄 翻译结果已保存，请查看 Word 文档")
        print("\n💡 提示：")
        print("   - 如果翻译质量满意，输入 'y' 继续审校")
        print("   - 如果需要重新翻译，输入 'n' 退出\n")

        response = input("✅ 是否继续审校？(y/n): ").strip().lower()

        if response in ['y', 'yes', '是']:
            return True
        elif response in ['n', 'no', '否']:
            return False
        else:
            print("⚠️ 请输入 y 或 n")


def save_translated_files(content, base_name):
    """
    保存翻译结果（Markdown、HTML、Word）
    复用 translate_to_word_ds.py 的逻辑
    """
    print("💾 正在保存翻译结果...")

    saved_files = {}

    # 1. 保存 Markdown
    try:
        md_filename = f"{base_name}_translated.md"
        with open(md_filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"   ✅ Markdown: {md_filename}")
        saved_files['markdown'] = md_filename
    except Exception as e:
        print(f"   ❌ Markdown 保存失败: {e}")

    # 2. 保存 HTML
    try:
        _, full_html = convert_to_markdown_and_copy(content)
        html_filename = f"{base_name}_translated.html"
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(full_html)
        print(f"   ✅ HTML: {html_filename}")
        saved_files['html'] = html_filename
    except Exception as e:
        print(f"   ❌ HTML 保存失败: {e}")

    # 3. 保存 Word（使用 Pandoc）
    try:
        word_filename = f"{base_name}_translated.docx"
        pypandoc.convert_text(
            content,
            'docx',
            format='md',
            outputfile=word_filename
        )
        print(f"   ✅ Word: {word_filename}")
        saved_files['word'] = word_filename
    except Exception as e:
        print(f"   ❌ Word 保存失败: {e}")

    return saved_files


def open_word_file(filepath):
    """自动打开 Word 文档"""
    try:
        print(f"\n📖 正在打开: {filepath}")
        if sys.platform == "darwin":
            subprocess.run(["open", filepath], check=True)
        elif sys.platform == "win32":
            os.startfile(filepath)
        else:
            subprocess.run(["xdg-open", filepath], check=True)
        print("✅ 文档已打开")
    except Exception as e:
        print(f"⚠️ 自动打开失败: {e}")


# ==================== 主流程 ====================

def main():
    """主函数"""

    parser = argparse.ArgumentParser(description='翻译+审校一体化工具')
    parser.add_argument('input_file', help='输入文件.txt')
    parser.add_argument('--auto', action='store_true', help='自动模式，无需用户确认')
    args = parser.parse_args()

    input_filepath = args.input_file

    # 转换为绝对路径
    if not os.path.isabs(input_filepath):
        input_filepath = os.path.abspath(input_filepath)

    # 检查文件是否存在
    if not os.path.exists(input_filepath):
        print(f"❌ 错误：文件不存在: {input_filepath}")
        sys.exit(1)

    # 获取基础文件名
    base_name = os.path.splitext(os.path.basename(input_filepath))[0]

    # 检查 Pandoc
    try:
        pypandoc.get_pandoc_version()
    except OSError:
        print("❌ 错误：找不到 Pandoc！")
        print("请安装: brew install pandoc")
        sys.exit(1)

    auto_mode = args.auto
    mode_text = "[自动模式]" if auto_mode else "[手动模式]"
    print_section(f"📚 翻译+审校一体化工具 {mode_text}")
    print(f"输入文件: {input_filepath}")
    print(f"基础名称: {base_name}\n")

    # ==================== 步骤1：读取文件 ====================
    print_section("步骤 1/4: 读取输入文件")

    try:
        with open(input_filepath, 'r', encoding='utf-8') as f:
            original_text = f.read().strip()

        if not original_text:
            print("❌ 错误：文件内容为空")
            sys.exit(1)

        print(f"✅ 成功读取文件")
        print(f"   文件大小: {len(original_text)} 字符")
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        sys.exit(1)

    # ==================== 步骤2：翻译 ====================
    print_section("步骤 2/4: 翻译文本")

    print("🌐 正在调用 DeepSeek API 进行翻译...")
    print("   (这可能需要几分钟，请耐心等待)\n")

    # 调用 main_us.py 同款翻译入口
    translated_content = translator.translate_article(original_text)

    if not translated_content:
        print("❌ 翻译失败")
        sys.exit(1)

    print(f"\n✅ 翻译完成！(输出: {len(translated_content)} 字符)\n")

    # 保存翻译结果
    translated_files = save_translated_files(translated_content, base_name)

    # 自动打开 Word 文档
    if 'word' in translated_files:
        open_word_file(translated_files['word'])

    # ==================== 步骤3：用户确认 ====================
    if not ask_user_confirmation(auto_mode):
        print("\n⏸️  用户取消，程序退出")
        print(f"\n翻译结果已保存:")
        for file_type, filepath in translated_files.items():
            print(f"   - {filepath}")
        print()
        sys.exit(0)

    # ==================== 步骤4：审校 ====================
    print_section("步骤 4/4: 审校翻译内容")

    print("🔍 正在调用 DeepSeek API 进行审校...")
    print("   (这可能需要几分钟，请耐心等待)\n")

    # 直接调用 review_markdown_ds.py 的审校函数
    reviewed_content = review_markdown_content(translated_content)

    if not reviewed_content:
        print("\n❌ 审校失败，但翻译结果已保存")
        sys.exit(1)

    print(f"\n✅ 审校完成！(输出: {len(reviewed_content)} 字符)\n")

    # 保存审校结果（使用 review_markdown_ds.py 的保存函数）
    print("💾 正在保存审校结果...")

    # 创建临时 Markdown 文件用于保存
    temp_md_file = f"{base_name}_temp.md"
    with open(temp_md_file, 'w', encoding='utf-8') as f:
        f.write(reviewed_content)

    # 调用原有的保存函数
    reviewed_md_path = save_reviewed_markdown(reviewed_content, temp_md_file)

    # 删除临时文件
    if os.path.exists(temp_md_file):
        os.remove(temp_md_file)

    # 生成 HTML 和 Word
    try:
        # HTML
        _, full_html = convert_to_markdown_and_copy(reviewed_content)
        reviewed_html = f"{base_name}_reviewed.html"
        with open(reviewed_html, 'w', encoding='utf-8') as f:
            f.write(full_html)
        print(f"   ✅ HTML: {reviewed_html}")

        # Word
        reviewed_word = f"{base_name}_reviewed.docx"
        pypandoc.convert_text(
            reviewed_content,
            'docx',
            format='md',
            outputfile=reviewed_word
        )
        print(f"   ✅ Word: {reviewed_word}")

    except Exception as e:
        print(f"   ⚠️ 部分文件保存失败: {e}")
        reviewed_word = None

    # ==================== 完成 ====================
    print_section("🎉 全部完成！")

    print("📦 生成的文件：\n")
    print("【翻译版本】")
    for file_type, filepath in translated_files.items():
        print(f"   - {filepath}")

    print("\n【审校版本】（推荐使用）")
    if reviewed_md_path:
        print(f"   - {reviewed_md_path}")
    if 'reviewed_html' in locals():
        print(f"   - {reviewed_html}")
    if reviewed_word:
        print(f"   - {reviewed_word}")
        # 自动打开审校后的 Word
        open_word_file(reviewed_word)

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
