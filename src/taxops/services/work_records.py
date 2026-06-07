"""Work Records service: workflow templates/runs and structured error reviews."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PySide6.QtGui import QImage

from ..core.text import sanitize_user_text
from ..repositories.work_records import (
    ErrorReviewRow,
    WorkRecordsRepository,
    WorkflowRunRow,
    WorkflowTemplateRow,
)
from ..security.image_guard import ImageGuardError, validate_image_data, validate_image_file
from .audit import AuditService

VALID_SEVERITIES = frozenset({"low", "medium", "high"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})


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


def _load_context_snapshot(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


class WorkRecordsService:
    def __init__(
        self,
        repo: WorkRecordsRepository,
        audit: AuditService,
        workflow_assets_dir: Path | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._workflow_assets_dir = workflow_assets_dir
        self._conn = repo._conn

    @property
    def workflow_assets_dir(self) -> Path:
        if self._workflow_assets_dir is None:
            raise WorkRecordValidationError("work_record.asset.storage_unavailable")
        return self._workflow_assets_dir

    def create_template(self, payload: CreateWorkflowTemplateInput) -> WorkflowTemplateRow:
        name = sanitize_user_text(payload.name, max_length=200)
        if not name:
            raise WorkRecordValidationError("work_record.template.name.required")
        stages = self._normalize_stage_inputs(payload.stages)
        with self._conn:
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

    def update_template(
        self,
        template_id: int,
        payload: CreateWorkflowTemplateInput,
    ) -> WorkflowTemplateRow:
        existing = self._repo.get_template(template_id)
        if existing is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        name = sanitize_user_text(payload.name, max_length=200)
        if not name:
            raise WorkRecordValidationError("work_record.template.name.required")
        stages = self._normalize_stage_inputs(payload.stages)
        with self._conn:
            updated = _require_row(
                self._repo.update_template_stages(
                    template_id,
                    name=name,
                    stages_json=_dumps_stages(stages),
                    bump_version=True,
                ),
                "work_record.template.not_found",
            )
            self._audit.record(
                action="work_record.workflow_template.update",
                target_type="workflow_template",
                target_id=str(updated.id),
                detail={"name": updated.name, "previous_version": existing.version},
            )
        return updated

    def set_template_image_path(
        self,
        template_id: int,
        image_path: str | None,
    ) -> WorkflowTemplateRow:
        if not image_path:
            return self.set_template_image_asset(template_id, None)
        if self._repo.get_template(template_id) is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        rel_path, width, height = self.import_workflow_image_asset(Path(image_path))
        try:
            return self.set_template_image_asset(
                template_id,
                rel_path,
                width=width,
                height=height,
            )
        except Exception:
            self._remove_workflow_image_asset(rel_path)
            raise

    def set_template_image_data(
        self,
        template_id: int,
        image: QImage,
    ) -> WorkflowTemplateRow:
        if self._repo.get_template(template_id) is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        rel_path, width, height = self.import_workflow_image_data(image)
        try:
            return self.set_template_image_asset(
                template_id,
                rel_path,
                width=width,
                height=height,
            )
        except Exception:
            self._remove_workflow_image_asset(rel_path)
            raise

    def import_workflow_image_asset(self, source_path: Path) -> tuple[str, int, int]:
        source = Path(source_path)
        ext = source.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            raise WorkRecordValidationError("work_record.asset.extension_invalid")
        if not source.is_file():
            raise WorkRecordValidationError("work_record.asset.not_found")
        try:
            width, height = validate_image_file(source)
        except (OSError, ImageGuardError) as exc:
            raise WorkRecordValidationError("work_record.asset.image_invalid") from exc
        rel = Path("images") / f"{uuid4().hex}{ext}"
        dest = self.workflow_assets_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        staging = dest.with_name(f".{dest.name}.tmp")
        try:
            shutil.copy2(source, staging)
            staging.replace(dest)
        except Exception:
            staging.unlink(missing_ok=True)
            dest.unlink(missing_ok=True)
            raise
        return rel.as_posix(), width, height

    def import_workflow_image_data(self, image: QImage) -> tuple[str, int, int]:
        try:
            width, height = validate_image_data(image)
        except ImageGuardError as exc:
            raise WorkRecordValidationError("work_record.asset.image_invalid") from exc
        rel = Path("images") / f"{uuid4().hex}.png"
        dest = self.workflow_assets_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        staging = dest.with_name(f".{dest.name}.tmp")
        try:
            if not image.save(str(staging), "PNG"):
                raise WorkRecordValidationError("work_record.asset.image_invalid")
            staging.replace(dest)
        except Exception:
            staging.unlink(missing_ok=True)
            dest.unlink(missing_ok=True)
            raise
        return rel.as_posix(), width, height

    def _remove_workflow_image_asset(self, rel_path: str) -> None:
        try:
            asset_path = self._safe_workflow_asset_path(rel_path)
        except WorkRecordValidationError:
            return
        asset_path.unlink(missing_ok=True)

    @staticmethod
    def _image_paths(context_snapshot: str | None, stages_json: str) -> set[str]:
        paths: set[str] = set()
        snapshot = _load_context_snapshot(context_snapshot)
        main_image = snapshot.get("image_path")
        if isinstance(main_image, str) and main_image:
            paths.add(main_image)
        for stage in _loads_stages(stages_json):
            for item in stage.get("items", []):
                image_path = item.get("image_path")
                if isinstance(image_path, str) and image_path:
                    paths.add(image_path)
        return paths

    def _remove_asset_if_unreferenced(self, rel_path: str | None) -> None:
        if not rel_path:
            return
        rows = self._conn.execute(
            "SELECT context_snapshot, stages_json FROM workflow_templates_v2"
            " WHERE deleted_at IS NULL"
            " UNION ALL"
            " SELECT context_snapshot, stages_json FROM workflow_runs"
            " WHERE deleted_at IS NULL"
        ).fetchall()
        for row in rows:
            try:
                referenced_paths = self._image_paths(
                    row["context_snapshot"], row["stages_json"]
                )
            except WorkRecordValidationError:
                # Corrupt historical JSON must not turn a committed delete/update
                # into a reported failure or risk deleting an asset still in use.
                return
            if rel_path in referenced_paths:
                return
        self._remove_workflow_image_asset(rel_path)

    def _cleanup_unreferenced_assets(self, rel_paths: set[str]) -> None:
        for rel_path in rel_paths:
            self._remove_asset_if_unreferenced(rel_path)

    def set_template_image_asset(
        self,
        template_id: int,
        rel_path: str | None,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> WorkflowTemplateRow:
        template = self._repo.get_template(template_id)
        if template is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        snapshot = _load_context_snapshot(template.context_snapshot)
        previous_path = snapshot.get("image_path")
        clean_path = sanitize_user_text(rel_path, max_length=1000) if rel_path else ""
        if clean_path:
            asset_path = self._safe_workflow_asset_path(clean_path)
            try:
                image_width, image_height = validate_image_file(asset_path)
            except (OSError, ImageGuardError) as exc:
                raise WorkRecordValidationError("work_record.asset.image_invalid") from exc
            snapshot["image_path"] = clean_path
            snapshot["image_width"] = int(width or image_width)
            snapshot["image_height"] = int(height or image_height)
        else:
            snapshot.pop("image_path", None)
            snapshot.pop("image_width", None)
            snapshot.pop("image_height", None)
        with self._conn:
            updated = _require_row(
                self._repo.update_template_context(
                    template_id,
                    context_snapshot=json.dumps(snapshot, ensure_ascii=False) if snapshot else None,
                ),
                "work_record.template.not_found",
            )
            self._audit.record(
                action="work_record.workflow_template.image_update",
                target_type="workflow_template",
                target_id=str(updated.id),
                detail={"has_image": bool(clean_path)},
            )
        self._remove_asset_if_unreferenced(
            previous_path if isinstance(previous_path, str) else None
        )
        return updated

    def set_template_step_image_path(
        self,
        template_id: int,
        *,
        stage_id: str,
        item_id: str,
        image_path: str,
    ) -> WorkflowTemplateRow:
        self._require_template_step_target(template_id, stage_id=stage_id, item_id=item_id)
        rel_path, width, height = self.import_workflow_image_asset(Path(image_path))
        try:
            return self.set_template_step_image_asset(
                template_id,
                stage_id=stage_id,
                item_id=item_id,
                rel_path=rel_path,
                width=width,
                height=height,
            )
        except Exception:
            self._remove_workflow_image_asset(rel_path)
            raise

    def set_template_step_image_data(
        self,
        template_id: int,
        *,
        stage_id: str,
        item_id: str,
        image: QImage,
    ) -> WorkflowTemplateRow:
        self._require_template_step_target(template_id, stage_id=stage_id, item_id=item_id)
        rel_path, width, height = self.import_workflow_image_data(image)
        try:
            return self.set_template_step_image_asset(
                template_id,
                stage_id=stage_id,
                item_id=item_id,
                rel_path=rel_path,
                width=width,
                height=height,
            )
        except Exception:
            self._remove_workflow_image_asset(rel_path)
            raise

    def set_template_step_image_asset(
        self,
        template_id: int,
        *,
        stage_id: str,
        item_id: str,
        rel_path: str,
        width: int | None = None,
        height: int | None = None,
    ) -> WorkflowTemplateRow:
        template = self._repo.get_template(template_id)
        if template is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        clean_path = sanitize_user_text(rel_path, max_length=1000)
        if not clean_path:
            raise WorkRecordValidationError("work_record.asset.path_invalid")
        asset_path = self._safe_workflow_asset_path(clean_path)
        try:
            image_width, image_height = validate_image_file(asset_path)
        except (OSError, ImageGuardError) as exc:
            raise WorkRecordValidationError("work_record.asset.image_invalid") from exc
        stages = _loads_stages(template.stages_json)
        changed = False
        previous_path: str | None = None
        for stage in stages:
            if stage.get("id") != stage_id:
                continue
            for item in stage.get("items", []):
                if item.get("id") == item_id:
                    old_path = item.get("image_path")
                    previous_path = old_path if isinstance(old_path, str) else None
                    item["image_path"] = clean_path
                    item["image_width"] = int(width or image_width)
                    item["image_height"] = int(height or image_height)
                    changed = True
                    break
        if not changed:
            raise WorkRecordValidationError("work_record.step.not_found")
        with self._conn:
            updated = _require_row(
                self._repo.update_template_stages(
                    template.id,
                    name=template.name,
                    stages_json=_dumps_stages(stages),
                    bump_version=False,
                ),
                "work_record.template.not_found",
            )
            self._audit.record(
                action="work_record.workflow_template.step_image_update",
                target_type="workflow_template",
                target_id=str(template.id),
                detail={"stage_id": stage_id, "item_id": item_id, "has_image": True},
            )
        self._remove_asset_if_unreferenced(previous_path)
        return updated

    def _safe_workflow_asset_path(self, rel_path: str) -> Path:
        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise WorkRecordValidationError("work_record.asset.path_invalid")
        target = (self.workflow_assets_dir / rel).resolve()
        root = self.workflow_assets_dir.resolve()
        if root not in target.parents:
            raise WorkRecordValidationError("work_record.asset.path_invalid")
        if not target.is_file():
            raise WorkRecordValidationError("work_record.asset.not_found")
        return target

    def _require_template_step_target(
        self,
        template_id: int,
        *,
        stage_id: str,
        item_id: str,
    ) -> None:
        template = self._repo.get_template(template_id)
        if template is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        self._require_step_target(template.stages_json, stage_id=stage_id, item_id=item_id)

    def _require_run_step_target(
        self,
        run_id: int,
        *,
        stage_id: str,
        item_id: str,
    ) -> None:
        run = self._repo.get_run(run_id)
        if run is None:
            raise WorkRecordValidationError("work_record.run.not_found")
        self._require_step_target(run.stages_json, stage_id=stage_id, item_id=item_id)

    @staticmethod
    def _require_step_target(stages_json: str, *, stage_id: str, item_id: str) -> None:
        for stage in _loads_stages(stages_json):
            if stage.get("id") != stage_id:
                continue
            if any(item.get("id") == item_id for item in stage.get("items", [])):
                return
        raise WorkRecordValidationError("work_record.step.not_found")

    def delete_template(self, template_id: int) -> None:
        existing = self._repo.get_template(template_id)
        if existing is None:
            raise WorkRecordValidationError("work_record.template.not_found")
        asset_paths = self._image_paths(existing.context_snapshot, existing.stages_json)
        with self._conn:
            self._repo.soft_delete_template(template_id)
            self._audit.record(
                action="work_record.workflow_template.delete",
                target_type="workflow_template",
                target_id=str(template_id),
                detail={"name": existing.name},
            )
        self._cleanup_unreferenced_assets(asset_paths)

    def delete_run(self, run_id: int) -> None:
        existing = self._repo.get_run(run_id)
        if existing is None:
            raise WorkRecordValidationError("work_record.run.not_found")
        asset_paths = self._image_paths(existing.context_snapshot, existing.stages_json)
        with self._conn:
            self._repo.soft_delete_run(run_id)
            self._audit.record(
                action="work_record.workflow_run.delete",
                target_type="workflow_run",
                target_id=str(run_id),
                detail={"name": existing.name},
            )
        self._cleanup_unreferenced_assets(asset_paths)

    def rename_run(self, run_id: int, name: str) -> WorkflowRunRow:
        existing = self._repo.get_run(run_id)
        if existing is None:
            raise WorkRecordValidationError("work_record.run.not_found")
        clean_name = sanitize_user_text(name, max_length=200)
        if not clean_name:
            raise WorkRecordValidationError("work_record.run.name.required")
        with self._conn:
            updated = _require_row(
                self._repo.update_run_name(run_id, name=clean_name),
                "work_record.run.not_found",
            )
            self._audit.record(
                action="work_record.workflow_run.rename",
                target_type="workflow_run",
                target_id=str(run_id),
                detail={"name": updated.name, "previous_name": existing.name},
            )
        return updated

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
        with self._conn:
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
        with self._conn:
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

    def set_run_step_image_path(
        self,
        run_id: int,
        *,
        stage_id: str,
        item_id: str,
        image_path: str,
    ) -> WorkflowRunRow:
        self._require_run_step_target(run_id, stage_id=stage_id, item_id=item_id)
        rel_path, width, height = self.import_workflow_image_asset(Path(image_path))
        try:
            return self.set_run_step_image_asset(
                run_id,
                stage_id=stage_id,
                item_id=item_id,
                rel_path=rel_path,
                width=width,
                height=height,
            )
        except Exception:
            self._remove_workflow_image_asset(rel_path)
            raise

    def set_run_step_image_data(
        self,
        run_id: int,
        *,
        stage_id: str,
        item_id: str,
        image: QImage,
    ) -> WorkflowRunRow:
        self._require_run_step_target(run_id, stage_id=stage_id, item_id=item_id)
        rel_path, width, height = self.import_workflow_image_data(image)
        try:
            return self.set_run_step_image_asset(
                run_id,
                stage_id=stage_id,
                item_id=item_id,
                rel_path=rel_path,
                width=width,
                height=height,
            )
        except Exception:
            self._remove_workflow_image_asset(rel_path)
            raise

    def set_run_step_image_asset(
        self,
        run_id: int,
        *,
        stage_id: str,
        item_id: str,
        rel_path: str,
        width: int | None = None,
        height: int | None = None,
    ) -> WorkflowRunRow:
        run = self._repo.get_run(run_id)
        if run is None:
            raise WorkRecordValidationError("work_record.run.not_found")
        clean_path = sanitize_user_text(rel_path, max_length=1000)
        if not clean_path:
            raise WorkRecordValidationError("work_record.asset.path_invalid")
        asset_path = self._safe_workflow_asset_path(clean_path)
        try:
            image_width, image_height = validate_image_file(asset_path)
        except (OSError, ImageGuardError) as exc:
            raise WorkRecordValidationError("work_record.asset.image_invalid") from exc
        stages = _loads_stages(run.stages_json)
        changed = False
        previous_path: str | None = None
        for stage in stages:
            if stage.get("id") != stage_id:
                continue
            for item in stage.get("items", []):
                if item.get("id") == item_id:
                    old_path = item.get("image_path")
                    previous_path = old_path if isinstance(old_path, str) else None
                    item["image_path"] = clean_path
                    item["image_width"] = int(width or image_width)
                    item["image_height"] = int(height or image_height)
                    changed = True
                    break
        if not changed:
            raise WorkRecordValidationError("work_record.step.not_found")
        with self._conn:
            updated = _require_row(
                self._repo.update_run_stages(run.id, stages_json=_dumps_stages(stages)),
                "work_record.run.not_found",
            )
            self._audit.record(
                action="work_record.workflow_run.step_image_update",
                target_type="workflow_run",
                target_id=str(run.id),
                detail={"stage_id": stage_id, "item_id": item_id, "has_image": True},
            )
        self._remove_asset_if_unreferenced(previous_path)
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
        with self._conn:
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
        with self._conn:
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
        with self._conn:
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
        with self._conn:
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
