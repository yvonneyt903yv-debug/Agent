# Todo

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
