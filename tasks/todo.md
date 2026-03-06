# Todo

- [x] Confirm local runtime file is `/Users/yvonne/Documents/Agent/gps/siemens.py` from active process.
- [x] Fix Siemens date resolution priority: parse page published date first, use `Last-Modified` only as fallback.
- [x] Fix Siemens image enhancement replacement to avoid nested markdown URL corruption.
- [x] Add markdown image download guard to skip non-http malformed URLs.
- [x] Re-run March 4 Siemens article (`new-artis-family`) with corrected logic and verify output.
- [ ] Commit only related files with a short English message.

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
- Git commit: not yet
- Sync status: local updated; VPS not yet synced
