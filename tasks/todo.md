# Todo

- [x] Confirm the real runtime entry for local `ph.py` publishing is `~/Library/LaunchAgents/com.gps.ph.plist`.
- [x] Add `EnvironmentVariables.PATH` to `com.gps.ph.plist` so launchd can find `npx`.
- [ ] Reload the LaunchAgent and verify publish logs no longer fail on missing Node/Bun.
- [x] Confirm Siemens missing-article issue root cause from logs and source behavior.
- [x] Update `gps/siemens.py` to support infinite-scroll loading on `/press/releases`.
- [x] Verify `get_article_links()` can include `/press/releases/new-artis-family`.
- [ ] Commit only related files with a short English message.

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
- Git commit: pending
- Sync status: local updated; VPS not yet synced
