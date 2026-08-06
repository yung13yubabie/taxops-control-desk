# UI Redesign Audit

Living record of the desktop UI rebuild: what was wrong, which code owns it, what
was done, and how it is verified. Updated at every checkpoint. Supersedes the
short-lived `UI_REBUILD_PLAN.md`.

Branch: `feature/v030-annual-workbench` (v0.30.0).
Last inventory: 2026-08-06.

## Version Ownership

The rebuild targets this branch, not `main`. Verified by file inventory:

| Rebuild target | `main` (v0.29.0) | this branch (v0.30.0) |
| --- | --- | --- |
| Annual workbench | absent | `ui/pages/annual_workbench_page.py` |
| Annual compliance settings | absent | `ui/dialogs/compliance_profile_dialog.py` |
| Annual work creation | absent | `ui/dialogs/annual_workspace_dialog.py`, `ui/widgets/annual_preview_table.py` |
| Annual work detail | absent | `ui/dialogs/annual_workflow_dialog.py` (1,194 lines) |
| Client leases | data layer only | `ui/widgets/client_leases_editor.py`, `ui/dialogs/client_lease_dialog.py` |

The packaged EXE under `dist/` is v0.29.0 and predates all of the above, so the
screenshots showing lease detail and the annual workbench correspond to this
worktree's source, not to `main` and not to the shipped EXE. Editing `main` would
modify the wrong revision.

## Measured Inventory (2026-08-06)

Counts over `src/taxops/ui`, excluding `__pycache__`:

| Element | Count | Note |
| --- | --- | --- |
| `QMainWindow` | 1 class | `ui/main_window.py` |
| `QDialog` subclasses | 35 | modal depth risk concentrated in annual and recurring billing |
| `QWidget` page/panel subclasses | 24 | 13 nav pages plus panels |
| `QPushButton` references | 306 | all were brand blue before this rebuild |
| `QDialogButtonBox` references | 109 | footer primary/cancel pairs |
| `QTableWidget` references | 163 | |
| `QTreeWidget` references | 7 | workflow step trees |
| `QGroupBox` references | 47 | main source of nested borders |
| `QScrollArea` references | 26 across 11 files | double-scroll risk |
| `QSplitter` references | 12 | |
| `FlowLayout` references | 24 across 9 pages | used as primary toolbar — not allowed |
| `QCalendarWidget` references | 4 | custom date popup |
| inline `setStyleSheet` | 101 | overrides the role system per page |
| `setProperty("role")` | via helper | `ui/widgets/buttons.py` |

Double-scroll candidates (a `QScrollArea` whose content also scrolls):
`annual_workflow_dialog.py`, `bulk_import_wizard.py`, `client_lease_dialog.py`,
`edit_client_dialog.py`, `new_client_dialog.py`, `recurring_billing_dialogs.py`,
`late_fee_page.py`, `recurring_billing_page.py`, `settings_page.py`,
`annual_item_fields.py`, `annual_transaction_panel.py`.

Tables hosting embedded editors: `compliance_profile_dialog.py`,
`mismatch_review_dialog.py`, `annual_preview_table.py`.

## Product Object Model

Object responsibilities and the single source of truth for each are fixed in
`.ai/DECISIONS.md` (2026-08-06) and `docs/product_object_model.md`. UI work must not
present a second opinion on compliance status.

Measured linkage, not assumed:

| From → to | Link | Mechanism | Status sync |
| --- | --- | --- | --- |
| Annual work → engagement | yes | `annual_work_items.engagement_id` (nullable) | none |
| Annual work ↔ task | yes, bidirectional | `workflow_tasks.annual_work_item_id` (`_m0028`); `create_linked_task` validates matching client and engagement | **none** — `complete_item` only writes `work_status` |
| Task → engagement | yes | `workflow_tasks.engagement_id` (nullable) | none |
| Task → task | yes | `parent_task_id` (`_m0018`) | n/a |
| Workflow run → client/engagement | yes | `workflow_runs.client_id`, `.engagement_id` | none |
| Workflow run → annual work | **no** | no column, no service code | n/a |
| Fixed billing → anything | **no** | independent | n/a |

Consequence carried into every screen: the same 營所稅結算申報 can exist as an annual
work item and as a linked task, and completing the annual item leaves the task open.
The UI must therefore label annual work as the compliance authority and must not
imply that finishing a task or a workflow run completes it.

## Global Defects

| # | Defect | Owning code | Remedy | Acceptance | Status |
| --- | --- | --- | --- | --- | --- |
| G1 | Every button brand blue; no action rank | `ui/style.py` base `QPushButton` | Seven roles via `role` dynamic property; base rule is secondary | `test_global_button_default_is_not_a_solid_primary_fill`, `test_only_primary_uses_the_brand_fill` | done |
| G2 | 8–12 peer actions per page; disabled-button graveyard | 9 pages using `FlowLayout` | PageHeader + ActionBar, five-action ceiling, overflow menu, contextual actions in inspector | pending stage 2 | todo |
| G3 | Checked checkbox is a blue square, no tick | `ui/style.py` `QCheckBox::indicator` | Restore platform indicator; only spacing and type in QSS | `test_checked_indicator_is_not_a_solid_block`, `test_unchecked_indicator_draws_a_visible_border` | done |
| G4 | Inputs and rows clip text | `ui/style.py` had padding but no `min-height`; no row-height token | Height tokens with box-model overhead subtracted | `test_button_height_leaves_room_for_its_text`, `test_input_height_leaves_room_for_its_text` | done |
| G5 | Nested borders (group box in card in table in frame) | `ui/style.py` `QGroupBox`, 47 references | Three surfaces only; group box becomes heading plus top rule | `test_group_box_does_not_add_a_full_border` | done (QSS); per-page cleanup pending |
| G6 | Mixed Qt standard pixmaps, emoji, Unicode arrows; unknown role silently became info icon | `ui/style.py` `_TOOLBAR_ICON_MAP` | 39-role inline SVG set; unknown role raises | `test_unknown_icon_role_raises_instead_of_falling_back`, `test_ui_source_no_longer_uses_qt_standard_pixmaps` | done |
| G7 | Sidebar toggle a full-width blue bar; collapse left a 32px strip; active item a saturated block | `ui/main_window.py`, `ui/style.py` | 220/56px, icons retained, 32x32 quiet toggle, left indicator | `test_sidebar_collapsed_restored_on_window_init`, `test_sidebar_active_item_is_not_a_saturated_block` | done |
| G8 | Body type below the product's own 14px floor | `ui/style.py` (13px body, 12px headers) | Type tokens at 14/13px | `test_no_declared_font_size_falls_below_thirteen_px` | done |
| G9 | Status conveyed by fill colour alone | status tokens, per-page badges | Text plus low-saturation background | partial — tokens done, per-page pending | todo |
| G10 | Double vertical scrolling | 11 files above | One primary scroll region per dialog | pending per-screen stages | todo |
| G11 | Modal canyon | `annual_workflow_dialog.py`, `client_lease_dialog.py` | Tabs or inline sub-pages; depth ≤ 1 | pending stages 6–10 | todo |
| G12 | 101 inline `setStyleSheet` override the role system | 33 in `recurring_billing_page.py`, 8 each in `document_requests_page.py` and `annual_workflow_dialog.py` | Migrate to roles and tokens per page | pending stage 2 onward | todo |
| G13 | Empty state shown together with an empty framed table | `widgets/empty_state.py` and pages | EmptyState replaces the table, single CTA | pending per-page stages | todo |
| G14 | Custom date picker with ±1/5/10-year buttons and a confirm step | `ui/widgets/date_field.py` (325 lines) | Rebuild: click-to-select, 300–340px popup, in-field quiet clear | icons replaced; full rebuild pending stage 5 | partial |

Correction to the brief: `toolbar_icon` roles `upload` and `paste` are not called
anywhere, so nothing was silently falling back at audit time. The real defects were
the fallback mechanism itself plus three wrong mappings among the ten roles in use —
`trial` resolved to an information glyph, `export` to a plain arrow, `new` to a
folder.

## Screen Register

Function and interface scores are the product owner's where given, otherwise
assigned from business role. Frequency is the expected office usage rate.

| Screen | Class / file | Core problem | Freq | Value | Strategy | Acceptance |
| --- | --- | --- | --- | --- | --- | --- |
| Clients | `pages/clients_page.py` | 8 peer actions; search/clear/2 checkboxes/count in one row; table carries addresses, full notes, leases; no inspector | daily | 9/10 | Master-detail template for the system: single primary, filters in a menu, six core columns, right inspector | contextual-action and master-detail tests |
| Edit client | `dialogs/edit_client_dialog.py` + `widgets/client_profile_form.py`, `client_leases_editor.py` | One long form; address occupies 200px+ for two lines; leases at the bottom; must scroll to save | daily | 9/10 | Tabs: 基本資料 / 聯絡與地址 / 備註與要求 / 租約; sticky footer; one scroll region | geometry + validation-retention tests |
| Annual workbench | `pages/annual_workbench_page.py` | 8 KPIs shown even at zero; core columns truncated; row text repeated below | weekly | 9/10 | Actionable KPIs only, five core columns, inspector, double-click to open | geometry + KPI tests |
| Annual compliance settings | `dialogs/compliance_profile_dialog.py` | checkbox + combo + empty explanation table; disabled rows still show frequency | monthly | 8/10 | Settings list; disclosure on enable | contextual disclosure tests |
| Create annual work | `dialogs/annual_workspace_dialog.py`, `widgets/annual_preview_table.py` | Many `QLineEdit`/date editors embedded in a table; editors clip | monthly | 8/10 | Three steps; per-item disclosure; 42px editor rows | geometry + wizard tests |
| Annual work detail | `dialogs/annual_workflow_dialog.py` | Work data, statuses, transactions, billing and collaboration on one surface; complete and cancel the same colour; collaboration opens a second modal | weekly | 9/10 | Tabs; complete primary, cancel danger; collaboration inlined | role + modal-depth tests |
| Engagements | `pages/engagements_page.py` | New/edit/toggle/delete/enter/refresh all peers; case name holds two unlabelled lines | daily | 9/10 | Single primary, inspector, badges with text | contextual-action tests |
| Collaboration | `pages/document_requests_page.py` (2 instances, 2,007 lines) | 12+ actions exposed; ten disabled buttons before any batch is selected | daily | 8/10 | Progressive disclosure: case → batch → item | disabled-graveyard tests |
| Tasks | `pages/tasks_page.py` | 10 top-level actions, most disabled; hierarchy manager exposed for one task | daily | 6/10 | List plus inspector; bulk only in multi-select mode | contextual-action tests |
| New/edit task | `dialogs/new_task_dialog.py` | Date picker unfit; cancel blue; 「下一步」 abstract; dialog occluded by popup | daily | 6/10 | New DateField, rename to 完成後接續事項, client-filtered case combo | DateField + form tests |
| Workflow templates/runs | `pages/work_records_page.py` | 12 flat buttons; templates and runs mixed; image area occupies half the screen when empty | weekly | 5/10 | Two tabs; image tools only when editing a step | tab + disclosure tests |
| Message templates | `pages/templates_page.py` | New/edit/delete/try as peers; refresh floating right; huge empty preview box | weekly | 8/10 | Keep master-detail; contextual actions; EmptyState | master-detail tests |
| New/edit template | `dialogs/template_form_dialog.py` | Field-source essay permanently occupies the top | weekly | 8/10 | Collapsible notes, searchable field list, live preview | insertion + preview tests |
| Late-fee trial | `pages/late_fee_page.py` | Date popup occludes content; all inputs crammed at top; empty rate-segment table dominates; result not prominent | weekly | 8.5/10 | Input → result → collapsed segments | calculation regression + geometry |
| Fixed billing | `pages/recurring_billing_page.py` (33 inline styles) | Duplicate 新增方案 entries; deep blue client banner; read-only cells look like inputs; 「選取」 repeated per row | monthly | 9/10 | Single primary, pale group header, real tables, header select-all | selection + audit tests |
| Fixed billing plan dialog | `dialogs/recurring_billing_dialogs.py` | Dialog scrolls and its table scrolls; amount editor clips; footer 新增方案 collides with 新增列 | monthly | 9/10 | One scroll region; numeric editor with 42px rows; footer 儲存方案 | inline-editor + geometry tests |
| Registry lookup | `pages/registry_page.py` | Two query buttons compete with the apply action | weekly | 8/10 | 套用至客戶主檔 is the only primary | role tests |
| Attachments / folders / settings | `pages/attachments_page.py`, `folder_bookmarks_page.py`, `settings_page.py` | Peer actions, refresh as a large button | weekly | 7/10 | Apply shared rules in stage 14 | role tests |

## Stage Order and Status

1. **Design system** — tokens, roles, checkbox, icons, sizing, sidebar. **done**
2. **Shared page structure** — `widgets/page_shell.py` (`PageHeader`, `ActionBar`,
   overflow menu, `build_page_layout`), `widgets/inspector.py`, reworked
   `widgets/empty_state.py`. **done.** Ceilings are enforced at construction: a
   header raises `ActionBarOverflowError` on a second primary, and an action bar
   raises on a sixth visible action. The overflow button does not consume a slot.
   Icon aliases added for the brief's unprefixed names (`calendar`, `client`,
   `engagement`, `task`, `workflow`, `template`, `calculator`, `attachment`,
   `folder`, `billing`, `settings`) plus a new `today` glyph — 39 roles, 51 names.
   Spacing tokens extended to 20 and 32 with a single `PAGE_MARGIN`; font stack now
   leads with Microsoft JhengHei UI.
3. **Clients page as the master-detail template — done.** Header owns the single
   primary; the action bar carries the search field with quiet search and clear icons,
   a 篩選 menu holding both list filters, 批量匯入, 欄位顯示, and a quiet refresh icon —
   four actions against the five-action ceiling. The table shows six columns
   (`short_name`, `contact_email`, both addresses, and `updated_at` are now opt-in), so
   the core list no longer needs horizontal scrolling. A `QSplitter` puts an
   `Inspector` beside the list: identity, contact, addresses, lease count, and last
   update, with 編輯客戶 and 租約管理 as contextual actions and 刪除/復原/永久刪除 behind
   更多. Notes and the lease table sit in the right column and are hidden entirely
   until a row is selected, replacing the two permanently visible framed boxes.
   Pagination uses chevron icons instead of ◀ ▶ glyphs. Three inline `setStyleSheet`
   calls removed.

   Deliberate compromise: the lease marker stays in the client-name cell. Moving it to
   its own column would require changing `TABLE_HEADERS` and
   `test_user_requests_v031.py`, whose real requirement is only that the list shows
   which clients have leases without an N+1 query. The ▸ glyph was removed; lease
   detail lives in the inspector.
4. Edit-client dialog — tabbed sections.
5. DateField rebuild (blocks tasks, late fee, leases, fixed billing).
6. Annual workbench.
7. Annual compliance settings.
8. Create annual work — three steps.
9. Annual work detail — tabs.
10. Engagements and collaboration — progressive disclosure.
11. Tasks.
12. Message templates and editor.
13. Late-fee trial.
14. Fixed billing and its plan dialog.
15. Remaining pages, dialogs, message boxes, context menus.
16. Full regression and coverage.
17. Windows packaging and EXE smoke.
18. Manual acceptance documentation.

## Verification Log

| Date | Command | Result |
| --- | --- | --- |
| 2026-08-06 | `python -m compileall -q src tests` | pass |
| 2026-08-06 | `pytest tests/test_ui_design_system.py` | 50 passed |
| 2026-08-06 | `pytest` on `test_date_field`, `test_slice26_clients_search`, `test_ui_layout_stability`, `test_ui_action_contracts`, `test_dialog_acceptance`, `test_app_runtime` | 108 passed |
| 2026-08-06 | `git diff --check` | clean |
| 2026-08-06 | `pytest tests/test_ui_page_shell.py tests/test_ui_design_system.py` | 72 passed (stage 2) |
| 2026-08-06 | `pytest` clients suites: `test_clients_page_user_paths`, `test_client_profile_ui`, `test_slice26_clients_search`, `test_slice21c_column_settings`, `test_user_requests_v031` | 76 passed (stage 3) |
| 2026-08-06 | `pytest` UI suites: `test_ui_action_contracts`, `test_ui_layout_stability`, `test_ui_regressions`, `test_slice19a_navigation`, `test_ui_design_system`, `test_ui_page_shell`, `test_clients_page_smoke`, `test_client_soft_delete_visibility` | 127 passed (stage 3) |
| 2026-08-06 | full `pytest` (sequential, `QT_QPA_PLATFORM=offscreen`) | **2,733 passed, 0 failed in 1,769s (29:29)** |

Scope limit on that full run: it started while only stage 1 was in place, and stages
2 and 3 landed while it was executing, so its later files exercised newer code than
its earlier ones. It is strong evidence that stage 1 caused no regression, and that
stages 2–3 did not break the suites that ran after them, but per
`.ai/COMMAND_EXECUTION_RULES.md` rule 10 it does **not** stand as the final
regression. Stage 16 must re-run the full suite once the remaining stages land.

Defects found by these tests during stage 2, both real and both fixed:

- `Inspector.add_action` did not inherit the panel's placeholder state, so an action
  registered while building a page appeared before any row was selected — the button
  graveyard the inspector exists to remove.
- `is_showing_placeholder` used `isVisible()`, which is False for any widget whose
  ancestors are unshown. The assertion passed for the wrong reason until it was
  changed to track state explicitly.

Manual acceptance not performed and not claimed: real mouse and keyboard use,
restart persistence, and 100/125/150% Windows scaling all require the running
application. Automated geometry assertions are not a substitute.
