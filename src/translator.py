from typing import List

from src.deepseek import call_deepseek_api


MAX_CHARS = 8000


def split_text_by_length(text: str, max_len: int = MAX_CHARS) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_len
        chunks.append(text[start:end])
        start = end
    return chunks


def _create_name_glossary() -> str:
    """
    保留你原来的姓名 / 术语对照表逻辑
    """
    return """
    专有名词翻译规范：
    - Singju Post：Singju Post
    - Podcast：播客
    - Host：主持人
    """


def _build_translation_prompt(text: str) -> str:
    glossary = _create_name_glossary()
    return f"""
你是一位专业的中文翻译和内容编辑专家。
请将以下英文 Markdown 翻译为**自然、流畅、适合中文阅读的 Markdown**。

要求：
- 不遗漏内容
- 不保留英文
- 保留 Markdown 结构
- 删除时间戳
- 对说话人名称加粗
- 不要新增总结或评论

{glossary}

正文如下：
{text}
""".strip()


def translate_article(text: str) -> str:
    """
    翻译整篇文章，返回中文 Markdown
    """
    chunks = split_text_by_length(text)
    translated_chunks = []

    for chunk in chunks:
        prompt = _build_translation_prompt(chunk)
        translated = call_deepseek_api(prompt)
        translated_chunks.append(translated)

    return "\n\n".join(translated_chunks)
