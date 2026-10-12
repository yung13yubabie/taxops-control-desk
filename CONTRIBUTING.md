# Contributing

## Public repository boundary

Commit source, tests built from synthetic data, reviewed public specifications,
and required application assets. Keep personal handoffs, session transcripts,
local task lists, raw audit logs, screenshots of real records, credentials,
databases, backups, and exports outside the repository. Local ignored files are
not a secure storage mechanism. Do not attach real customer data to issues or CI.

Read [development contracts](docs/development_contract.md),
[design guidelines](docs/design_guidelines.md), and the existing architecture and
packaging documentation. Public contracts belong in documentation; execution
history and private instructions do not.

## Setup and checks

Use Python 3.11 or newer in an isolated environment. Install the project's
`pyproject.toml` development dependencies, and use `requirements-release.txt`
for the isolated Windows release build as described in the packaging checklist.

```text
python -m build_tools.check_repository_hygiene
python -m pytest tests/test_repository_hygiene.py -q
python -m coverage run -m pytest
python -m coverage report --precision=2
```

The existing complete test/coverage gate remains unchanged at 90% branch-aware
coverage. Failures remain failures. The new hygiene-only workflow checks tracked
content and cannot substitute for full application tests or EXE acceptance.
These commands describe this branch's existing tooling; no candidate-version
matrix runner or newer application feature is introduced by this change.

Follow [the packaging checklist](docs/packaging_checklist.md) for Windows builds
and manual acceptance. A smoke test alone is not clean offline Windows/DPI
acceptance. Use synthetic data for new tests and diagnostics.

## Before committing

Stage specific paths, inspect `git diff --cached`, then run
`python -m build_tools.check_repository_hygiene`. The check reads staged Git
blobs, including files force-added despite `.gitignore`; it does not print file
contents. Stage again and rerun after any edit. Review new assets manually: this
small deterministic check cannot recognize all personal data or all secret formats.
It does not scan Git history, release assets, or remote caches.

`.env.example`, if needed, may contain comments and `NAME=` empty assignments only.
A local `.env` is never a template. Do not add blanket exemptions for test folders,
images, JSON, or ZIP files. Reviewed binary assets remain tracked. The existing
public registry ZIP is a fixed-path, fixed-hash exception documented in
[fixture provenance](docs/fixture_provenance.md); changing it needs a fresh review.

If a private file was already tracked, `.gitignore` alone does not remove it.
Preserve any needed private copy outside the repository, remove it from the Git
index, and verify the staged tree. Removing it in a new commit does not erase
older commits. Follow [SECURITY](SECURITY.md) for suspected exposures.
