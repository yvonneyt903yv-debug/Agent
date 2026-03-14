# Todo

- [x] Confirm the exact local runtime path for Podscribe on Mac (`LaunchAgent -> main.py -> gps/sf_ds.py`).
- [x] Design a strict full-Chinese translation policy for Podscribe outputs: no English fallback chunks may be saved.
- [x] Bypass legacy fallback in `gps/sf_ds.py` by preferring `src/translator.py` strict translation path.
- [x] Add a final Chinese-completeness gate in `gps/sf_ds.py` before saving Markdown/HTML/Word outputs.
- [x] Verify modified files with syntax checks and one focused local translation-path test.
- [ ] Commit only Podscribe-related files with a short English message.

- [x] Confirm real runtime file for Podscribe is `/Users/yvonne/Documents/sf_ds.py` rather than `Agent/gps/sf_ds.py`.
- [x] Fix `sf_ds.py` so review output cannot silently replace a longer translation with truncated content.
- [x] Sync the same `sf_ds.py` fix into `Agent/gps/sf_ds.py` to keep repo copy aligned with runtime.
- [x] Run syntax checks for both `sf_ds.py` copies and note restart/verification commands.

- [x] Confirm local runtime file for Philips pipeline is `/Users/yvonne/Documents/Agent/gps/ph.py`.
- [x] Reproduce and verify bad Philips outputs are shell-content pages (disclaimer/browser tip) rather than real article body.
- [x] Add Philips-specific low-quality content gate in `gps/ph.py` to block shell/noise extraction.
- [x] Add Philips direct HTML fallback extraction (`article/main/p`) when Jina output is low quality.
- [x] Add encoding safety fallback (`apparent_encoding`) in Philips direct extraction to reduce mojibake risk.
- [ ] Run one full local Philips cycle and verify new `ph_processed.json` entries no longer show short/garbled content.

- [x] Confirm local runtime file is `/Users/yvonne/Documents/Agent/gps/siemens.py` from active process.
- [x] Fix Siemens date resolution priority: parse page published date first, use `Last-Modified` only as fallback.
- [x] Fix Siemens image enhancement replacement to avoid nested markdown URL corruption.
- [x] Add markdown image download guard to skip non-http malformed URLs.
- [x] Re-run March 4 Siemens article (`new-artis-family`) with corrected logic and verify output.
- [x] Commit only related files with a short English message.

- [x] Confirm Siemens "today/yesterday" mismatch root cause (`get_target_dates()` returns 7 days in shared module).
- [x] Update `gps/siemens.py` to use Siemens-local target dates (today + yesterday only).
- [x] Add multi-source article date resolution (list date -> content date -> page meta/time/json-ld).
- [x] Add HTTP `Last-Modified` header fallback to page-level date extraction.
- [x] Improve unknown-date logging to include title/list raw date for debugging.
- [ ] Verify on local runtime (`python3 siemens.py`) that new links show `Resolved article date` and no longer skip as unknown.

- [x] Confirm the real runtime entry for local `ph.py` publishing is `~/Library/LaunchAgents/com.gps.ph.plist`.
- [x] Add `EnvironmentVariables.PATH` to `com.gps.ph.plist` so launchd can find `npx`.
- [ ] Reload the LaunchAgent and verify publish logs no longer fail on missing Node/Bun.
- [x] Confirm Siemens missing-article issue root cause from logs and source behavior.
- [x] Update `gps/siemens.py` to support infinite-scroll loading on `/press/releases`.
- [x] Verify `get_article_links()` can include `/press/releases/new-artis-family`.
- [x] Commit only related files with a short English message.

- [x] Confirm local `ph.py` processed record does not persist readable content body (only lengths/path).
- [x] Update `gps/ph.py` to store `content_preview` in `ph_processed.json` for local inspection.
- [ ] Run one full local ph cycle and verify latest `ph_processed.json` entry contains `content_preview`.

- [x] Confirm podcast "no sound" report root cause by probing target output file stream/container and volume.
- [x] Change NotebookLM audio download naming to preserve source container format (`.m4a`) instead of forcing `.mp3`.
- [x] Apply the same extension fix to duplicate NotebookSkill implementation and standalone summary script to avoid regression.
- [x] Validate updated code paths with syntax checks and spot-check existing podcast files for container/extension consistency.

- [x] Confirm local runtime path for Philips translation entry is `gps/ph.py -> gps/rss_monitor_base.py -> src/singju_ds.py -> src/deepseek.py`.
- [x] Add unified DeepSeek network strategy in `src/deepseek.py` (`DEEPSEEK_NETWORK_MODE=auto/proxy/direct`) to avoid proxy path split.
- [x] Add fast-fail glossary extraction in `src/singju_ds.py` (short timeout + single retry + fallback) to prevent blocking at first LLM call.
- [x] Validate modified Python files with `python3 -m py_compile`.
- [x] Verify DeepSeek mode resolution (`auto/proxy/direct`) matches crawler proxy source in local checks.
- [x] Run one full local `gps/ph.py` cycle and capture current blocker (RSS fetch fails at proxy connect before translation stage).
- [x] Run minimal glossary-call test and confirm fast-fail fallback works (`Connection error` returns quickly and degrades to `{}`).

# Review

- Date: 2026-03-04
- Scope: local macOS LaunchAgent environment fix for `com.gps.ph.plist`
- Files: `~/Library/LaunchAgents/com.gps.ph.plist`
- Change path: added `EnvironmentVariables.PATH` for `launchd` background execution
- Git commit: not yet
- Sync status: local-only change; no VPS sync needed

- Date: 2026-03-06
- Scope: Siemens releases page missing `new-artis-family` in crawler results
- Files: `gps/siemens.py`, `tasks/todo.md`
- Change path: add infinite-scroll trigger loop in `get_article_links()` before extracting release anchors
- Git commit: `b51f865` (`Fix Siemens releases infinite scroll`), `f2a9187` (`Update Siemens task log`)
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-06
- Scope: Siemens unknown-date skipping on new releases
- Files: `gps/siemens.py`, `tasks/todo.md`
- Change path: align target window to today+yesterday, add page date fallback, and add `Last-Modified` header date fallback
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-06
- Scope: local `ph.py` processed record visibility for content inspection
- Files: `gps/ph.py`, `tasks/todo.md`
- Change path: persist `content_preview` and `content_preview_length` in `ph_processed.json` on successful processing
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-06
- Scope: Siemens date correctness and malformed image URL parsing during translation
- Files: `gps/siemens.py`, `gps/rss_monitor_base.py`, `tasks/todo.md`
- Change path: prefer page published date over `Last-Modified`; avoid nested markdown image replacement; guard non-http image URLs; rerun `new-artis-family` with corrected date (`2026-03-04`)
- Git commit: `3de6fb3` (`Fix Siemens date and image parsing`)
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-06
- Scope: local `ph.py` content garbling and body-loss mitigation for Philips pages
- Files: `gps/ph.py`, `tasks/todo.md`
- Change path: add low-quality shell-content detection, Philips direct HTML body extraction fallback, and response encoding fallback to `apparent_encoding`
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-07
- Scope: NotebookLM podcast extension mismatch causing occasional silent playback in some players
- Files: `src/notebook_tool.py`, `notebook_tool.py`, `notebooklm_summary_podcast.py`, `tasks/todo.md`
- Change path: stop forcing `.mp3` filename for downloaded NotebookLM audio; preserve `.m4a` container naming
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-07
- Scope: Philips pipeline stalls on first LLM glossary request and proxy path mismatch
- Files: `src/deepseek.py`, `src/singju_ds.py`, `tasks/todo.md`
- Change path: add configurable DeepSeek network mode (`auto/proxy/direct`) and fast-fail glossary extraction fallback
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-07
- Scope: align DeepSeek proxy decision with crawler proxy source
- Files: `src/deepseek.py`, `tasks/todo.md`
- Change path: `auto` mode now prefers `gps/server_utils.get_proxy_config()`; local mode-resolution checks pass, but quick live probe hit `Connection error`
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-07
- Scope: execution test for Philips local pipeline after proxy/glossary changes
- Files: `tasks/todo.md`
- Change path: ran `gps/ph.py` initial cycle and isolated current failure at RSS proxy connect; ran glossary minimal test and verified fast-fail fallback without long blocking
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- [x] Confirm `translate_and_review.py` currently uses `singju_ds` translation entry.
- [x] Align translation call with `main_us.py` style by switching to `src/translator.translate_article`.
- [x] Move script into repo path `scripts/translate_and_review.py` for versioned management.
- [x] Add `scripts/README.md` for script usage and dependency notes.
- [x] Commit only related files with a short English message.

- Date: 2026-03-08
- Scope: move translate-and-review helper into Agent repo and align translator entry with `main_us.py`
- Files: `scripts/translate_and_review.py`, `scripts/README.md`, `tasks/todo.md`
- Change path: copied script into `scripts/`, switched translation entry to `src/translator.translate_article`, and added script-level README
- Git commit: pending
- Sync status: local updated; VPS not yet synced

- [x] Confirm runtime chain for `publish_to_wechat_ds.py` points to `gps/publish_to_wechat.py` and then `baoyu-skills/.../wechat-article.ts`.
- [x] Reproduce title extraction logic on target markdown and verify H1 parsing is correct (not full body).
- [x] Fix WeChat editor selector fallback to avoid selecting title input when inserting HTML content.
- [ ] Re-run one full publish flow and verify article body stays in editor while title keeps only H1 text.

- [x] Confirm runtime module path for Singju translation is `gps/* -> src/singju_ds.py`.
- [x] Enable parallel chunk translation in `src/singju_ds.py` with ordered merge and serial compensation fallback.
- [x] Enable parallel chunk review in `src/review_markdown_ds.py` with serial compensation fallback.
- [x] Run syntax/import checks for stage-1 changes and commit related files only.
- [x] Switch `src/singju_ds.py` to call `translator.py` and `reviewer.py` first, with safe fallback to legacy path.
- [x] Run syntax/import checks for stage-2 changes and commit related files only.

- Date: 2026-03-10
- Scope: WeChat publish automation pasted full article into title field
- Files: `baoyu-skills/skills/baoyu-post-to-wechat/scripts/wechat-article.ts`, `tasks/todo.md`
- Change path: narrowed editor selection to content area, excluded title-like contenteditable elements, and blocked `INPUT/TEXTAREA` fallback before HTML insertion
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-10
- Scope: phased safety rollout for Singju translation/review performance
- Files: `src/singju_ds.py`, `src/review_markdown_ds.py`, `tasks/todo.md`
- Change path: stage-1 enabled parallel chunk execution in local singju/review module with ordered merge and fallback; stage-2 switched singju entry to `translator.py` + `reviewer.py` with env-controlled fallback
- Git commit: `b093cc2` (`Enable parallel chunk translation and review`), `8580206` (`Switch singju pipeline to translator and reviewer`)
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-12
- Scope: Podscribe review-stage truncation guard and runtime/repo path alignment
- Files: `/Users/yvonne/Documents/sf_ds.py`, `gps/sf_ds.py`, `tasks/todo.md`
- Change path: confirmed real runtime is `/Users/yvonne/Documents/sf_ds.py`; added review-output length guard to prevent short reviewed text replacing longer translations; synced same guard to repo copy; added repo-copy import path fallback for direct execution; verified with `python3 -m py_compile`
- Git commit: not yet
- Sync status: local updated; runtime copy updated on Mac; VPS not involved

- Date: 2026-03-14
- Scope: Podscribe full-Chinese output enforcement on local Mac background run
- Files: `gps/sf_ds.py`, `tasks/todo.md`
- Change path: switched Podscribe translation to prefer strict `src/translator.py` path, added final mixed-language rejection gate before file save, and verified with `python3 -m py_compile` plus a local detector smoke test
- Git commit: pending
- Sync status: local updated; VPS not yet synced
