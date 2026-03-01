#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

DROP_HEADINGS = {
    "## 【Gemini 结构化分析】",
    "## 【NotebookLM 智能总结】",
    "## 【被访者简介】",
    "## 【核心要点】",
    "## 【相关播客】",
    "## 【正文实录】",
}
TAIL_CUT_HEADINGS = {
    "### 相关文章",
    "## 【英文原文】",
}

NOISE_LINE_RE = re.compile(
    r"(另请阅读|相关阅读|ALSO READ|Read More|"
    r"\[[^\]]*(另请阅读|ALSO READ|Read More|相关阅读)[^\]]*\]\([^)]*\))",
    re.IGNORECASE,
)


def derive_output_path(inp: Path) -> Path:
    if inp.suffix.lower() == ".md":
        return inp.with_name(f"{inp.stem}_publish.md")
    return inp.with_name(f"{inp.name}_publish.md")


def normalize_spacing(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    blank = 0
    for line in lines:
        if line.strip():
            blank = 0
            out.append(line.rstrip())
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    return "\n".join(out).strip() + "\n"


def parse_pipe_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split("||") if part.strip()]


def remove_noise_blocks_with_dynamic(
    text: str,
    extra_drop_exact: list[str],
    extra_drop_prefix: list[str],
    tail_cut_exact: list[str],
) -> str:
    lines = text.splitlines()
    drop_exact = set(DROP_HEADINGS) | set(extra_drop_exact)
    drop_prefix = ["## 【核心要点】"] + extra_drop_prefix
    tail_cut = set(TAIL_CUT_HEADINGS) | set(tail_cut_exact)

    kept: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i].strip()
        if cur in tail_cut:
            break
        drop_hit = (cur in drop_exact) or any(cur.startswith(prefix) for prefix in drop_prefix)
        if drop_hit:
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                nxt_drop = (nxt in drop_exact) or any(nxt.startswith(prefix) for prefix in drop_prefix)
                if nxt.startswith("## ") and not nxt_drop:
                    break
                i += 1
            continue
        if not NOISE_LINE_RE.search(cur):
            kept.append(lines[i])
        i += 1

    return normalize_spacing("\n".join(kept))


def find_conversation_start_idx(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("## "):
            return i
    return 0


def extract_notebook_or_core_points(raw_text: str) -> str:
    lines = raw_text.splitlines()
    markers = ("## 【NotebookLM 智能总结】", "## 【核心要点】")
    for marker in markers:
        start = -1
        for i, line in enumerate(lines):
            if line.strip().startswith(marker):
                start = i + 1
                break
        if start >= 0:
            out: list[str] = []
            i = start
            while i < len(lines):
                s = lines[i].strip()
                if s == "---":
                    break
                if s.startswith("## "):
                    break
                if not s.startswith("### "):
                    out.append(lines[i])
                i += 1
            points = "\n".join(out).strip()
            if points:
                return points
    return ""


def build_publish_format(
    body_text: str,
    title: str,
    person_intro: str,
    hook: str,
    points_text: str,
) -> str:
    lines = body_text.splitlines()
    idx = find_conversation_start_idx(lines)
    conversation = "\n".join(lines[idx:]).strip()
    front = [
        f"# {title}",
        "",
        person_intro.strip(),
        "",
        hook.strip(),
        "",
        "以下是他的观点总结：",
        "",
    ]
    if points_text.strip():
        front.append(points_text.strip())
        front.append("")
    front.extend(["以下是访谈全文。", "", conversation, ""])
    return normalize_spacing("\n".join(front))


def apply_name_normalization(text: str) -> tuple[str, list[str]]:
    replacements = [
        ("首席执行官", "CEO"),
        ("首席财务官", "CFO"),
        ("人工智能", "AI"),
        ("企业信息学", "企业信息化"),
    ]
    changed: list[str] = []
    for src, dst in replacements:
        count = text.count(src)
        if count:
            text = text.replace(src, dst)
            changed.append(f"TEXT: {src} -> {dst} ({count})")
    return normalize_spacing(text), changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Lightweight publisher markdown post-processor")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument(
        "--mode",
        choices=["hybrid", "remove", "review-names", "publish-format"],
        default="hybrid",
    )
    parser.add_argument("--drop-headings")
    parser.add_argument("--drop-prefixes")
    parser.add_argument("--tail-cut-headings")
    parser.add_argument("--title")
    parser.add_argument("--person-intro")
    parser.add_argument("--hook")
    parser.add_argument("--points")
    parser.add_argument("--force-points-override", action="store_true")
    args = parser.parse_args()

    inp = Path(args.input).expanduser().resolve()
    if not inp.exists():
        raise FileNotFoundError(f"Input not found: {inp}")
    out = Path(args.output).expanduser().resolve() if args.output else derive_output_path(inp)

    raw = inp.read_text(encoding="utf-8")
    result = raw
    change_logs: list[str] = []

    extra_drop_exact = parse_pipe_list(args.drop_headings)
    extra_drop_prefix = parse_pipe_list(args.drop_prefixes)
    tail_cut_exact = parse_pipe_list(args.tail_cut_headings)

    if args.mode in ("hybrid", "remove"):
        result = remove_noise_blocks_with_dynamic(
            result,
            extra_drop_exact=extra_drop_exact,
            extra_drop_prefix=extra_drop_prefix,
            tail_cut_exact=tail_cut_exact,
        )

    if args.mode == "publish-format":
        points_text = extract_notebook_or_core_points(raw)
        if args.points and args.force_points_override:
            parts = [x.strip() for x in args.points.split("||") if x.strip()]
            points_text = "\n".join(f"{idx}. {part}" for idx, part in enumerate(parts, 1))
        cleaned = remove_noise_blocks_with_dynamic(
            raw,
            extra_drop_exact=extra_drop_exact,
            extra_drop_prefix=extra_drop_prefix,
            tail_cut_exact=tail_cut_exact,
        )
        result = build_publish_format(
            cleaned,
            args.title or "访谈实录",
            args.person_intro or "本文围绕受访者背景与关键观点展开。",
            args.hook or "这场访谈聚焦核心问题与现实决策逻辑。",
            points_text,
        )

    if args.mode in ("hybrid", "review-names"):
        result, change_logs = apply_name_normalization(result)

    out.write_text(normalize_spacing(result), encoding="utf-8")

    print(f"INPUT:  {inp}")
    print(f"OUTPUT: {out}")
    print(f"MODE:   {args.mode}")
    if args.mode in ("hybrid", "review-names"):
        print("NAME_REVIEW:")
        if change_logs:
            for item in change_logs:
                print(f"  - {item}")
        else:
            print("  - no replacements")


if __name__ == "__main__":
    main()

