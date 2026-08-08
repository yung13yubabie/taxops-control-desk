# UI Redesign Implementation Spec

Written for an agent picking up one stage of the UI redesign with no memory of prior
sessions. Read this file, then the two it points at, then work.

Baseline: `feature/v030-annual-workbench`, v0.31.0 released, commit `055a3a1`.
Stages 1–3 (design system, shared page structure, clients page) are done and shipped.
Stages 4–18 are open.

## Pointers

- `.ai/UI_REDESIGN_AUDIT.md` — the screen register: every screen's owning class, core
  problem, business value, strategy, and acceptance. Reach it to learn what your stage
  must change and how it is judged.
- `docs/product_object_model.md` — object responsibilities and the single source of
  truth for each. Reach it whenever your stage touches annual work, engagements,
  tasks, workflow runs, or fixed billing, or displays any status or deadline.
- `.ai/DESIGN.md` — product-owned visual direction. Reach it before choosing any
  colour, spacing, or type value.
- `.ai/HANDOFF.md` — contracts a change must not break, and the test commands.

## Steps

Work one stage. Do not start a second.

1. **Read your stage's row** in `.ai/UI_REDESIGN_AUDIT.md`. It names the owning files
   and the acceptance condition.
2. **Read the current implementation end to end** before editing. The file is the
   authority on present behaviour.
3. **Inventory the tests that reach your files.** `grep` the test suite for the class
   name and for every `_attribute` your files expose. Those tests are the behaviour
   contract. This inventory is the input to step 6.
4. **Write the failing tests first** for the new behaviour, in a new file named
   `tests/test_ui_stage_<n>_<slug>.py`. Each assertion states a condition from the
   audit's acceptance column.
5. **Implement** until your new tests pass.
6. **Run the tests from step 3.** They pass unchanged, or you rewrite an assertion —
   and a rewritten assertion asserts more than the one it replaces, never less.
7. **Run the full suite** and report the exact counts.
8. **Write your report** in the format at the end of this file.

## Completion criteria

Your stage is done when all four hold:

- Every acceptance condition in your audit row has a test asserting it.
- The full suite passes with zero failures, and you state the count.
- Every attribute name your files exposed before still exists, or its removal is
  named in your report with the tests that were updated.
- Your report's Assumptions section lists every decision you made inside **fog**.

Visual and DPI acceptance stay open. They need a human at 100/125/150% scaling and no
automated assertion substitutes for that. Say so; do not describe tests as visual
acceptance.

## fog

**fog** is the region your stage's spec does not cover — a decision point where the
audit row, this file, and the object model are all silent. Every stage has fog. The
protocol is what you do inside it, and it turns on one question: does the decision
change what the data means?

When you enter fog, consult three sources in order:

1. **The tests that reach your files.** A test asserting current behaviour is a
   decision already made.
2. **`docs/product_object_model.md`.** It settles anything about status, deadlines,
   completion semantics, or which object owns a fact.
3. **The surrounding code's existing pattern.** Match it.

Then:

- **Any source answers** → follow it. Note the source in your report's Assumptions.
- **All three silent, and the decision is presentational** — layout, spacing, which
  section a field sits in, wording of a label, whether an action is secondary or quiet
  → **decide it yourself**, pick the smallest change that satisfies the audit row, and
  list it in Assumptions.
- **All three silent, and the decision changes data meaning** — what a status means,
  which object owns a fact, whether completing one thing completes another, what an
  audit entry records, whether a value is stored or derived → **stop that item**, list
  it in your report's Blocked section with the specific question, and continue with
  the rest of your stage.

The line is data meaning. Presentational fog you clear yourself; semantic fog you
report. A stage that reports zero fog either had none or did not look.

## loud

**loud** means a failure is visible at the moment it happens. The codebase has three
recorded cases where it was not, and each shipped a plausible-looking wrong result:

- `toolbar_icon` returned an information glyph for any unmapped role, so a typo drew a
  believable wrong icon. It now raises `UnknownIconRole`.
- A `background-color` declaration on `QCheckBox` moved indicator painting into the
  stylesheet and erased the unchecked border — measured, 64 painted pixels to zero.
  The control became invisible with no error anywhere.
- `Inspector.add_action` did not inherit the panel's placeholder state, so an action
  registered during construction appeared before any row was selected.

Write code that is loud:

- An unmapped key, unknown enum, or unsupported role **raises a named exception**.
- A caught exception **writes to `system_log` with the exception type** and **shows the
  user a sentence they can act on**, sourced from `i18n.error_message`.
- An unknown status **renders `未知狀態，請聯絡系統管理員` and writes a log line.**
- A state change **records an audit entry** naming the exact database id.
- Tests assert the error path, not only the happy path: give the code the bad input
  and assert the exception, the log, or the visible message.

When a value is genuinely optional, render `—`. That is a present answer, not silence.

## Contracts

These hold across every stage.

**Attribute names survive.** Existing tests drive real user paths through named
attributes. `clients_page.py` keeps `_delete_btn`, `_restore_btn`, and `_purge_btn`
even though users now reach them through a menu — the menu entry clicks the button, so
one path carries both. Follow that pattern when you move an action into a menu.

**`DateField`'s public API is frozen.** Six screens depend on it. Keep
`value_changed`, `value()`, `validated_value()`, `raw_text()`, `set_value()`,
`set_error()`, `clear()`, and `set_date_range()` with their current signatures and
semantics. Its internals and appearance are open.

**Shared widgets grow, they do not change.** `page_shell.py`, `inspector.py`,
`buttons.py`, `tokens.py`, `icons.py`, `empty_state.py`, and `table_builder.py` are
used by parallel work. Add a method or a token; leave existing signatures and values
alone. If your stage needs an existing one changed, report it instead.

**One primary per page.** `PageHeader.add_action` raises on a second primary and
`ActionBar` raises on a sixth visible action. Those exceptions are the design working.
Move the surplus into the overflow menu.

**Type floor.** Body text 14px, table headers 13px, error text 14px. Values live in
`tokens.py`; read them from there.

**Sizing.** Inputs and buttons 36px, compact 32px, icon buttons 32px, text rows 36px,
editor rows 42px. Qt applies `min-height` to the content rect, so subtract padding and
border — `style.py` shows the arithmetic.

**Colour carries no state alone.** Every status badge contains words. Colour is the
second cue.

**Selection reveals actions.** Actions needing a selected row live in the inspector
and appear when a row is selected. An empty selection shows the empty state's single
next step.

**Modal depth one.** A dialog opens from a page. Content that would open a second
dialog becomes a tab or an inline sub-page in the first.

**Business logic, database semantics, audit flow, and permission rules stay as they
are.** This is interface work. A change to any of them is semantic fog: report it.

## Environment

```powershell
python -m compileall -q src tests
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_ui_stage_<n>_<slug>.py -q
python -u -m pytest -q          # full suite, ~34 min, 2755 tests at baseline
git diff --check
```

Run pytest with `python -u` and read the output file directly. Piping a long run
through `tail` buffers everything until the process exits, so the file stays empty and
the run looks stalled.

Release builds use an isolated venv from `requirements-release.txt`. Packaging is not
part of a stage.

## Report format

```
## Stage <n> — <name>

### Done
<what changed, per file>

### Tests
New: tests/test_ui_stage_<n>_<slug>.py — <n> passed
Existing suites run: <names> — <n> passed
Full suite: <n> passed, <n> failed

### Assumptions
<every presentational decision made inside fog, with the source that settled it or
"decided: <reason>">

### Blocked
<every semantic fog item, with the specific question. "None" if none.>

### Contracts touched
<any attribute renamed or removed, any shared widget signature changed, and the tests
updated. "None" if none.>

### Not verified
<always includes visual and DPI acceptance>
```

## Stage assignments

Files listed are the stage's own. Reading anything is fine; editing outside your list
is semantic fog — report it.

| Stage | Name | Files |
| --- | --- | --- |
| 4 | Edit client dialog | `dialogs/edit_client_dialog.py`, `widgets/client_profile_form.py`, `widgets/client_leases_editor.py`, `dialogs/client_lease_dialog.py` |
| 5 | DateField rebuild | `widgets/date_field.py` |
| 6 | Annual workbench | `pages/annual_workbench_page.py` |
| 7 | Annual compliance settings | `dialogs/compliance_profile_dialog.py` |
| 8 | Create annual work | `dialogs/annual_workspace_dialog.py`, `widgets/annual_preview_table.py` |
| 9 | Annual work detail | `dialogs/annual_workflow_dialog.py`, `widgets/annual_item_detail.py`, `widgets/annual_item_fields.py` |
| 10 | Engagements and collaboration | `pages/engagements_page.py`, `pages/document_requests_page.py` |
| 11 | Tasks | `pages/tasks_page.py`, `dialogs/new_task_dialog.py`, `dialogs/task_bulk_dialogs.py` |
| 12 | Message templates | `pages/templates_page.py`, `dialogs/template_form_dialog.py` |
| 13 | Late-fee trial | `pages/late_fee_page.py` |
| 14 | Fixed billing | `pages/recurring_billing_page.py`, `dialogs/recurring_billing_dialogs.py` |
| 15 | Remaining pages | `pages/registry_page.py`, `pages/attachments_page.py`, `pages/folder_bookmarks_page.py`, `pages/settings_page.py`, `pages/work_records_page.py` |

Stage 15 also carries the inline-stylesheet migration: about 98 `setStyleSheet` calls
across the UI still override the role system, 33 of them in
`recurring_billing_page.py`. Each stage migrates the ones in its own files as it goes.

Stage 15's work-record portion waits on the four questions in `.ai/DECISIONS.md`
(2026-08-06). Until they are answered, work records keeps its current features and
receives styling only.
