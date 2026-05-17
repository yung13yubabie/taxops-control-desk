# TaxOps Control Desk

Windows-first desktop application for Taiwan accounting and tax office operations.

Current status: specification and project skeleton only. Application features are not implemented yet.

## Before Working

Read the collaboration files first:

1. `.ai/spec-kit.md`
2. `.ai/CURRENT_STATE.md`
3. `.ai/TASKS.md`
4. `.ai/DECISIONS.md`
5. `.ai/DESIGN.md` before UI work

Primary implementation docs:

- `docs/implementation_spec.md`
- `docs/registry_cache_workflow.md`
- `docs/ui_action_contract.md`

## Development Commands

These commands are planned and must be made real during implementation:

```powershell
python -m pytest
python -m taxops
python -m build_tools.clean_package
python -m build_tools.package_windows
python -m build_tools.smoke_test_exe
```

## MVP Rule

MVP is not complete until every item in section 24 of the source specification is implemented and verified.

No fake UI is allowed.
