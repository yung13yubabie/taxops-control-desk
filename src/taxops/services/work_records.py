"""Work Records service: workflow templates/runs and structured error reviews."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from ..core.text import sanitize_user_text
from ..repositories.work_records import (
    ErrorReviewRow,
    WorkRecordsRepository,
    WorkflowRunRow,
    WorkflowTemplateRow,
)
from .audit import AuditService

VALID_SEVERITIES = frozenset({"low", "medium", "high"})


class WorkRecordValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WorkflowStepInput:
    text: str


@dataclass(frozen=True)
class WorkflowStageInput:
    title: str
    steps: tuple[WorkflowStepInput, ...]


@dataclass(frozen=True)
class CreateWorkflowTemplateInput:
    name: str
    stages: tuple[WorkflowStageInput, ...]
    client_id: int | None = None
    engagement_id: int | None = None


@dataclass(frozen=True)
class CreateErrorReviewInput:
    title: str
    phenomenon: str
    root_cause: str
    short_term_fix: str | None = None
    long_term_guard: str | None = None
    severity: str = "medium"
    workflow_template_id: int | None = None
    guard_stage_id: str | None = None
    guard_step_text: str | None = None
    client_id: int | None = None
    engagement_id: int | None = None


def _dumps_stages(stages: list[dict]) -> str:
    return json.dumps(stages, ensure_ascii=False, separators=(",", ":"))


def _loads_stages(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise WorkRecordValidationError("work_record.stages.invalid") from err
    if not isinstance(data, list):
        raise WorkRecordValidationError("work_record.stages.invalid")
    return data


def _progress(stages: list[dict]) -> tuple[int, int, int]:
    total = 0
    done = 0
    for stage in stages:
        for item in stage.get("items", []):
            total += 1
            if item.get("done"):
                done += 1
    percent = int(round((done / total) * 100)) if total else 0
    return done, total, percent


def _require_row(row, code: str):
    if row is None:
        raise WorkRecordValidationError(code)
    return row


class WorkRecordsService:
    def __init__(self, repo: WorkRecordsRepository, audit: AuditService) -> None:
        self._repo = repo
        self._audit = audit

    def create_template(self, payload: CreateWorkflowTemplateInput) -> WorkflowTemplateRow:
        name = sanitize_user_text(payload.name, max_length=200)
        if not name:
            raise WorkRecordValidationError("work_record.template.name.required")
        stages = self._normalize_stage_inputs(payload.stages)
        row = self._repo.insert_template(
            name=name,
            stages_json=_dumps_stages(stages),
            client_id=payload.client_id,
            engagement_id=payload.engagement_id,
            context_snapshot=None,
        )
        self._audit.record(
            action="work_record.workflow_template.create",
            target_type="workflow_template",
            target_id=str(row.id),
            detail={"name": row.name},
        )
        return row

    def create_standard_company_setup_template(self) -> WorkflowTemplateRow:
        return self.create_template(
            CreateWorkflowTemplateInput(
                name="標準公司設立流程",
                stages=(
                    WorkflowStageInput(
                        title="前期準備",
                        steps=(
                            WorkflowStepInput("確認公司名稱與營業項目"),
                            WorkflowStepInput("確認負責人與股東資料"),
                        ),
                    ),
                    WorkflowStageInput(
                        title="資料審查",
                        steps=(
                            WorkflowStepInput("檢查身分證明文件"),
                            WorkflowStepInput("檢查租約或地址使用文件"),
                        ),
                    ),
                    WorkflowStageInput(
                        title="正式送件",
                        steps=(
                            WorkflowStepInput("送出登記申請"),
                            WorkflowStepInput("追蹤補件與核准狀態"),
                        ),
                    ),
                ),
            )
        )

    def instantiate_run(self, template_id: int, name: str | None = None) -> WorkflowRunRow:
        template = self._repo.get_template(template_id)
        if template is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        run_name = sanitize_user_text(name, max_length=200) or f"{template.name} 執行"
        row = self._repo.insert_run(
            template_id=template.id,
            name=run_name,
            stages_json=template.stages_json,
            client_id=template.client_id,
            engagement_id=template.engagement_id,
            context_snapshot=template.context_snapshot,
        )
        self._audit.record(
            action="work_record.workflow_run.create",
            target_type="workflow_run",
            target_id=str(row.id),
            detail={"template_id": template.id},
        )
        return row

    def set_run_step_done(
        self,
        run_id: int,
        *,
        stage_id: str,
        item_id: str,
        done: bool,
    ) -> WorkflowRunRow:
        run = self._repo.get_run(run_id)
        if run is None:
            raise WorkRecordValidationError("work_record.run.not_found")
        stages = _loads_stages(run.stages_json)
        changed = False
        for stage in stages:
            if stage.get("id") != stage_id:
                continue
            for item in stage.get("items", []):
                if item.get("id") == item_id:
                    item["done"] = bool(done)
                    changed = True
                    break
        if not changed:
            raise WorkRecordValidationError("work_record.step.not_found")
        updated = _require_row(
            self._repo.update_run_stages(run.id, stages_json=_dumps_stages(stages)),
            "work_record.run.not_found",
        )
        self._audit.record(
            action="work_record.workflow_run.step_update",
            target_type="workflow_run",
            target_id=str(run.id),
            detail={"stage_id": stage_id, "item_id": item_id, "done": done},
        )
        return updated

    def overwrite_template_from_run(self, run_id: int) -> WorkflowTemplateRow:
        run = self._repo.get_run(run_id)
        if run is None:
            raise WorkRecordValidationError("work_record.run.not_found")
        if run.template_id is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        template = self._repo.get_template(run.template_id)
        if template is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        updated = _require_row(
            self._repo.update_template_stages(
                template.id,
                name=template.name,
                stages_json=run.stages_json,
                bump_version=True,
            ),
            "work_record.template.not_found",
        )
        self._audit.record(
            action="work_record.workflow_template.overwrite_from_run",
            target_type="workflow_template",
            target_id=str(template.id),
            detail={"run_id": run.id},
        )
        return updated

    def save_run_as_template(self, run_id: int, name: str) -> WorkflowTemplateRow:
        run = self._repo.get_run(run_id)
        if run is None:
            raise WorkRecordValidationError("work_record.run.not_found")
        template_name = sanitize_user_text(name, max_length=200)
        if not template_name:
            raise WorkRecordValidationError("work_record.template.name.required")
        row = self._repo.insert_template(
            name=template_name,
            stages_json=run.stages_json,
            client_id=run.client_id,
            engagement_id=run.engagement_id,
            context_snapshot=run.context_snapshot,
        )
        self._audit.record(
            action="work_record.workflow_template.save_from_run",
            target_type="workflow_template",
            target_id=str(row.id),
            detail={"run_id": run.id},
        )
        return row

    def create_error_review(self, payload: CreateErrorReviewInput) -> ErrorReviewRow:
        if payload.severity not in VALID_SEVERITIES:
            raise WorkRecordValidationError("work_record.error.severity.invalid")
        title = sanitize_user_text(payload.title, max_length=200)
        phenomenon = sanitize_user_text(payload.phenomenon, max_length=2000)
        root_cause = sanitize_user_text(payload.root_cause, max_length=2000)
        if not title or not phenomenon or not root_cause:
            raise WorkRecordValidationError("work_record.error.required")
        guard_step = sanitize_user_text(payload.guard_step_text, max_length=500) or None
        if payload.workflow_template_id and guard_step:
            self.append_guard_step_to_template(
                payload.workflow_template_id,
                stage_id=payload.guard_stage_id,
                step_text=guard_step,
            )
        row = self._repo.insert_error_review(
            title=title,
            phenomenon=phenomenon,
            root_cause=root_cause,
            short_term_fix=sanitize_user_text(payload.short_term_fix, max_length=2000) or None,
            long_term_guard=sanitize_user_text(payload.long_term_guard, max_length=2000) or None,
            severity=payload.severity,
            workflow_template_id=payload.workflow_template_id,
            guard_stage_id=payload.guard_stage_id,
            guard_step_text=guard_step,
            client_id=payload.client_id,
            engagement_id=payload.engagement_id,
            context_snapshot=None,
        )
        self._audit.record(
            action="work_record.error_review.create",
            target_type="error_review",
            target_id=str(row.id),
            detail={"severity": row.severity, "workflow_template_id": row.workflow_template_id},
        )
        return row

    def append_guard_step_to_template(
        self,
        template_id: int,
        *,
        stage_id: str | None,
        step_text: str,
    ) -> WorkflowTemplateRow:
        template = self._repo.get_template(template_id)
        if template is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        clean_step = sanitize_user_text(step_text, max_length=500)
        if not clean_step:
            raise WorkRecordValidationError("work_record.step.required")
        stages = _loads_stages(template.stages_json)
        if not stages:
            raise WorkRecordValidationError("work_record.stage.not_found")
        target_stage = None
        if stage_id:
            target_stage = next((s for s in stages if s.get("id") == stage_id), None)
        if target_stage is None:
            target_stage = stages[-1]
        target_stage.setdefault("items", []).append({
            "id": f"step_{uuid4().hex[:10]}",
            "text": clean_step,
            "done": False,
        })
        updated = _require_row(
            self._repo.update_template_stages(
                template.id,
                name=template.name,
                stages_json=_dumps_stages(stages),
                bump_version=True,
            ),
            "work_record.template.not_found",
        )
        self._audit.record(
            action="work_record.workflow_template.guard_step_append",
            target_type="workflow_template",
            target_id=str(template.id),
            detail={"stage_id": target_stage.get("id"), "step_text": clean_step},
        )
        return updated

    def list_templates(self) -> list[WorkflowTemplateRow]:
        return self._repo.list_templates()

    def list_runs(self) -> list[WorkflowRunRow]:
        return self._repo.list_runs()

    def list_error_reviews(self) -> list[ErrorReviewRow]:
        return self._repo.list_error_reviews()

    def progress_for_stages_json(self, stages_json: str) -> tuple[int, int, int]:
        return _progress(_loads_stages(stages_json))

    def stages_for_row(self, row: WorkflowTemplateRow | WorkflowRunRow) -> list[dict]:
        return _loads_stages(row.stages_json)

    def _normalize_stage_inputs(
        self,
        stages: tuple[WorkflowStageInput, ...],
    ) -> list[dict]:
        if not stages:
            raise WorkRecordValidationError("work_record.stage.required")
        normalized: list[dict] = []
        for stage in stages:
            title = sanitize_user_text(stage.title, max_length=200)
            if not title:
                raise WorkRecordValidationError("work_record.stage.required")
            items = []
            for step in stage.steps:
                text = sanitize_user_text(step.text, max_length=500)
                if text:
                    items.append({"id": f"step_{uuid4().hex[:10]}", "text": text, "done": False})
            normalized.append({"id": f"stage_{uuid4().hex[:10]}", "title": title, "collapsed": False, "items": items})
        return normalized
