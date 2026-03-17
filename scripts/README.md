# Scripts

## translate_and_review.py

- Purpose: translate an input `.txt` file to Chinese Markdown/HTML/Word, then run review on translated Markdown.
- Translation engine: uses `src/translator.translate_article()` (same entry style as `main_us.py`).
- Typical usage:

```bash
python3 scripts/translate_and_review.py /path/to/input.txt --auto
```

- Notes:
- Requires `pypandoc` and local `pandoc` binary.
- `--auto` skips interactive confirmation between translation and review.
- Review supports `REVIEW_MODE=auto|serial|parallel_chunks` and `REVIEW_CONCURRENCY` tuning.

## md-to-publish.py

- Purpose: summarize an existing Markdown with NotebookLM, merge the summary back into the source Markdown under `## 【NotebookLM 智能总结】`, run the publisher flow, and then ask whether to publish to WeChat.
- Typical usage:

```bash
python3 md-to-publish.py /absolute/path/to/article.md
```

- Optional debug usage without NotebookLM network call:

```bash
python3 md-to-publish.py /absolute/path/to/article.md \
  --summary-text $'1. 要点一\n2. 要点二' \
  --skip-publisher
```

- Outputs:
- merged intermediate file: `*_publish_source.md`
- final publisher file: `*_publish.md`
- If `MINIMAX_API_KEY` / `MINIMAX_API_URL` are not configured, the script still uses publisher formatting and name review, while preserving the merged NotebookLM summary as the points section.
- After generating the final markdown, the script asks whether to publish. Only `y` will call `/Users/yvonne/Documents/publish_to_wechat_ds.py`; any other input exits.
