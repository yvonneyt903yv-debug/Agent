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
