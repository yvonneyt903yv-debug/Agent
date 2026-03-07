import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from src.deepseek import call_deepseek_api


MAX_CHARS = int(os.getenv("TRANSLATE_CHUNK_MAX_CHARS", "8000"))
CHUNK_CONTEXT_TAIL_CHARS = int(os.getenv("TRANSLATE_CONTEXT_TAIL_CHARS", "260"))
# Per user decision: fix concurrency/stagger in code to avoid runtime parameter tuning.
CHUNK_CONCURRENCY = 3
CHUNK_STAGGER_SECONDS = 4.0
CHUNK_RETRY_MAX = max(1, int(os.getenv("TRANSLATE_CHUNK_RETRY_MAX", "3")))
TRANSLATE_MODE_DEFAULT = "auto"
GLOSSARY_ENABLED = os.getenv("TRANSLATE_GLOSSARY_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
GLOSSARY_TIMEOUT_SECONDS = float(os.getenv("TRANSLATE_GLOSSARY_TIMEOUT_SECONDS", "90"))
GLOSSARY_RETRY_MAX = max(1, int(os.getenv("TRANSLATE_GLOSSARY_RETRY_MAX", "2")))
GLOSSARY_BUDGET_SECONDS = float(os.getenv("TRANSLATE_GLOSSARY_BUDGET_SECONDS", "120"))
GLOSSARY_MAX_TOKENS = int(os.getenv("TRANSLATE_GLOSSARY_MAX_TOKENS", "1200"))

_DEFAULT_GLOSSARY: Dict[str, str] = {
    "Singju Post": "Singju Post",
    "Podcast": "播客",
    "Host": "主持人",
}


def split_text_by_length(text: str, max_len: int = MAX_CHARS) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_len
        chunks.append(text[start:end])
        start = end
    return chunks


def _split_long_segment(segment: str, max_len: int) -> List[str]:
    if len(segment) <= max_len:
        return [segment]

    pieces: List[str] = []
    start = 0
    while start < len(segment):
        window_end = min(start + max_len, len(segment))
        window = segment[start:window_end]

        split_pos = max(window.rfind("\n"), window.rfind("。"), window.rfind("."), window.rfind("!"), window.rfind("?"))
        if split_pos <= max_len // 3:
            split_pos = len(window)

        chunk = window[:split_pos].strip()
        if chunk:
            pieces.append(chunk)

        start += split_pos

    return pieces if pieces else split_text_by_length(segment, max_len)


def split_text_by_semantic_boundary(text: str, max_len: int = MAX_CHARS) -> List[Dict[str, str]]:
    """按段落/句子边界分块，并为每块附加前文尾部上下文。"""
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text.strip()) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    raw_chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if not current:
            if len(para) <= max_len:
                current = para
            else:
                raw_chunks.extend(_split_long_segment(para, max_len))
            continue

        candidate = f"{current}\n\n{para}"
        if len(candidate) <= max_len:
            current = candidate
        else:
            raw_chunks.append(current)
            if len(para) <= max_len:
                current = para
            else:
                raw_chunks.extend(_split_long_segment(para, max_len))
                current = ""

    if current:
        raw_chunks.append(current)

    chunk_items: List[Dict[str, str]] = []
    for idx, chunk in enumerate(raw_chunks):
        prev = raw_chunks[idx - 1] if idx > 0 else ""
        context_tail = prev[-CHUNK_CONTEXT_TAIL_CHARS:] if prev else ""
        chunk_items.append({
            "index": idx,
            "text": chunk,
            "context_tail": context_tail,
        })

    return chunk_items


def _extract_json_object(text: str) -> str:
    clean = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", clean, re.DOTALL)
    if fence_match:
        return fence_match.group(1)

    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        return clean[start:end + 1]

    return clean


def _parse_glossary_json(raw: str) -> Dict[str, str]:
    try:
        payload = _extract_json_object(raw)
        data = json.loads(payload)
        if not isinstance(data, dict):
            return {}

        glossary: Dict[str, str] = {}
        for key, value in data.items():
            src = str(key).strip()
            dst = str(value).strip()
            if not src or not dst:
                continue
            if len(src) > 80 or len(dst) > 80:
                continue
            glossary[src] = dst
        return glossary
    except Exception:
        return {}


def extract_glossary(text: str) -> Dict[str, str]:
    if not GLOSSARY_ENABLED or not text.strip():
        return dict(_DEFAULT_GLOSSARY)

    sample = text[:12000]
    start_ts = time.time()
    print(
        f"🧭 术语抽取配置: timeout={GLOSSARY_TIMEOUT_SECONDS}s, "
        f"retries={GLOSSARY_RETRY_MAX}, budget={GLOSSARY_BUDGET_SECONDS}s"
    )
    prompt = f"""
你是一名技术翻译助手。请从下面英文原文中提取需要统一翻译的术语（人名、公司名、产品名、缩写）。

要求：
1. 仅输出 JSON 对象，key 为英文术语，value 为中文译名。
2. 不要输出代码块，不要输出解释。
3. 如果某术语应保留英文，可直接让 value 与 key 相同。
4. 只保留 5-30 个最重要术语。

原文：
{sample}
""".strip()

    try:
        response = call_deepseek_api(
            prompt,
            timeout=GLOSSARY_TIMEOUT_SECONDS,
            max_retries=GLOSSARY_RETRY_MAX,
            retry_delay=2,
            thinking=False,
            max_tokens=GLOSSARY_MAX_TOKENS,
            stream=False,
            temperature=0.2,
            top_p=0.9,
        )
        extracted = _parse_glossary_json(response)
        elapsed = time.time() - start_ts
        if elapsed > GLOSSARY_BUDGET_SECONDS:
            print(f"⚠️ 术语抽取超预算 ({elapsed:.1f}s)，回退默认术语表")
            return dict(_DEFAULT_GLOSSARY)

        merged = dict(_DEFAULT_GLOSSARY)
        merged.update(extracted)
        if not extracted:
            print("⚠️ 术语抽取返回为空，回退默认术语表以继续翻译")
        return merged
    except Exception as exc:
        elapsed = time.time() - start_ts
        print(f"⚠️ 术语抽取失败 ({elapsed:.1f}s)，回退默认术语表: {exc}")
        return dict(_DEFAULT_GLOSSARY)


def _format_glossary(glossary: Dict[str, str]) -> str:
    if not glossary:
        return "- (无)"
    return "\n".join(f"- {k}: {v}" for k, v in glossary.items())


def build_chunk_prompt(
    chunk: str,
    glossary: Dict[str, str],
    context_tail: str,
    chunk_index: int,
    total_chunks: int,
) -> str:
    glossary_block = _format_glossary(glossary)
    context_block = context_tail if context_tail else "(无)"

    return f"""
你是一位专业的中文翻译和内容编辑专家。
请将英文 Markdown 翻译为自然、流畅、适合中文阅读的 Markdown。

这是第 {chunk_index + 1}/{total_chunks} 个分块。

要求：
- 不遗漏信息，不新增评论
- 保留 Markdown 结构
- 删除时间戳
- 对说话人名称加粗
- 严格遵循术语表
- 只翻译“当前分块正文”，不要复述上下文

术语表：
{glossary_block}

上文末尾（仅供理解，不要重复翻译）：
{context_block}

当前分块正文：
{chunk}
""".strip()


def translate_chunk_with_retry(
    chunk: str,
    glossary: Dict[str, str],
    context_tail: str,
    chunk_index: int,
    total_chunks: int,
    max_retries: int = CHUNK_RETRY_MAX,
) -> Dict[str, object]:
    last_error = ""

    for attempt in range(max_retries):
        try:
            prompt = build_chunk_prompt(
                chunk=chunk,
                glossary=glossary,
                context_tail=context_tail,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
            )
            translated = call_deepseek_api(prompt).strip()
            if not translated:
                raise ValueError("empty translation")

            return {
                "index": chunk_index,
                "translated": translated,
                "ok": True,
                "error": "",
            }
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries - 1:
                time.sleep(min(2 ** attempt, 8))

    return {
        "index": chunk_index,
        "translated": "",
        "ok": False,
        "error": last_error,
    }


def _translate_chunks_serial(chunk_items: List[Dict[str, str]], glossary: Dict[str, str]) -> str:
    translated_chunks: List[str] = []
    total_chunks = len(chunk_items)

    for item in chunk_items:
        payload = translate_chunk_with_retry(
            chunk=item["text"],
            glossary=glossary,
            context_tail=item.get("context_tail", ""),
            chunk_index=item["index"],
            total_chunks=total_chunks,
            max_retries=CHUNK_RETRY_MAX,
        )
        if not payload["ok"]:
            raise RuntimeError(f"chunk {item['index']} translate failed: {payload['error']}")
        translated_chunks.append(str(payload["translated"]))

    merged = "\n\n".join(translated_chunks)
    return normalize_terms(merged, glossary)


def translate_article_parallel_chunks(
    text: str,
    max_concurrency: int = CHUNK_CONCURRENCY,
    stagger_sec: float = CHUNK_STAGGER_SECONDS,
    chunk_items: Optional[List[Dict[str, str]]] = None,
    glossary: Optional[Dict[str, str]] = None,
) -> str:
    chunks = chunk_items or split_text_by_semantic_boundary(text, MAX_CHARS)
    if not chunks:
        return ""

    glossary_map = glossary if glossary is not None else extract_glossary(text)
    total_chunks = len(chunks)
    results: Dict[int, str] = {}
    failed: List[int] = []

    with ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as executor:
        futures = []
        for i, item in enumerate(chunks):
            if i > 0 and stagger_sec > 0:
                time.sleep(stagger_sec)

            futures.append(
                executor.submit(
                    translate_chunk_with_retry,
                    item["text"],
                    glossary_map,
                    item.get("context_tail", ""),
                    item["index"],
                    total_chunks,
                    CHUNK_RETRY_MAX,
                )
            )

        for future in as_completed(futures):
            payload = future.result()
            idx = int(payload["index"])
            if payload["ok"]:
                results[idx] = str(payload["translated"])
            else:
                failed.append(idx)

    for idx in sorted(failed):
        item = chunks[idx]
        payload = translate_chunk_with_retry(
            chunk=item["text"],
            glossary=glossary_map,
            context_tail=item.get("context_tail", ""),
            chunk_index=idx,
            total_chunks=total_chunks,
            max_retries=max(CHUNK_RETRY_MAX, 2),
        )
        if not payload["ok"]:
            raise RuntimeError(f"chunk {idx} translate failed: {payload['error']}")
        results[idx] = str(payload["translated"])

    ordered = [results[i] for i in range(total_chunks)]
    merged = "\n\n".join(ordered)
    return normalize_terms(merged, glossary_map)


def normalize_terms(translated_text: str, glossary: Dict[str, str]) -> str:
    if not translated_text or not glossary:
        return translated_text

    normalized = translated_text
    for source, target in glossary.items():
        src = source.strip()
        dst = target.strip()
        if not src or not dst or src == dst:
            continue

        if re.search(r"^[A-Za-z0-9_\-\s\.]+$", src):
            pattern = r"\b" + re.escape(src) + r"\b"
            normalized = re.sub(pattern, dst, normalized)
        else:
            normalized = normalized.replace(src, dst)

    return normalized


def translate_article(text: str) -> str:
    """翻译整篇文章，返回中文 Markdown。"""
    if not text or not text.strip():
        return ""

    mode = os.getenv("TRANSLATE_MODE", TRANSLATE_MODE_DEFAULT).strip().lower()
    chunks = split_text_by_semantic_boundary(text, MAX_CHARS)
    if not chunks:
        return ""

    glossary = extract_glossary(text)

    if mode == "serial":
        return _translate_chunks_serial(chunks, glossary)

    if mode == "parallel_chunks":
        return translate_article_parallel_chunks(
            text=text,
            max_concurrency=CHUNK_CONCURRENCY,
            stagger_sec=CHUNK_STAGGER_SECONDS,
            chunk_items=chunks,
            glossary=glossary,
        )

    # auto mode
    if len(chunks) <= 1:
        return _translate_chunks_serial(chunks, glossary)

    try:
        return translate_article_parallel_chunks(
            text=text,
            max_concurrency=CHUNK_CONCURRENCY,
            stagger_sec=CHUNK_STAGGER_SECONDS,
            chunk_items=chunks,
            glossary=glossary,
        )
    except Exception as exc:
        print(f"⚠️ 并发翻译失败，自动降级串行: {exc}")
        return _translate_chunks_serial(chunks, glossary)
