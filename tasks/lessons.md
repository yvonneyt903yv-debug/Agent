# Lessons

- Date: 2026-03-07
- Context: NotebookLM podcast output naming
- Lesson: Do not force target audio extension (e.g., `.mp3`) when upstream artifact container is different.
- Rule: Preserve upstream format by default; only transcode when there is an explicit compatibility requirement.
- Prevention: During review, check both filename extension and `ffprobe format_name` consistency for generated audio.
