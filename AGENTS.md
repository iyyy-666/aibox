# Codex Context Rules

This project is large. Keep default context small.

## Loading Order

1. Read this file.
2. Read `PROJECT_CONTEXT.md` for the project summary.
3. Read only the relevant subproject `PROJECT_CONTEXT.md`.
4. Read source files only when directly needed for the current task.

## Do Not Load By Default

- Entire project tree
- `.git`
- `node_modules`
- `build`
- `dist`
- `cache`
- `logs`
- `*.log`
- `*.sqlite`
- `*.bin`
- large JSON files
- datasets
- model files
- audio/video files
- generated files
- `latest_from_3588/extracted/` unless the task explicitly needs snapshot code

## Tool Output

- Prefer `rg`, targeted `Get-Content`, `Select-Object -First`, and `Select-Object -Last`.
- Avoid full `cat`/`Get-Content` on logs, manifests, archives, or large generated files.
- When reading logs, search for `ERROR`, `WARN`, `failed`, `exception`, timestamps, or process names first.
- Limit shell output before running commands that may print many files.

## Context Budget

- Small task target: under 50K input tokens.
- Medium task target: under 80K input tokens.
- Complex task target: under 150K input tokens only when justified.
- If a normal task approaches 150K tokens, stop expanding context and narrow the file set.

## Long Sessions

- Do not carry unrelated completed task history into a new task.
- Summarize only current task, changed files, status, and next step.
- Do not re-read unchanged `PROJECT_CONTEXT.md`, `README.md`, manifests, or large source files in full.
