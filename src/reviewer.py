import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from src.deepseek import call_deepseek_api
from src.review_markdown_ds import split_text_by_length, format_dialogue_spacing


REVIEW_CHUNK_MAX_CHARS = int(os.getenv("REVIEW_CHUNK_MAX_CHARS", "10000"))
REVIEW_CONCURRENCY = max(1, int(os.getenv("REVIEW_CONCURRENCY", "3")))
REVIEW_STAGGER_SECONDS = float(os.getenv("REVIEW_STAGGER_SECONDS", "2.0"))
REVIEW_RETRY_MAX = max(1, int(os.getenv("REVIEW_RETRY_MAX", "3")))
REVIEW_MODE_DEFAULT = "auto"


REVIEW_PROMPT = """你将作为一名专业翻译审校（Translation Reviewer），对以下 Markdown 文档进行审查，确认其是否构成一份完整、准确、格式规范的中文翻译。

请在不改变原意的前提下，直接输出修订后的 Markdown 文档，并重点处理以下常见问题：

1. **遗漏翻译**：如发现仍保留英文原文，请补充对应的完整中文翻译。
2. **冗余说明**：如存在与正文主题无关的翻译解释、注释或元说明性内容，请删除。删除说话人的一些无用的语气词。
3. **格式错误（重要）**：
   - 说话人切换时，每个说话人标识（如 **说话人**：）必须独占一行。
   - 说话人内容结束后，必须有空行与下一个说话人分隔。
   - 段落尽量控制在每 1-2 句。

请勿新增内容、总结或评论，仅输出最终修订结果。

以下是待审校的 Markdown 文档：
"""


def _build_review_prompt(chunk: str) -> str:
    return f"{REVIEW_PROMPT}\n\n{chunk}"


def _review_chunk_with_retry(chunk: str, chunk_index: int, total_chunks: int, max_retries: int) -> Dict[str, object]:
    last_error = ""
    full_prompt = _build_review_prompt(chunk)

    for attempt in range(max_retries):
        try:
            print(f"🧪 审校分块 {chunk_index + 1}/{total_chunks}，尝试 {attempt + 1}/{max_retries}")
            reviewed = call_deepseek_api(full_prompt).strip()
            if len(reviewed) < 10:
                raise ValueError("review result too short")
            return {"index": chunk_index, "ok": True, "reviewed": reviewed, "error": ""}
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries - 1:
                time.sleep(min(2 ** attempt, 8))

    return {"index": chunk_index, "ok": False, "reviewed": chunk, "error": last_error}


def _review_chunks_serial(chunks: List[str], max_retries: int) -> str:
    reviewed_chunks: List[str] = []
    total = len(chunks)
    for idx, chunk in enumerate(chunks):
        payload = _review_chunk_with_retry(chunk, idx, total, max_retries)
        if not payload["ok"]:
            print(f"⚠️ 分块 {idx + 1} 审校失败，回退原文: {payload['error']}")
        reviewed_chunks.append(str(payload["reviewed"]))
    return "\n\n".join(reviewed_chunks)


def _review_chunks_parallel(chunks: List[str], max_concurrency: int, stagger_sec: float, max_retries: int) -> str:
    total = len(chunks)
    results: Dict[int, str] = {}
    failed_indices: List[int] = []

    with ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as executor:
        futures = []
        for idx, chunk in enumerate(chunks):
            if idx > 0 and stagger_sec > 0:
                time.sleep(stagger_sec)
            futures.append(executor.submit(_review_chunk_with_retry, chunk, idx, total, max_retries))

        for future in as_completed(futures):
            payload = future.result()
            idx = int(payload["index"])
            results[idx] = str(payload["reviewed"])
            if not payload["ok"]:
                failed_indices.append(idx)

    for idx in sorted(failed_indices):
        print(f"🔁 分块 {idx + 1} 并发失败，串行补偿重试")
        payload = _review_chunk_with_retry(chunks[idx], idx, total, max(max_retries, 2))
        results[idx] = str(payload["reviewed"])

    ordered = [results[i] for i in range(total)]
    return "\n\n".join(ordered)


def review_article(text: str) -> str:
    """对外暴露的审校函数：支持 serial / parallel_chunks / auto。"""
    if not text:
        return "错误：输入文本为空"

    chunks = split_text_by_length(text, max_chars=REVIEW_CHUNK_MAX_CHARS)
    if not chunks:
        return text

    mode = os.getenv("REVIEW_MODE", REVIEW_MODE_DEFAULT).strip().lower()
    if mode == "serial":
        reviewed = _review_chunks_serial(chunks, REVIEW_RETRY_MAX)
    elif mode == "parallel_chunks":
        reviewed = _review_chunks_parallel(chunks, REVIEW_CONCURRENCY, REVIEW_STAGGER_SECONDS, REVIEW_RETRY_MAX)
    else:
        if len(chunks) <= 1:
            reviewed = _review_chunks_serial(chunks, REVIEW_RETRY_MAX)
        else:
            try:
                reviewed = _review_chunks_parallel(
                    chunks,
                    REVIEW_CONCURRENCY,
                    REVIEW_STAGGER_SECONDS,
                    REVIEW_RETRY_MAX,
                )
            except Exception as exc:
                print(f"⚠️ 并发审校失败，回退串行: {exc}")
                reviewed = _review_chunks_serial(chunks, REVIEW_RETRY_MAX)

    return format_dialogue_spacing(reviewed) if reviewed else text
