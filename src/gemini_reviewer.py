#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 审核模块 - 发布前对 Markdown 进行编辑审核

功能：
1. 格式优化（标题层级、段落间距、列表格式）
2. 去除无关内容（导航、页脚、广告、分享按钮等）
3. 清理微信不支持的 Markdown 格式（加粗、斜体）
"""

import re
import time
from openai import OpenAI

# 从 gemini_brain 导入统一配置
from gemini_brain import API_KEY, BASE_URL, MODEL_NAME

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

REVIEW_SYSTEM_PROMPT = """你是一位专业的微信公众号编辑，负责审核和优化 Markdown 文章内容。

请对以下 Markdown 文档进行编辑审核，直接输出修订后的 Markdown：

## 审核要点

### 1. 去除无关内容（必须严格执行）
- 删除网页导航元素（如 "返回首页"、"上一篇/下一篇"、"目录"、"跳转到"）
- 删除页脚信息（如版权声明、联系方式、订阅提示、免责声明）
- 删除广告内容和推广链接
- 删除社交分享按钮文字（如 "分享到微博"、"转发"、"点赞"）
- 删除评论区提示（如 "发表评论"、"查看更多评论"）
- 删除与正文无关的元数据（如 "阅读量"、"点赞数"、"浏览次数"）
- 删除网站导航菜单和侧边栏内容
- 删除 "关于我们"、"联系我们" 等页面链接
- 删除 Cookie 提示和隐私政策链接
- 删除 "更多信息可在此处查阅"、"点击此处了解更多" 等引导性链接文字
- 删除 "更多信息将在适当时候发布"、"敬请期待" 等预告性文字
- 删除 "相关阅读"、"推荐阅读"、"Related news" 等推荐内容
- 删除任何 CSS 样式代码（如 .preview-wrapper, .hljs, font-size 等）
- 删除任何 HTML 标签残留
- 删除媒体联系人信息（如 "Media contacts"、联系电话、邮箱）
- 删除文末的公司简介模板（如 "关于皇家飞利浦" 等标准介绍段落）

### 2. 格式优化
- 确保标题层级合理（h1 用于主标题，h2/h3 用于章节）
- 段落之间保持适当空行
- 列表格式统一（无序列表用 -，有序列表用数字）
- 代码块标注正确的语言类型
- 图片保留 alt 文本和标题
- 删除无效链接（如 "此处"、"这里" 等指向不明的链接）
- 重要：移除正文中的加粗语法（**text** 改为 text），因为微信公众号不支持 Markdown 加粗
- 移除正文中的斜体语法（*text* 或 _text_ 改为 text）
- 保留标题的 # 语法，但正文不要使用 ** 或 * 等格式标记

### 3. 内容完整性
- 保留所有正文内容，不要删除或修改原文观点
- 保留引用和脚注
- 保留表格数据
- 保留图片（包括占位符如 [[IMAGE_PLACEHOLDER_1]]）

## 输出要求
- 只输出修订后的 Markdown，不要添加任何解释或评论
- 保持原文的语言风格
- 如果内容已经很规范，可以原样输出
- 不要添加 ```markdown 代码块包裹"""


def split_text_by_length(text, max_chars=8000):
    """
    按长度分割文本，尽量在段落边界处分割
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current_chunk = ""
    paragraphs = text.split('\n\n')

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= max_chars:
            current_chunk += para + '\n\n'
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            if len(para) > max_chars:
                # 段落本身太长，强制分割
                for i in range(0, len(para), max_chars):
                    chunks.append(para[i:i + max_chars])
                current_chunk = ""
            else:
                current_chunk = para + '\n\n'

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def clean_markdown_formatting(text):
    """
    清理微信不支持的 Markdown 格式标记

    处理：
    - **text** 加粗 -> text
    - *text* 或 _text_ 斜体 -> text
    - 保留标题 # 和列表 - 等基本格式
    """
    # 移除加粗 **text** 或 __text__
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)

    # 移除斜体 *text* 或 _text_（但不影响列表项的 * 或文件名中的 _）
    # 只匹配被空格或标点包围的斜体标记
    text = re.sub(r'(?<![*\w])\*([^*\n]+)\*(?![*\w])', r'\1', text)
    text = re.sub(r'(?<![_\w])_([^_\n]+)_(?![_\w])', r'\1', text)

    return text


def review_markdown_for_wechat(markdown_content: str, max_retries: int = 3) -> str:
    """
    使用 Gemini 对 Markdown 进行编辑审核

    参数:
        markdown_content: 原始 Markdown 内容
        max_retries: 每个分段的最大重试次数

    返回:
        审核后的 Markdown 内容
    """
    chunks = split_text_by_length(markdown_content, max_chars=8000)
    reviewed_chunks = []

    print(f"  📝 开始 Gemini 审核，共 {len(chunks)} 个分段...")

    for i, chunk in enumerate(chunks, 1):
        print(f"  ...正在审核第 {i}/{len(chunks)} 部分...")

        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": chunk},
                    ],
                    stream=False,
                    temperature=0.1
                )

                reviewed_chunk = response.choices[0].message.content
                if reviewed_chunk:
                    # 去除可能的 markdown 代码块包裹
                    reviewed_chunk = reviewed_chunk.strip()
                    if reviewed_chunk.startswith('```markdown'):
                        reviewed_chunk = reviewed_chunk[11:]
                    if reviewed_chunk.startswith('```'):
                        reviewed_chunk = reviewed_chunk[3:]
                    if reviewed_chunk.endswith('```'):
                        reviewed_chunk = reviewed_chunk[:-3]
                    reviewed_chunks.append(reviewed_chunk.strip())
                    break
            except Exception as e:
                print(f"    ⚠️ 审核失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                # API 令牌额度耗尽时无需重复重试，直接保留原文
                if "TokenStatusExhausted" in str(e):
                    print("    ⚠️ 检测到令牌额度已用尽，跳过后续重试")
                    break
                time.sleep(3)
        else:
            print(f"    ❌ 第 {i} 部分审核失败，保留原文")
            reviewed_chunks.append(chunk)
            continue

        # 额度耗尽场景会提前 break 到这里，仍需保留原文
        if len(reviewed_chunks) < i:
            print(f"    ❌ 第 {i} 部分审核失败，保留原文")
            reviewed_chunks.append(chunk)

        # 避免 API 限流
        if i < len(chunks):
            time.sleep(1)

    result = '\n\n'.join(reviewed_chunks)

    # 最终清理：移除残留的 Markdown 格式标记
    result = clean_markdown_formatting(result)

    print(f"  ✅ Gemini 审核完成")
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python gemini_reviewer.py <markdown文件>")
        print("示例: python gemini_reviewer.py article.md")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = input_file.replace('.md', '_reviewed.md')

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"📝 正在审核: {input_file}")
    reviewed = review_markdown_for_wechat(content)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(reviewed)

    print(f"✅ 审核完成: {output_file}")
