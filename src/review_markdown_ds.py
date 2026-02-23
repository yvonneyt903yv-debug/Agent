#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 文档翻译审校工具
输入 markdown 文档名称，使用 deepseek API 进行审校和校验
"""

import os
import sys
import json
import traceback
import re

# 确保能找到 src 目录下的模块
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from src.deepseek import call_deepseek_api


def read_markdown_file(filepath):
    """
    读取 Markdown 文件内容
    
    :param filepath: str, Markdown 文件路径
    :return: str, 文件内容，如果读取失败返回 None
    """
    try:
        if not os.path.exists(filepath):
            print(f"❌ 错误：文件不存在: {filepath}")
            return None
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"✅ 成功读取文件: {filepath} (长度: {len(content)} 字符)")
        return content
    
    except Exception as e:
        print(f"❌ 读取文件时出错: {e}")
        traceback.print_exc()
        return None


def split_text_by_length(text, max_chars=10000):
    """
    如果文本过长，按段落拆分文本，如果单个段落过长则按句子拆分

    :param text: str, 要拆分的文本
    :param max_chars: int, 最大字符数限制
    :return: list, 拆分后的文本块列表
    """
    text_length = len(text)
    print(f"文本总长度: {text_length} 字符")

    # 如果文本长度未超过限制，直接返回原文本
    if text_length <= max_chars:
        print(f"文本长度 {text_length} 未超过 {max_chars} 字符限制，无需���分")
        return [text]

    print(f"文本长度 {text_length} 超过 {max_chars} 字符限制，开始按段落拆分...")

    # 按双换行符（段落分隔）拆分
    paragraphs = text.split('\n\n')
    print(f"文本已拆分为 {len(paragraphs)} 个段落")

    text_chunks = []
    current_chunk = ""
    current_length = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:  # 跳过空段落
            continue

        paragraph_length = len(paragraph)

        # 如果单个段落就超过限制，需要进一步拆分
        if paragraph_length > max_chars:
            print(f"⚠️ 发现超长段落 ({paragraph_length} 字符)，按句子拆分...")

            # 先保存当前块
            if current_chunk:
                text_chunks.append(current_chunk.strip())
                print(f"创建分块 {len(text_chunks)}: {current_length} 字符")
                current_chunk = ""
                current_length = 0

            # 按句子拆分超长段落
            sentences = re.split(r'([。！？\n])', paragraph)
            temp_chunk = ""
            temp_length = 0

            for i in range(0, len(sentences), 2):
                sentence = sentences[i]
                delimiter = sentences[i + 1] if i + 1 < len(sentences) else ""
                full_sentence = sentence + delimiter
                sentence_length = len(full_sentence)

                if temp_length + sentence_length > max_chars and temp_chunk:
                    text_chunks.append(temp_chunk.strip())
                    print(f"创建分块 {len(text_chunks)}: {temp_length} 字符")
                    temp_chunk = full_sentence
                    temp_length = sentence_length
                else:
                    temp_chunk += full_sentence
                    temp_length += sentence_length

            # 保存剩余的句子
            if temp_chunk:
                text_chunks.append(temp_chunk.strip())
                print(f"创建分块 {len(text_chunks)}: {temp_length} 字符")

            continue

        # 如果添加这个段落后会超过限制，先保存当前块
        if current_length + paragraph_length + 2 > max_chars and current_chunk:
            text_chunks.append(current_chunk.strip())
            print(f"创建分块 {len(text_chunks)}: {current_length} 字符")
            current_chunk = paragraph
            current_length = paragraph_length
        else:
            # 添加段落到当前块
            if current_chunk:
                current_chunk += "\n\n" + paragraph
                current_length += paragraph_length + 2  # +2 是换行符的长度
            else:
                current_chunk = paragraph
                current_length = paragraph_length

    # 添加最后一个块
    if current_chunk:
        text_chunks.append(current_chunk.strip())
        print(f"创建分块 {len(text_chunks)}: {current_length} 字符")

    print(f"文本拆分完成，共创建 {len(text_chunks)} 个分块")
    return text_chunks


def review_markdown_content(content):
    """
    使用 deepseek API 审校 Markdown 文档
    
    :param content: str, 要审校的 Markdown 内容
    :return: str, 审校后的内容，如果失败返回 None
    """
    # 审校 prompt
    review_prompt = """你将作为一名专业翻译审校（Translation Reviewer），对以下 Markdown 文档进行审查，确认其是否构成一份完整、准确、格式规范的中文翻译。

请在不改变原意的前提下，直接输出修订后的 Markdown 文档，并重点处理以下常见问题：

1. **遗漏翻译**：如发现仍保留英文原文，请补充对应的完整中文翻译。

2. **冗余说明**：如存在与正文主题无关的翻译解释、注释或元说明性内容，请删除。删除说话人的一些无用的语气词。

3. **格式错误（重要）**：
   - **说话人切换格式**：当对话中说话人发生切换时，必须确保：
     * 每个说话人的标识（如 **说话人**：）必须独占一行
     * 说话人的内容结束后，必须有一个空行（两个换行符）与下一个说话人分隔
     * 若出现对话人切换，请确保该说话内容 作为独立段落存在。
     * 对话人标签（如 姓名：）前必须为空行（或为文档起始），
     * 仅有单行换行但未形成新段落的情况，视为格式错误，必须修正。
     * 正确格式示例：
       ```
       **说话人A**：这是说话人A的内容。

       **说话人B**：这是说话人B的内容。

       **说话人A**：继续的内容。
       ```
   - **段落分隔**：确保不同说话人的内容之间有空行分隔，同一说话人的连续内容可以不分段
   - **换行问题**：如果发现说话人标识和内容在同一行，或两个说话人之间没有空行，必须修正
   - **段落长度要求**：每1-2句话单独成一段。如果某个段落包含3句或更多句子，应将其拆分为多个段落，每个段落包含1-2句话

请勿新增内容、总结或评论，仅输出最终修订结果。

---

以下是待审校的 Markdown 文档：

"""
    
    # 检查内容长度，如果过长需要拆分处理
    text_chunks = split_text_by_length(content, max_chars=10000)
    
    if not text_chunks:
        print("❌ 错误：文本拆分失败")
        return None
    
    reviewed_chunks = []
    
    # 逐个处理每个文本块
    for i, chunk in enumerate(text_chunks, 1):
        print(f"\n--- 正在审校第 {i}/{len(text_chunks)} 块 ---")
        
        # 构建完整的 prompt
        full_prompt = review_prompt + chunk
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"正在调用 deepseek API (尝试 {attempt + 1}/{max_retries})...")
                reviewed_chunk = call_deepseek_api(full_prompt)
                
                if reviewed_chunk and len(reviewed_chunk.strip()) > 10:
                    print(f"✅ 第 {i} 块审校成功 (输出长度: {len(reviewed_chunk)} 字符)")
                    reviewed_chunks.append(reviewed_chunk.strip())
                    break
                else:
                    print(f"⚠️ 审校尝试 {attempt + 1}/{max_retries} 失败：API返回空内容或内容过短。")
                    
            except Exception as e:
                print(f"❌ 审校尝试 {attempt + 1}/{max_retries} 失败，错误: {e}")
                traceback.print_exc()
            
            if attempt < max_retries - 1:
                import time
                wait_time = (attempt + 1) * 2
                print(f"将在 {wait_time} 秒后进行下一次重试...")
                time.sleep(wait_time)
        else:
            print(f"❌ 错误：第 {i} 块在重试 {max_retries} 次后仍然失败，使用原内容")
            reviewed_chunks.append(chunk)
    
    # 合并所有审校后的块
    if reviewed_chunks:
        final_reviewed_content = '\n\n'.join(reviewed_chunks)
        print(f"\n✅ 所有文本块审校完成，合并后总长度: {len(final_reviewed_content)} 字符")
        
        # 进行后处理，确保对话格式正确
        final_reviewed_content = format_dialogue_spacing(final_reviewed_content)
        
        return final_reviewed_content
    else:
        print("❌ 错误：所有文本块审校都失败了。")
        return None


def format_dialogue_spacing(content):
    """
    格式化对话内容，确保说话人切换时有正确的空行分隔
    
    :param content: str, Markdown 内容
    :return: str, 格式化后的内容
    """
    if not content:
        return content
    
    # 匹配说话人格式：**说话人**：或 **说话人**：
    pattern = r'\*\*([^*]+)\*\*[：:]'
    
    lines = content.split('\n')
    formatted_lines = []
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        # 检查是否是说话人标识行
        is_speaker_line = bool(re.match(pattern, line_stripped))
        
        if is_speaker_line:
            # 检查前一行是否为空行或也是说话人
            if formatted_lines:
                prev_line = formatted_lines[-1].strip()
                
                # 如果前一行不为空
                if prev_line:
                    # 检查前一行是否也是说话人标识
                    prev_is_speaker = bool(re.match(pattern, prev_line))
                    
                    if prev_is_speaker:
                        # 前一个也是说话人，需要添加空行分隔
                        formatted_lines.append('')
                    elif not prev_line.endswith('。') and not prev_line.endswith('！') and not prev_line.endswith('？'):
                        # 前一行不是说话人且不以句号结尾，可能是连续对话，也添加空行
                        formatted_lines.append('')
            
            formatted_lines.append(line)
        else:
            # 普通内容行
            formatted_lines.append(line)
    
    result = '\n'.join(formatted_lines)
    
    # 清理多余的空行（将3个或更多连续换行符替换为2个）
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result


def save_reviewed_markdown(content, original_filepath):
    """
    保存审校后的 Markdown 文件
    
    :param content: str, 审校后的内容
    :param original_filepath: str, 原始文件路径
    :return: str, 保存的文件路径，如果失败返回 None
    """
    try:
        # 生成输出文件名（在原名基础上添加 _reviewed）
        directory = os.path.dirname(original_filepath)
        filename = os.path.basename(original_filepath)
        name, ext = os.path.splitext(filename)
        
        # 如果文件名已经包含 _reviewed，则不重复添加
        if name.endswith('_reviewed'):
            output_filename = filename
        else:
            output_filename = f"{name}_reviewed{ext}"
        
        output_filepath = os.path.join(directory, output_filename)
        
        # 保存文件
        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✅ 审校后的文件已保存到: {output_filepath}")
        return output_filepath
    
    except Exception as e:
        print(f"❌ 保存文件时出错: {e}")
        traceback.print_exc()
        return None


def main():
    """主函数"""
    # 获取输入的 markdown 文件名
    if len(sys.argv) < 2:
        print("用法: python review_markdown_ds.py <markdown文件路径>")
        print("示例: python review_markdown_ds.py document.md")
        print("注意: 如果文件名包含空格，请用引号包裹，或者直接传递参数，脚本会自动合并")
        sys.exit(1)
    
    # 合并所有参数（除了脚本名），以处理文件名中包含空格的情况
    input_filepath = ' '.join(sys.argv[1:])
    
    # 如果是相对路径，转换为绝对路径
    if not os.path.isabs(input_filepath):
        input_filepath = os.path.abspath(input_filepath)
    
    print(f"\n{'='*60}")
    print(f"Markdown 文档翻译审校工具")
    print(f"{'='*60}\n")
    print(f"输入文件: {input_filepath}\n")
    
    # 步骤 1: 读取 markdown 文件
    markdown_content = read_markdown_file(input_filepath)
    if not markdown_content:
        print("❌ 无法读取文件，程序退出")
        sys.exit(1)
    
    # 步骤 2: 审校内容
    print(f"\n{'='*60}")
    print("开始审校...")
    print(f"{'='*60}\n")
    
    reviewed_content = review_markdown_content(markdown_content)
    
    if not reviewed_content:
        print("❌ 审校失败，程序退出")
        sys.exit(1)
    
    # 步骤 3: 保存审校后的文件
    print(f"\n{'='*60}")
    print("保存审校结果...")
    print(f"{'='*60}\n")
    
    output_filepath = save_reviewed_markdown(reviewed_content, input_filepath)
    
    if output_filepath:
        print(f"\n{'='*60}")
        print("✅ 审校完成！")
        print(f"{'='*60}")
        print(f"原始文件: {input_filepath}")
        print(f"审校文件: {output_filepath}")
        print(f"{'='*60}\n")
    else:
        print("\n❌ 保存失败，程序退出")
        sys.exit(1)


if __name__ == "__main__":
    main()

