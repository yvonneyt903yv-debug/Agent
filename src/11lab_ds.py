#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 DeepSeek 将文本转换为 ElevenLabs 语音格式
支持 Markdown、TXT、Word 文件
"""

import os
import sys
import time
import traceback
from openai import OpenAI

# ================= 配置区 =================
BASE_URL = "https://integrate.api.nvidia.com/v1"
API_KEY = "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"
MODEL_NAME = "deepseek-ai/deepseek-v3.2"


def read_file(filepath):
    """
    读取文件内容，支持 .md, .txt, .docx
    """
    if not os.path.exists(filepath):
        print(f"错误：文件不存在: {filepath}")
        return None

    ext = os.path.splitext(filepath)[1].lower()

    try:
        if ext in ['.md', '.txt']:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()

        elif ext == '.docx':
            try:
                from docx import Document
            except ImportError:
                print("错误：请先安装 python-docx: pip install python-docx")
                return None

            doc = Document(filepath)
            paragraphs = [p.text for p in doc.paragraphs]
            return '\n\n'.join(paragraphs)

        else:
            print(f"错误：不支持的文件格式: {ext}")
            return None

    except Exception as e:
        print(f"读取文件出错: {e}")
        traceback.print_exc()
        return None


def split_text(text, max_chars=6000):
    """
    按段落拆分长文本
    """
    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split('\n\n')
    chunks = []
    current = ""

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue

        if len(current) + len(p) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = p
        else:
            current = current + "\n\n" + p if current else p

    if current:
        chunks.append(current.strip())

    return chunks


def call_deepseek(content, max_retries=3):
    """
    调用 DeepSeek API
    """
    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout=300,
    )

    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": content}],
                temperature=0.5,
                top_p=0.95,
                max_tokens=8192,
                stream=True,
            )

            full_content = ""
            for chunk in completion:
                if chunk.choices[0].delta.content:
                    full_content += chunk.choices[0].delta.content

            if full_content:
                return full_content.strip()
            else:
                raise ValueError("API 返回空内容")

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 10 * (attempt + 1)
                print(f"  API 调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                print(f"  {wait_time}秒后重试...")
                time.sleep(wait_time)
            else:
                raise e

    return None


def convert_to_elevenlabs(text):
    """
    使用 DeepSeek 将文本转换为 ElevenLabs 格式
    """
    prompt = """请将以下文本转换为适合 ElevenLabs 文本转语音的格式。

转换规则：
1. 移除所有 Markdown 格式（**加粗**、*斜体*、# 标题、- 列表等）
2. 说话人标识改为纯文本，如「张三：」而非「**张三**：」
3. 数字转为口语形式（如 "3个" 改为 "三个"，"100%" 改为 "百分之一百"）
4. 移除特殊符号（emoji、→、★、| 等）
5. 保留标点符号控制语音停顿
6. 每1-2句话一个段落，便于语音节奏
7. 链接和 URL 直接删除或改为"相关链接"
8. 代码块内容简化描述或删除

只输出转换后的纯文本，不要任何解释。

---

待转换文本：

"""

    chunks = split_text(text, max_chars=6000)
    results = []

    for i, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            print(f"  处理第 {i}/{len(chunks)} 部分...")

        try:
            result = call_deepseek(prompt + chunk)
            if result:
                results.append(result)
            else:
                print(f"  警告：第 {i} 部分返回空内容，保留原文")
                results.append(chunk)

        except Exception as e:
            print(f"  错误：第 {i} 部分处理失败: {e}")
            results.append(chunk)

        # 防止 API 限流
        if i < len(chunks):
            time.sleep(2)

    return '\n\n'.join(results)


def save_output(content, original_path):
    """
    保存输出文件
    """
    directory = os.path.dirname(original_path)
    filename = os.path.basename(original_path)
    name, _ = os.path.splitext(filename)

    output_path = os.path.join(directory, f"{name}_elevenlabs.txt")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return output_path


def main():
    # 确保输出实时刷新
    sys.stdout.reconfigure(line_buffering=True)

    if len(sys.argv) < 2:
        print("用法: python 11lab_ds.py <文件路径>")
        print("支持格式: .md, .txt, .docx")
        sys.exit(1)

    filepath = ' '.join(sys.argv[1:])
    if not os.path.isabs(filepath):
        filepath = os.path.abspath(filepath)

    print(f"\n{'='*50}")
    print("ElevenLabs 格式转换工具 (DeepSeek)")
    print(f"{'='*50}\n")
    print(f"输入文件: {filepath}\n")

    # 读取文件
    content = read_file(filepath)
    if not content:
        sys.exit(1)

    print(f"文件长度: {len(content)} 字符\n")

    # 转换
    print("开始转换...")
    result = convert_to_elevenlabs(content)

    if not result:
        print("转换失败")
        sys.exit(1)

    # 保存
    output_path = save_output(result, filepath)
    print(f"\n转换完成！")
    print(f"输出文件: {output_path}")


if __name__ == "__main__":
    main()
