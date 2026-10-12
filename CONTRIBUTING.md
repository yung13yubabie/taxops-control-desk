# Contributing

## Public repository boundary

Commit source, tests built from synthetic data, reviewed public specifications,
and required application assets. Keep personal handoffs, session transcripts,
local task lists, raw audit logs, screenshots of real records, credentials,
databases, backups, and exports outside the repository. Local ignored files are
not a secure storage mechanism. Do not attach real customer data to issues or CI.

Read [development contracts](docs/development_contract.md),
[the object model](docs/product_object_model.md),
[error handling](docs/no_silent_failure.md), [design guidelines](docs/design_guidelines.md),
and [desktop UI contracts](docs/desktop_ux_contract.md). Product contracts belong
in public documentation; execution history and private instructions do not.

## Setup and checks

Python 3.11 or newer is required. Use an isolated virtual environment and the
pinned release/CI dependencies:

```text
python -m venv .venv
python -m pip install -r requirements-release.txt -r requirements-ci.txt
python -m build_tools.check_repository_hygiene
python -m build_tools.run_test_matrix --output artifacts/source-tests
```

Activate `.venv` before the install and test commands using your shell's normal
activation command. The matrix starts each test file in a separate process and
combines raw branch coverage. All test files run; failures remain failures, and
the unrounded branch coverage gate stays at 90%. Do not replace this gate with a
focused suite, the hygiene-only workflow, or the five-file Windows diagnostic job.

Windows packaging and frozen verification use a separate release-only environment;
follow [the Windows candidate gate](docs/windows_candidate_gate.md). A source or
hosted-runner pass is not clean offline Windows/DPI acceptance.

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
