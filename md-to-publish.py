#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gps.publisher.minimax import MiniMaxClient
from gps.publisher.publish_run import detect_title, fallback_copy, run_publish
from src.notebook_tool import DEFAULT_SUMMARY_PROMPT, NotebookSkill, SummaryResult


SUMMARY_HEADING = "## 【NotebookLM 智能总结】"
INSERT_BEFORE_HEADINGS = (
    "## 【Gemini 结构化分析】",
    "## 【核心要点】",
    "## 【相关播客】",
    "## 【正文实录】",
    "### 相关文章",
    "## 【英文原文】",
)
PUBLISH_CLEAN = PROJECT_ROOT / "gps/publisher/publish_clean.py"
WECHAT_PUBLISHER = Path("/Users/yvonne/Documents/publish_to_wechat_ds.py")


def derive_merged_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_publish_source.md")


def derive_publish_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_publish.md")


def normalize_text_block(text: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    normalized: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip():
            blank_count = 0
            normalized.append(line)
        else:
            blank_count += 1
            if blank_count <= 1:
                normalized.append("")
    return "\n".join(normalized).strip()


def build_summary_section(summary_text: str) -> str:
    body = normalize_text_block(summary_text)
    return f"{SUMMARY_HEADING}\n\n{body}\n"


def replace_existing_summary_block(markdown_text: str, summary_section: str) -> str:
    lines = markdown_text.splitlines()
    start_idx: int | None = None
    end_idx: int | None = None

    for idx, line in enumerate(lines):
        if line.strip() == SUMMARY_HEADING:
            start_idx = idx
            end_idx = len(lines)
            for next_idx in range(idx + 1, len(lines)):
                stripped = lines[next_idx].strip()
                if stripped.startswith("## ") and stripped != SUMMARY_HEADING:
                    end_idx = next_idx
                    break
            break

    if start_idx is None or end_idx is None:
        return markdown_text

    replacement_lines = summary_section.rstrip("\n").splitlines()
    merged_lines = lines[:start_idx] + replacement_lines + [""] + lines[end_idx:]
    return "\n".join(merged_lines).strip() + "\n"


def insert_summary_block(markdown_text: str, summary_section: str) -> str:
    if SUMMARY_HEADING in markdown_text:
        return replace_existing_summary_block(markdown_text, summary_section)

    candidate_positions: list[int] = []
    for heading in INSERT_BEFORE_HEADINGS:
        marker = f"\n{heading}"
        idx = markdown_text.find(marker)
        if idx >= 0:
            candidate_positions.append(idx + 1)

    first_h2 = markdown_text.find("\n## ")
    if first_h2 >= 0:
        candidate_positions.append(first_h2 + 1)

    insert_at = min(candidate_positions) if candidate_positions else len(markdown_text)

    prefix = markdown_text[:insert_at].rstrip()
    suffix = markdown_text[insert_at:].lstrip()
    if prefix:
        return f"{prefix}\n\n{summary_section}\n{suffix}".strip() + "\n"
    return f"{summary_section}\n{suffix}".strip() + "\n"


async def generate_summary(
    input_path: Path,
    prompt: str,
    summary_output: str | None,
    notebook_title: str | None,
) -> SummaryResult:
    async with NotebookSkill() as skill:
        return await skill.summarize_document_to_output(
            file_path=str(input_path),
            prompt=prompt,
            output_path=summary_output,
            notebook_title=notebook_title,
        )


def merge_summary_into_markdown(
    input_path: Path,
    merged_output_path: Path,
    summary_text: str,
) -> Path:
    original_text = input_path.read_text(encoding="utf-8")
    summary_section = build_summary_section(summary_text)
    merged_text = insert_summary_block(original_text, summary_section)
    merged_output_path.write_text(merged_text, encoding="utf-8")
    return merged_output_path


def run_publish_clean(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(PUBLISH_CLEAN), *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def run_publisher_without_llm(
    merged_path: Path,
    publish_output_path: Path,
) -> dict[str, object]:
    merged_text = merged_path.read_text(encoding="utf-8")
    title = detect_title(merged_text, merged_path.stem)
    copy = fallback_copy(title)

    run_publish_clean(
        "--input", str(merged_path),
        "--output", str(publish_output_path),
        "--mode", "publish-format",
        "--title", str(copy["title"]),
        "--person-intro", str(copy["person_intro"]),
        "--hook", str(copy["hook"]),
    )
    review = run_publish_clean(
        "--input", str(publish_output_path),
        "--output", str(publish_output_path),
        "--mode", "review-names",
    )
    return {
        "ok": True,
        "input": str(merged_path),
        "output": str(publish_output_path),
        "name_review": review.stdout.strip().splitlines(),
        "used_llm_rewrite": False,
    }


def maybe_publish(final_markdown: Path) -> int:
    answer = input("是否需要发布到公众号？输入 y 发布，其他任意键终止: ").strip().lower()
    if answer != "y":
        print("已终止发布。")
        return 0

    if not WECHAT_PUBLISHER.exists():
        raise FileNotFoundError(f"Publish script not found: {WECHAT_PUBLISHER}")

    cmd = [sys.executable, str(WECHAT_PUBLISHER), str(final_markdown)]
    print(f"正在调用发布脚本: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print("发布完成。")
    else:
        print(f"发布失败，退出码: {result.returncode}")
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="调用 NotebookLM 总结现有 Markdown，合并后交给 publisher，再按确认决定是否发布",
    )
    parser.add_argument("input", help="原始 markdown 文件路径")
    parser.add_argument("--merged-output", help="合并总结后的中间 markdown 输出路径")
    parser.add_argument("--publish-output", help="publisher 最终输出路径")
    parser.add_argument("--summary-output", help="NotebookLM 标准总结输出文件路径或目录")
    parser.add_argument("--title", help="NotebookLM 笔记本标题")
    parser.add_argument("--prompt", default=DEFAULT_SUMMARY_PROMPT, help="NotebookLM 总结提示词")
    parser.add_argument("--summary-text", help="可选：直接提供总结文本，跳过 NotebookLM 调用")
    parser.add_argument("--skip-publisher", action="store_true", help="只生成合并后的 markdown，不运行 publisher")
    parser.add_argument("--max-chars", type=int, default=50000, help="publisher 最大输出字符数")
    parser.add_argument("--minimax-api-key", help="可选：覆盖 MINIMAX_API_KEY")
    parser.add_argument("--minimax-api-url", help="可选：覆盖 MINIMAX_API_URL")
    parser.add_argument("--minimax-model", help="可选：覆盖 MINIMAX_MODEL")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    if input_path.suffix.lower() != ".md":
        raise ValueError(f"Only markdown input is supported: {input_path}")

    merged_output_path = (
        Path(args.merged_output).expanduser().resolve()
        if args.merged_output
        else derive_merged_output_path(input_path)
    )
    publish_output_path = (
        Path(args.publish_output).expanduser().resolve()
        if args.publish_output
        else derive_publish_output_path(input_path)
    )

    summary_result: SummaryResult | None = None
    summary_text = args.summary_text
    if not summary_text:
        summary_result = asyncio.run(
            generate_summary(
                input_path=input_path,
                prompt=args.prompt,
                summary_output=args.summary_output,
                notebook_title=args.title,
            )
        )
        summary_text = summary_result.summary_text

    merged_path = merge_summary_into_markdown(
        input_path=input_path,
        merged_output_path=merged_output_path,
        summary_text=summary_text,
    )

    print(f"MERGED_MARKDOWN: {merged_path}")
    if summary_result:
        print(f"NOTEBOOKLM_OUTPUT: {summary_result.output_path}")

    if args.skip_publisher:
        return

    minimax_client = MiniMaxClient(
        api_key=args.minimax_api_key,
        api_url=args.minimax_api_url,
        model=args.minimax_model,
    )
    if minimax_client.configured():
        publish_result = run_publish(
            input_path=str(merged_path),
            output_path=str(publish_output_path),
            max_chars=args.max_chars,
            api_key=args.minimax_api_key,
            api_url=args.minimax_api_url,
            model=args.minimax_model,
        )
    else:
        publish_result = run_publisher_without_llm(
            merged_path=merged_path,
            publish_output_path=publish_output_path,
        )

    final_output = Path(str(publish_result["output"])).resolve()
    print(f"PUBLISH_OUTPUT: {final_output}")
    raise SystemExit(maybe_publish(final_output))


if __name__ == "__main__":
    main()
