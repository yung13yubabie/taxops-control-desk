# Product Object Model

Which object owns which fact. Written because several objects in this system carry a
status, a deadline, and a notion of "next", and without a stated owner the interface
ends up presenting two answers to the same question.

Every statement about linkage below was read from migrations and services on
2026-08-06 on `feature/v030-annual-workbench`, not inferred from naming.

## Objects and Responsibilities

### 年度工作 — annual work item

- Table: `annual_work_items`, grouped by `annual_workspaces` (client plus tax year).
- Responsibility: the controlling record for compliance and annual routine work.
- Carries: tax year, period, adopted deadline, and five independent status
  dimensions — `work_status`, `filing_status`, `document_status`, `tax_status`,
  `fee_status`.
- **Single source of truth for compliance status.** No other object may be read to
  answer "has this filing been done".
- Two deadline columns exist by design: `suggested_due_date` is what the compliance
  rules propose, `due_date` is what the office adopted. The UI must label which is
  which (decision of 2026-07-18).
- May reference an engagement through `engagement_id`, which is nullable.

### 案件 — engagement

- Table: `engagements`.
- Responsibility: a concrete deliverable for a client.
- The only shared meeting point: annual work, tasks, and workflow runs each may
  point at an engagement, and none of them point at each other except annual work
  and tasks.
- Owns document request batches, document items, and transactions.
- Must not carry a duplicate copy of annual compliance status.

### 待辦 — task

- Table: `workflow_tasks`.
- Responsibility: a short personal action.
- May reference a client, an engagement (`engagement_id`, nullable), another task
  (`parent_task_id`, added in `_m0018`), and an annual work item
  (`annual_work_item_id`, added in `_m0028`).
- `next_step` is a free-text column. It is a note, not a step in a workflow, and not
  a child record. The UI must not present it as either.
- Must not carry filing, document, or tax status. Those belong to annual work.

### 流程範本 — workflow template

- Table: `workflow_templates_v2`.
- Responsibility: a reusable set of steps.
- Holds no client work status.

### 流程執行 — workflow run

- Table: `workflow_runs`.
- Responsibility: the state of one application of a template.
- Steps live inside `stages_json`. The table itself has no status column.
- May reference `client_id` and `engagement_id`. Both are nullable, so a run with
  neither must be labelled 獨立執行 in the UI.
- Has **no** link to annual work: no column, no service code.

### 固定開立 — fixed billing

- Responsibility: a recurring issuance schedule and its pending history.
- `pending` means an issuance awaiting confirmation. It is **not** a receivable and
  must never be labelled as money the client owes.
- Confirmed, skipped, and cancelled history retains an audit trail.
- Has no link to any other object above.

## Measured Linkage

| From → to | Link | Mechanism | Status propagation |
| --- | --- | --- | --- |
| 年度工作 → 案件 | yes | `annual_work_items.engagement_id` (nullable) | none |
| 年度工作 ↔ 待辦 | yes, bidirectional | `workflow_tasks.annual_work_item_id`; `AnnualWorkService.create_linked_task` rejects a mismatched client or engagement | **none** |
| 待辦 → 案件 | yes | `workflow_tasks.engagement_id` (nullable) | none |
| 待辦 → 待辦 | yes | `parent_task_id` | none |
| 流程執行 → 客戶/案件 | yes | `workflow_runs.client_id`, `.engagement_id` | none |
| 流程執行 → 年度工作 | no | absent | n/a |
| 固定開立 → 其他 | no | absent | n/a |

## Completion Semantics

`AnnualWorkService.complete_item` writes `work_status` only. It sets
`completed_with_exception` instead of `completed` when any risk dimension is still
open, and then requires a reason. It does not touch linked tasks.

Therefore:

- Completing an annual work item does **not** complete its linked tasks.
- Completing a task does **not** complete the annual work item or the engagement.
- Completing a workflow run means nothing outside that run.

There is no implicit synchronisation anywhere in this model. Any future
synchronisation must be an explicit, tested rule with an audit entry — not a side
effect.

## Naming in the UI

| Object | UI label | Never call it |
| --- | --- | --- |
| annual work item | 年度工作 | 待辦, 任務 |
| engagement | 案件 | 專案 |
| task | 待辦 | 工作 (reserved for annual work) |
| workflow template | 流程範本 | 工作紀錄 |
| workflow run | 流程執行 | 待辦清單 |
| fixed billing pending record | 待開立紀錄 / 待確認 | 應收帳款, 欠款 |

`workflow_tasks.next_step` should read as 完成後接續事項 rather than 下一步, so it is
not mistaken for a workflow step.

## Derived-Only Displays

These may be shown but never stored as a second copy:

- An engagement's compliance progress — derived from its annual work items.
- A client's overdue count — derived from annual work deadlines.
- A workflow run's progress (for example 3/6) — derived from `stages_json`.
- A plan's pending count — derived from unconfirmed fixed-billing records.

## Open Questions

Product decisions, not implementation choices. Recorded in `.ai/DECISIONS.md`
(2026-08-06). No new work-record features until they are answered.

1. When an annual work item completes, should its linked tasks complete too? Today
   they do not, so the two states can disagree indefinitely.
2. Should a workflow run's progress write back to its engagement or annual work item?
   Today it does not.
3. Are workflow-run steps and task children the same concept? Today they are two
   unrelated data structures.
4. Is a workflow image a formal work instruction or an attachment? This decides
   whether it needs versioning and audit.

## Constraint

This document records the model as it is, plus the naming and display rules the UI
must follow. It does not authorise changing business logic, database semantics, the
audit trail, or permission rules. Where the current model is ambiguous, the UI avoids
implying an answer rather than inventing one.
