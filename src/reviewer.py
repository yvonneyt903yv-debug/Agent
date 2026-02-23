import os
import sys

# 添加脚本所在目录到路径，以便导入 review_markdown_ds
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)

from review_markdown_ds import split_text_by_length, review_markdown_content, format_dialogue_spacing


def review_article(text: str) -> str:
    """
    对外暴露的审校函数。
    接收翻译后的文本，返回审校后的文本。
    """
    if not text:
        return "错误：输入文本为空"

    # 直接调用 review_markdown_ds 中的审校函数
    reviewed_content = review_markdown_content(text)
    
    if reviewed_content:
        return reviewed_content
    else:
        return text  # 如果审校失败，返回原文