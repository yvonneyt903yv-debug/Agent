# Lessons

- Date: 2026-03-07
- Context: NotebookLM podcast output naming
- Lesson: Do not force target audio extension (e.g., `.mp3`) when upstream artifact container is different.
- Rule: Preserve upstream format by default; only transcode when there is an explicit compatibility requirement.
- Prevention: During review, check both filename extension and `ffprobe format_name` consistency for generated audio.

- Date: 2026-03-07
- Context: User requested "plan first, do not change code yet"
- Lesson: For non-trivial debugging tasks, pause code edits until plan is explicitly confirmed by user.
- Rule: Complete root-cause analysis + execution plan first, then edit only after user approval.
- Prevention: Add a short pre-edit checkpoint message: "Will start code changes now" and wait for confirmation.

- Date: 2026-03-07
- Context: VPS sync path for Agent project
- Lesson: Do not assume VPS `~/projects/Agent` is a git repository; verify runtime structure first.
- Rule: For this environment, sync code to `~/projects/Agent/gps` and `~/projects/Agent/gps/src` via `scp`.
- Prevention: Before giving deploy commands, always run `pwd && ls` on VPS and map local-to-remote file paths explicitly.

- Date: 2026-03-15
- Context: Lex Fridman service debugging
- Lesson: Do not infer that a VPS runtime file is missing just because the local repo copy is absent or moved.
- Rule: Treat VPS file existence as unknown until confirmed with direct remote `ls`/`find` output.
- Prevention: Before proposing a missing-file root cause for VPS services, first verify both local and remote paths separately and label any gap as a hypothesis.
