#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 转微信公众号 HTML（使用 premailer 内联样式）

功能：
1. 使用 markdown2 将 Markdown 转换为 HTML
2. 使用 premailer 将 CSS 转换为内联样式
3. 生成微信公众号兼容的 HTML

依赖安装：
    pip install markdown2 premailer
"""

import sys
import markdown2
from premailer import transform

# 微信公众号样式（用户自定义样式）
WECHAT_CSS = """
/* 全局属性 */
body {
    padding: 10px;
    font-family: Optima-Regular, -apple-system-font, BlinkMacSystemFont, Helvetica Neue, PingFang SC, Hiragino Sans GB, Microsoft YaHei UI, Microsoft YaHei, Arial, sans-serif;
    word-break: break-all;
    font-size: 16px;
    line-height: 1.75;
    color: #3e3e3e;
}

/* 段落样式 */
p {
    margin-top: 5px;
    margin-bottom: 5px;
    line-height: 26px;
    word-spacing: 3px;
    letter-spacing: 3px;
    text-align: left;
    color: #3e3e3e;
    font-size: 17px;
    text-indent: 0em;
}

/* 一级标题 */
h1 {
    color: rgb(89, 89, 89);
    font-size: 24px;
    margin-top: 1em;
    margin-bottom: 0.5em;
    font-weight: bold;
}

/* 二级标题 */
h2 {
    border-bottom: 2px solid rgb(89, 89, 89);
    margin-bottom: 5px;
    margin-top: 1.5em;
    color: rgb(89, 89, 89);
    font-size: 22px;
    padding-bottom: 5px;
}

/* 三级标题 */
h3 {
    color: rgb(89, 89, 89);
    font-size: 19px;
    margin-top: 1.2em;
    margin-bottom: 0.5em;
}

/* 四级标题 */
h4 {
    color: rgb(89, 89, 89);
    font-size: 18px;
    margin-top: 1em;
    margin-bottom: 0.5em;
}

/* 引用 */
blockquote {
    font-style: normal;
    padding: 10px 15px;
    position: relative;
    line-height: 1.8;
    text-indent: 0;
    border: none;
    color: #888;
    background: #f7f7f7;
    margin: 1em 0;
}

blockquote p {
    color: #888;
    font-size: 16px;
}

/* 链接 */
a {
    color: rgb(71, 193, 168);
    border-bottom: 1px solid rgb(71, 193, 168);
    text-decoration: none;
}

/* 加粗 */
strong {
    color: rgb(89, 89, 89);
    font-weight: bold;
}

/* 斜体 */
em {
    color: rgb(71, 193, 168);
    font-style: italic;
}

/* 行内代码 */
code {
    color: rgb(71, 193, 168);
    background: #f5f5f5;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 90%;
}

/* 代码块 */
pre {
    background: #f5f5f5;
    padding: 15px;
    border-radius: 5px;
    overflow-x: auto;
    font-size: 14px;
    line-height: 1.5;
}

pre code {
    background: none;
    padding: 0;
    color: #333;
}

/* 无序列表 */
ul {
    padding-left: 1.5em;
    list-style: disc;
}

/* 有序列表 */
ol {
    padding-left: 1.5em;
}

/* 列表项 */
li {
    margin: 0.5em 0;
    line-height: 1.8;
    color: #3e3e3e;
}

/* 表格 */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}

th, td {
    font-size: 16px;
    border: 1px solid #ccc;
    padding: 5px 10px;
    text-align: left;
}

th {
    background: #f5f5f5;
    font-weight: bold;
}

/* 分割线 */
hr {
    height: 1px;
    border: none;
    margin: 2em 0;
    background: linear-gradient(to right, rgba(0, 0, 0, 0), rgba(0, 0, 0, 0.2), rgba(0, 0, 0, 0));
}

/* 图片 */
img {
    max-width: 100%;
    border-radius: 4px;
    margin: 1em 0;
}

/* 图片说明 */
figcaption {
    text-align: center;
    color: #888;
    font-size: 14px;
    margin-top: 5px;
}
"""


def markdown_to_wechat_html(markdown_content: str) -> str:
    """
    将 Markdown 转换为微信公众号兼容的 HTML（带内联样式）

    参数:
        markdown_content: Markdown 内容

    返回:
        带内联样式的 HTML
    """
    # 使用 markdown2 转换，启用常用扩展
    html = markdown2.markdown(
        markdown_content,
        extras=[
            'fenced-code-blocks',
            'tables',
            'strike',
            'task_list',
            'footnotes',
            'header-ids',
            'code-friendly',
        ]
    )

    # 构建完整 HTML 文档
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>{WECHAT_CSS}</style>
</head>
<body>
    <div id="output">{html}</div>
</body>
</html>"""

    # 使用 premailer 将 CSS 转换为内联样式
    inlined_html = transform(
        full_html,
        remove_classes=True,
        strip_important=True,
        keep_style_tags=False,
    )

    return inlined_html


def extract_output_content(html: str) -> str:
    """
    从完整 HTML 中提取 #output 内容（用于直接注入编辑器）
    """
    import re
    match = re.search(r'<div id="output"[^>]*>([\s\S]*?)</div>\s*</body>', html)
    if match:
        return match.group(1).strip()
    return html


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python md_to_html_premailer.py <markdown文件>")
        print("示例: python md_to_html_premailer.py article.md")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = input_file.replace('.md', '.html')

    with open(input_file, 'r', encoding='utf-8') as f:
        md_content = f.read()

    print(f"📄 正在转换: {input_file}")
    html = markdown_to_wechat_html(md_content)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ 转换完成: {output_file}")
