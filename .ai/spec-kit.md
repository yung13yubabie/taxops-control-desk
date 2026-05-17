# .ai Collaboration Spec Kit

This directory is the shared startup context for CLI agents, AI agents, and human maintainers.

## Required Reading Order

Before working on this project, read files in this order:

1. `.ai/spec-kit.md`
2. `.ai/CURRENT_STATE.md`
3. `.ai/TASKS.md`
4. `.ai/DECISIONS.md` when decisions may affect the task
5. `.ai/DESIGN.md` before UI work
6. `.ai/RESOURCE_CLEANUP_AUDIT.md` before changing tests, download code, workers, or long-running operations
7. `.ai/HANDOFF.md` when taking over recent work
8. Relevant source code, tests, or docs only after reading the collaboration docs

Do not start by scanning the whole repository or making broad changes before reading this directory.

## File Purposes

- `spec-kit.md`: Collaboration rules, reading order, and update standards.
- `CURRENT_STATE.md`: Current project state only. Use present tense. Do not write history.
- `TASKS.md`: TODO, DOING, BLOCKED, and DONE task tracking.
- `DECISIONS.md`: Long-lived technical, product, process, and architecture decisions.
- `DESIGN.md`: Product-owned UI direction and visual rules.
- `RESOURCE_CLEANUP_AUDIT.md`: Network/process/port/socket/temp-file cleanup findings and remediation evidence.
- `HANDOFF.md`: Current handoff notes for the latest work session.

## Update Rules

- Update `CURRENT_STATE.md` when the current project shape, verified scope, or confirmed constraints change.
- Update `TASKS.md` when starting, blocking, finishing, or discovering actionable work.
- Update `DECISIONS.md` only for long-lived decisions with rationale and impact.
- Update `HANDOFF.md` before ending a substantial session or when leaving work for another agent.
- Update `RESOURCE_CLEANUP_AUDIT.md` when changing tests, HTTP downloads, worker threads, subprocess usage, browser automation, or long-running tasks.
- Do not record guesses as facts.
- Do not write large repository summaries unless the task explicitly requires them.

## Handoff Standard

A handoff must include:

- What changed in this session.
- Files added or modified.
- What remains unfinished.
- Next recommended step.
- Which files the next agent should read first.

## Collaboration Rules

- UI must be Traditional Chinese unless an explicit English mode is implemented.
- Do not create fake UI. A visible enabled action must connect to real service, repository, SQLite, audit log, and tests.
- Unimplemented features must be disabled and show `此功能尚未開放`.
- Keep implementation grounded in `docs/implementation_spec.md` and `docs/registry_cache_workflow.md`.
- For UI work, follow `.ai/DESIGN.md` before consulting external design references.
- The source specification at `C:\Users\LIN\Downloads\codex_readable_taxops_spec_compact.md` is reference material and should not be modified.
