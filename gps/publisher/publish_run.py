#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from minimax import MiniMaxClient  # type: ignore
else:
    from .minimax import MiniMaxClient

SCRIPT_DIR = Path(__file__).resolve().parent
PUBLISH_CLEAN = SCRIPT_DIR / "publish_clean.py"

TERM_REPLACEMENTS = {
    "人工智能": "AI",
    "首席执行官": "CEO",
    "首席财务官": "CFO",
    "首席信息官": "CIO",
    "首席数字官": "CDO",
    "企业信息学": "企业信息化",
}

FILLER_PHRASES = [
    "你知道，",
    "你知道",
    "正如大家所看到的，",
    "正如大家所看到的",
    "我想说的是，",
    "我想说的是",
    "但说真的，",
    "但说真的",
]


def derive_output_path(inp: Path) -> Path:
    if inp.suffix.lower() == ".md":
        return inp.with_name(f"{inp.stem}_publish.md")
    return inp.with_name(f"{inp.name}_publish.md")


def run_publish_clean(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(PUBLISH_CLEAN), *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def detect_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def extract_json_block(raw: str) -> dict[str, object]:
    raw = raw.strip()
    if raw.startswith("```"):
        match = re.search(r"```(?:json)?\n(.*?)\n```", raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    return data


def fallback_copy(title: str) -> dict[str, object]:
    return {
        "title": title,
        "person_intro": "本文整理自本场管理层沟通，保留核心判断与正文实录。",
        "hook": "内容聚焦增长、利润率、现金流与执行路径。",
        "points": [
            "管理层围绕增长、利润率、现金流和资本配置展开说明。",
            "重点涉及业务结构、创新投入与执行节奏。",
            "以下保留正文实录，并在必要处做篇幅压缩。",
        ],
    }


def build_rewrite_messages(title: str, clean_text: str, max_chars: int) -> list[dict[str, str]]:
    preview = clean_text[:12000]
    system = (
        "你是访谈稿发布编辑。只生成用于发布的前置文案，不改正文事实。"
        "输出必须是 JSON，对象字段为 title, person_intro, hook, points。"
        "points 必须是 3 到 4 条短句数组。"
    )
    user = (
        f"请为以下稿件生成可直接发布的前置文案，目标不超过 {max_chars} 字。\n"
        "压缩原则：优先用 AI/CEO/CFO 等英文简称；删除口语连接词；"
        "必要时减少个人健康、企业信息化和案例展开。\n"
        f"原始标题：{title}\n\n"
        "请只输出 JSON，不要额外说明。\n\n"
        "稿件预览如下：\n"
        f"{preview}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def apply_text_shorteners(text: str) -> str:
    for src, dst in TERM_REPLACEMENTS.items():
        text = text.replace(src, dst)
    for phrase in FILLER_PHRASES:
        text = text.replace(phrase, "")
    return text


def compress_known_sections(text: str) -> str:
    text = re.sub(
        r"## \*\*杜尔加·多赖萨米\*\*.*?(?=\n## \*\*)",
        "## **杜尔加·多赖萨米**\n\n**投资者关系主管**\n\n简要开场后，杜尔加宣布活动开始，议程包括 CEO、CFO 发言、业务线更新、Q&A 和客户圆桌。\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"在企业信息化领域，我们为独立的软件解决方案创建了一个专注的“家园”。*?"
        r"这样，它就能共同满足支持不同临床领域的整合诊断需求。\n",
        "企业信息化部分可概括为：通过软件、云和 AI 让数据流动起来，并把这些能力嵌入各平台。\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"个人健康为增长、利润率和现金生成做出了重要贡献.*?"
        r"对于个人健康而言，能够获得尖端的软件、AI和数据能力，以及在自助护理领域实现更个性化的受监管能力，是一项独特的资产。\n",
        "个人健康部分可概括为：继续贡献利润和现金流，支撑品牌，并通过 Sonicare、OneBlade 等平台型产品维持消费者黏性。\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    customer_start = text.find("\n**杰夫·迪卢洛**")
    if customer_start >= 0:
        text = (
            text[:customer_start].rstrip()
            + "\n\n**客户圆桌与收尾（压缩版）**\n\n"
            + "北美客户圆桌的核心反馈可压缩为三点：医疗系统同时承受老龄化、人员短缺和成本压力，因此更需要可规模化的平台；"
            + "平台价值在于标准化、互操作、把数据接入临床工作流，并进一步用 AI 提升效率和决策质量；"
            + "客户更强调长期合作，而不是单次采购。\n\n"
            + "活动最后，罗伊再次重申中期目标不变：中个位数增长、百分之十几利润率、强劲现金流，以及通过持续执行兑现价值。\n"
        )
    return text


def normalize_spacing(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    out: list[str] = []
    blank = 0
    for line in lines:
        if line.strip():
            blank = 0
            out.append(line)
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    return "\n".join(out).strip() + "\n"


def trim_to_limit(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cutoff = text.rfind("\n\n", 0, max_chars - 8)
    if cutoff < 0:
        cutoff = max_chars - 8
    return text[:cutoff].rstrip() + "\n\n[后文略]\n"


def run_publish(
    *,
    input_path: str,
    output_path: str | None = None,
    max_chars: int = 50000,
    api_key: str | None = None,
    api_url: str | None = None,
    model: str | None = None,
) -> dict[str, object]:
    inp = Path(input_path).expanduser().resolve()
    if not inp.exists():
        raise FileNotFoundError(f"Input not found: {inp}")

    out = Path(output_path).expanduser().resolve() if output_path else derive_output_path(inp)
    raw_text = inp.read_text(encoding="utf-8")
    title = detect_title(raw_text, inp.stem)

    with tempfile.TemporaryDirectory(prefix="publisher_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        cleaned = tmp_dir_path / "cleaned.md"
        run_publish_clean("--input", str(inp), "--output", str(cleaned), "--mode", "remove")
        clean_text = cleaned.read_text(encoding="utf-8")

        client = MiniMaxClient(api_key=api_key, api_url=api_url, model=model)
        copy = fallback_copy(title)
        if client.configured():
            try:
                llm_raw = client.chat(build_rewrite_messages(title, clean_text, max_chars), max_tokens=800)
                data = extract_json_block(llm_raw)
                points = data.get("points")
                if not isinstance(points, list) or not points:
                    raise ValueError("LLM points missing")
                copy = {
                    "title": str(data.get("title") or title).strip(),
                    "person_intro": str(data.get("person_intro") or copy["person_intro"]).strip(),
                    "hook": str(data.get("hook") or copy["hook"]).strip(),
                    "points": [str(x).strip() for x in points if str(x).strip()],
                }
            except Exception:
                copy = fallback_copy(title)

        draft = tmp_dir_path / "draft.md"
        run_publish_clean(
            "--input", str(inp),
            "--output", str(draft),
            "--mode", "publish-format",
            "--title", str(copy["title"]),
            "--person-intro", str(copy["person_intro"]),
            "--hook", str(copy["hook"]),
            "--points", "||".join(copy["points"]),
            "--force-points-override",
        )

        final_text = draft.read_text(encoding="utf-8")
        final_text = compress_known_sections(apply_text_shorteners(final_text))
        final_text = normalize_spacing(apply_text_shorteners(final_text))
        final_text = trim_to_limit(final_text, max_chars)
        out.write_text(final_text, encoding="utf-8")

        review = run_publish_clean(
            "--input", str(out),
            "--output", str(out),
            "--mode", "review-names",
        )

    final_chars = len(out.read_text(encoding="utf-8"))
    return {
        "ok": True,
        "input": str(inp),
        "output": str(out),
        "char_count": final_chars,
        "compressed": final_chars <= max_chars,
        "name_review": review.stdout.strip().splitlines(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the publisher workflow end-to-end")
    parser.add_argument("--input", required=True, help="Input markdown file path")
    parser.add_argument("--output", help="Output markdown file path")
    parser.add_argument("--max-chars", type=int, default=50000)
    parser.add_argument("--api-key")
    parser.add_argument("--api-url")
    parser.add_argument("--model")
    args = parser.parse_args()

    result = run_publish(
        input_path=args.input,
        output_path=args.output,
        max_chars=args.max_chars,
        api_key=args.api_key,
        api_url=args.api_url,
        model=args.model,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
