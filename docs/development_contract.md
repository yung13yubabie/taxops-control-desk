# Development contracts

Use the current source and regression tests as the behavioral baseline. Public
architecture is described in `implementation_spec.md`, `registry_cache_workflow.md`,
and `ui_action_contract.md`; visual requirements are in `design_guidelines.md`.

- Preserve business meaning, database semantics, audit history, transactions, and
  access/ownership checks. A visual change must not redefine a business status.
- Fixed billing represents scheduled issuance, not accounts receivable. Confirmed
  issuance and reversal retain audit evidence; deleting a plan must not silently
  delete issued history. Batch operations act on the selected pending records.
- GCIS lookup is an optional official per-tax-id online fallback. Keep its source
  distinct from the downloaded Ministry of Finance tax cache; offline results
  must not imply a live verification.
- Optional display values may be empty, but failures must remain visible and
  must not masquerade as successful empty results.
- Preserve existing component interfaces, user data, and regression assertions.
  Unknown business semantics require explicit product review rather than guessing.
- Complete branch-aware coverage remains at least 90%; neither this documentation
  nor the repository hygiene check waives existing test or Windows acceptance.

Keep execution notes, handoffs, raw logs and private instructions outside Git.
See `../CONTRIBUTING.md` for checks and `../SECURITY.md` for data handling.
