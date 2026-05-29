"""v0.19.0 Work Records workflow/error-review slice."""

from __future__ import annotations

import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog

from taxops.services.work_records import (
    CreateErrorReviewInput,
    CreateWorkflowTemplateInput,
    WorkflowStageInput,
    WorkflowStepInput,
    WorkRecordValidationError,
)
from taxops.ui.action_registry import PAGE_WORK_RECORDS, actions_for_page
from taxops.ui.pages.work_records_page import WorkRecordsPage


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_work_records_tables_exist(db_conn: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"workflow_templates_v2", "workflow_runs", "error_reviews"}.issubset(tables)


def test_create_template_and_instantiate_run_progress(container) -> None:
    template = container.work_records.create_template(
        CreateWorkflowTemplateInput(
            name="標準公司設立流程",
            stages=(
                WorkflowStageInput(
                    title="前期準備",
                    steps=(WorkflowStepInput("確認公司名稱"), WorkflowStepInput("收齊附件")),
                ),
            ),
        )
    )

    run = container.work_records.instantiate_run(template.id)
    done, total, percent = container.work_records.progress_for_stages_json(run.stages_json)

    assert run.template_id == template.id
    assert (done, total, percent) == (0, 2, 0)


def test_set_run_step_done_updates_progress_and_audit(container) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)
    stages = container.work_records.stages_for_row(run)
    first_stage = stages[0]
    first_item = first_stage["items"][0]

    updated = container.work_records.set_run_step_done(
        run.id,
        stage_id=first_stage["id"],
        item_id=first_item["id"],
        done=True,
    )

    assert container.work_records.progress_for_stages_json(updated.stages_json)[0] == 1
    row = container.conn.execute(
        "SELECT id FROM audit_logs WHERE action='work_record.workflow_run.step_update'"
    ).fetchone()
    assert row is not None


def test_run_can_overwrite_template_or_save_as_new_template(container) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)
    stages = container.work_records.stages_for_row(run)
    container.work_records.set_run_step_done(
        run.id,
        stage_id=stages[0]["id"],
        item_id=stages[0]["items"][0]["id"],
        done=True,
    )

    overwritten = container.work_records.overwrite_template_from_run(run.id)
    saved = container.work_records.save_run_as_template(run.id, "今年公司設立流程")

    assert overwritten.version == 2
    assert '"done":true' in overwritten.stages_json
    assert saved.id != overwritten.id
    assert saved.name == "今年公司設立流程"


def test_error_review_appends_guard_step_to_template(container) -> None:
    template = container.work_records.create_standard_company_setup_template()
    stage_id = container.work_records.stages_for_row(template)[1]["id"]

    review = container.work_records.create_error_review(
        CreateErrorReviewInput(
            title="附件漏收",
            phenomenon="送件前才發現缺附件",
            root_cause="內部沒有最後檢查點",
            severity="high",
            workflow_template_id=template.id,
            guard_stage_id=stage_id,
            guard_step_text="送件前再次檢查附件",
        )
    )
    updated = next(t for t in container.work_records.list_templates() if t.id == template.id)

    assert review.workflow_template_id == template.id
    assert updated.version == 2
    assert "送件前再次檢查附件" in updated.stages_json


def test_error_review_rejects_invalid_severity(container) -> None:
    with pytest.raises(WorkRecordValidationError) as ei:
        container.work_records.create_error_review(
            CreateErrorReviewInput(
                title="錯誤",
                phenomenon="現象",
                root_cause="原因",
                severity="critical",
            )
        )
    assert ei.value.code == "work_record.error.severity.invalid"


def test_work_records_page_has_three_tabs_and_writes_db(qapp, container, monkeypatch) -> None:
    page = WorkRecordsPage(container)

    assert [page._tabs.tabText(i) for i in range(page._tabs.count())] == [
        "流程",
        "筆記",
        "錯誤回顧",
    ]

    page._on_create_standard_template()
    page._templates_table.selectRow(0)
    page._on_instantiate_run()
    page._runs_table.selectRow(0)
    page._on_toggle_first_run_step()
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("另存測試範本", True),
    )
    page._on_save_run_as_template()

    assert page._templates_table.rowCount() == 2
    assert page._runs_table.rowCount() == 1


def test_work_records_action_registry_contracts() -> None:
    labels = {contract.button_label: contract for contract in actions_for_page(PAGE_WORK_RECORDS)}

    assert labels["建立標準公司設立流程"].service == (
        "WorkRecordsService.create_standard_company_setup_template"
    )
    assert labels["建立執行清單"].repository == "WorkRecordsRepository.insert_run"
    assert labels["勾選第一步"].audit_action == "work_record.workflow_run.step_update"
    assert labels["覆蓋回原範本"].service == "WorkRecordsService.overwrite_template_from_run"
    assert labels["另存為新範本"].repository == "WorkRecordsRepository.insert_template"
    assert labels["新增錯誤回顧並追加防呆"].audit_action == "work_record.error_review.create"
