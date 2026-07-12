"""v0.19.0 Work Records workflow/error-review slice."""

from __future__ import annotations

import os
import sqlite3
import json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QInputDialog,
    QMessageBox,
    QTabWidget,
    QTreeWidget,
)

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


def test_create_template_rejects_mismatched_client_and_engagement(container) -> None:
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput

    client_a = container.clients.create_client(CreateClientInput(
        client_code="CTX-A",
        client_name="Context client A",
    ))
    client_b = container.clients.create_client(CreateClientInput(
        client_code="CTX-B",
        client_name="Context client B",
    ))
    engagement_b = container.engagements.create_engagement(CreateEngagementInput(
        client_id=client_b.id,
        engagement_name="Context engagement B",
        tax_type="vat",
        period_name="2026-07",
    ))

    with pytest.raises(WorkRecordValidationError) as exc:
        container.work_records.create_template(CreateWorkflowTemplateInput(
            name="Cross-client dirty context",
            stages=(WorkflowStageInput(
                title="Stage",
                steps=(WorkflowStepInput("Step"),),
            ),),
            client_id=client_a.id,
            engagement_id=engagement_b.id,
        ))

    assert exc.value.code == "work_record.context_mismatch"
    assert container.conn.execute(
        "SELECT COUNT(*) FROM workflow_templates_v2"
        " WHERE name = 'Cross-client dirty context'"
    ).fetchone()[0] == 0
    assert container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs"
        " WHERE action = 'work_record.workflow_template.create'"
        "   AND detail_json LIKE '%Cross-client dirty context%'"
    ).fetchone()[0] == 0


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


def test_error_review_rejects_mismatched_client_and_engagement(container) -> None:
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput

    client_a = container.clients.create_client(CreateClientInput(
        client_code="ERR-CTX-A",
        client_name="Error context A",
    ))
    client_b = container.clients.create_client(CreateClientInput(
        client_code="ERR-CTX-B",
        client_name="Error context B",
    ))
    engagement_b = container.engagements.create_engagement(CreateEngagementInput(
        client_id=client_b.id,
        engagement_name="Error engagement B",
        tax_type="vat",
        period_name="2026-07",
    ))

    with pytest.raises(WorkRecordValidationError) as exc:
        container.work_records.create_error_review(CreateErrorReviewInput(
            title="Cross-client error review",
            phenomenon="Wrong context",
            root_cause="Missing ownership validation",
            severity="high",
            client_id=client_a.id,
            engagement_id=engagement_b.id,
        ))

    assert exc.value.code == "work_record.context_mismatch"
    assert container.conn.execute(
        "SELECT COUNT(*) FROM error_reviews"
        " WHERE title = 'Cross-client error review'"
    ).fetchone()[0] == 0


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


def test_work_records_page_single_workflow_surface_and_writes_db(qapp, container, monkeypatch) -> None:
    page = WorkRecordsPage(container)

    assert not page.findChildren(QTabWidget)
    assert isinstance(page._workflow_detail, QTreeWidget)
    assert not hasattr(page, "_notes_tab")
    assert not hasattr(page, "_errors_tab")

    page._on_create_standard_template()
    page._templates_table.selectRow(0)
    page._on_instantiate_run()
    page._runs_table.selectRow(0)
    page._update_workflow_detail()
    second_stage = page._workflow_detail.topLevelItem(2)
    selected_step = second_stage.child(0)
    page._workflow_detail.setCurrentItem(selected_step)
    page._on_toggle_selected_run_step()
    current = page._workflow_detail.currentItem()
    assert current is not None
    assert current.text(0) == "檢查身分證明文件"
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("另存測試範本", True),
    )
    page._on_save_run_as_template()

    assert page._templates_table.rowCount() == 2
    assert page._runs_table.rowCount() == 1
    run = container.work_records.list_runs()[0]
    stages = container.work_records.stages_for_row(run)
    assert stages[0]["items"][0]["done"] is False
    assert stages[1]["items"][0]["done"] is True


def test_work_records_template_image_import_stores_relative_asset(container, tmp_path) -> None:
    template = container.work_records.create_standard_company_setup_template()
    source = tmp_path / "source.png"
    image = QImage(32, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    assert image.save(str(source))

    updated = container.work_records.set_template_image_path(template.id, str(source))
    snapshot = json.loads(updated.context_snapshot)

    assert snapshot["image_path"].startswith("images/")
    assert not os.path.isabs(snapshot["image_path"])
    assert snapshot["image_width"] == 32
    assert snapshot["image_height"] == 24
    assert (container.work_records.workflow_assets_dir / snapshot["image_path"]).is_file()
    assert str(source) not in updated.context_snapshot


def test_replacing_template_image_removes_unreferenced_old_asset(
    container, tmp_path
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    sources = []
    for name, color in (("first.png", "red"), ("second.png", "blue")):
        source = tmp_path / name
        image = QImage(16, 12, QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        assert image.save(str(source))
        sources.append(source)

    first = container.work_records.set_template_image_path(
        template.id, str(sources[0])
    )
    first_path = container.work_records.workflow_assets_dir / json.loads(
        first.context_snapshot
    )["image_path"]
    assert first_path.is_file()

    second = container.work_records.set_template_image_path(
        template.id, str(sources[1])
    )
    second_path = container.work_records.workflow_assets_dir / json.loads(
        second.context_snapshot
    )["image_path"]

    assert not first_path.exists()
    assert second_path.is_file()


def test_delete_keeps_shared_image_until_last_reference_is_deleted(
    container, tmp_path
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    source = tmp_path / "shared.png"
    image = QImage(16, 12, QImage.Format.Format_ARGB32)
    image.fill(QColor("green"))
    assert image.save(str(source))
    updated = container.work_records.set_template_image_path(template.id, str(source))
    asset_path = container.work_records.workflow_assets_dir / json.loads(
        updated.context_snapshot
    )["image_path"]
    run = container.work_records.instantiate_run(template.id)

    container.work_records.delete_template(template.id)
    assert asset_path.is_file()

    container.work_records.delete_run(run.id)
    assert not asset_path.exists()


def test_delete_with_corrupt_active_workflow_keeps_asset_without_false_failure(
    container, tmp_path
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    source = tmp_path / "guarded.png"
    image = QImage(16, 12, QImage.Format.Format_ARGB32)
    image.fill(QColor("green"))
    assert image.save(str(source))
    updated = container.work_records.set_template_image_path(template.id, str(source))
    asset_path = container.work_records.workflow_assets_dir / json.loads(
        updated.context_snapshot
    )["image_path"]

    corrupt = container.work_records.create_template(
        CreateWorkflowTemplateInput(
            name="corrupt historical workflow",
            stages=(
                WorkflowStageInput(
                    title="stage",
                    steps=(WorkflowStepInput("item"),),
                ),
            ),
        )
    )
    container.conn.execute(
        "UPDATE workflow_templates_v2 SET stages_json = ? WHERE id = ?",
        ("{not-json", corrupt.id),
    )
    container.conn.commit()

    container.work_records.delete_template(template.id)

    deleted_at = container.conn.execute(
        "SELECT deleted_at FROM workflow_templates_v2 WHERE id = ?",
        (template.id,),
    ).fetchone()["deleted_at"]
    assert deleted_at is not None
    assert asset_path.is_file()


def test_work_records_step_image_path_validates_target_before_import(container, tmp_path) -> None:
    template = container.work_records.create_standard_company_setup_template()
    source = tmp_path / "source.png"
    image = QImage(12, 10, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    assert image.save(str(source))

    with pytest.raises(WorkRecordValidationError) as error:
        container.work_records.set_template_step_image_path(
            template.id,
            stage_id="missing-stage",
            item_id="missing-step",
            image_path=str(source),
        )

    assert error.value.code == "work_record.step.not_found"
    assert list(container.work_records.workflow_assets_dir.rglob("*")) == []


def test_work_records_image_copy_failure_leaves_no_formal_asset(
    container, tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.png"
    image = QImage(12, 10, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    assert image.save(str(source))

    def fail_after_partial_copy(_source, dest) -> None:
        Path(dest).write_bytes(b"partial")
        raise OSError("simulated copy failure")

    monkeypatch.setattr("taxops.services.work_records.shutil.copy2", fail_after_partial_copy)

    with pytest.raises(OSError, match="simulated copy failure"):
        container.work_records.import_workflow_image_asset(source)

    assert [path for path in container.work_records.workflow_assets_dir.rglob("*") if path.is_file()] == []


@pytest.mark.parametrize("failure_source", ["repository", "audit"])
def test_work_records_run_step_image_failure_leaves_no_orphan_asset(
    container, tmp_path, monkeypatch, failure_source
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)
    stages = container.work_records.stages_for_row(run)
    source = tmp_path / "source.png"
    image = QImage(12, 10, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    assert image.save(str(source))

    def fail(*_args, **_kwargs):
        raise RuntimeError(f"simulated {failure_source} failure")

    target = container.work_records._repo if failure_source == "repository" else container.work_records._audit
    method = "update_run_stages" if failure_source == "repository" else "record"
    monkeypatch.setattr(target, method, fail)

    with pytest.raises(RuntimeError, match=f"simulated {failure_source} failure"):
        container.work_records.set_run_step_image_path(
            run.id,
            stage_id=stages[0]["id"],
            item_id=stages[0]["items"][0]["id"],
            image_path=str(source),
        )

    assert [path for path in container.work_records.workflow_assets_dir.rglob("*") if path.is_file()] == []


def test_work_records_paste_screenshot_stores_relative_asset(qapp, container) -> None:
    template = container.work_records.create_standard_company_setup_template()
    page = WorkRecordsPage(container)
    page._templates_table.selectRow(0)
    image = QImage(20, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor("blue"))
    QApplication.clipboard().setPixmap(QPixmap.fromImage(image))

    page._on_paste_template_image()

    updated = next(t for t in container.work_records.list_templates() if t.id == template.id)
    snapshot = json.loads(updated.context_snapshot)
    assert snapshot["image_path"].startswith("images/")
    assert snapshot["image_width"] == 20
    assert snapshot["image_height"] == 16
    assert (container.work_records.workflow_assets_dir / snapshot["image_path"]).is_file()


def test_workflow_dialog_plain_lines_create_steps(qapp) -> None:
    from taxops.ui.dialogs.work_records_dialogs import WorkflowTemplateDialog

    dlg = WorkflowTemplateDialog(title="新增流程")
    dlg._name.setText("不用符號的流程")
    dlg._stages.setPlainText(
        "前期準備\n"
        "確認公司名稱\n"
        "確認負責人資料\n\n"
        "正式送件\n"
        "送出登記申請\n"
        "追蹤補件"
    )

    payload = dlg.payload()

    assert payload.stages[0].title == "前期準備"
    assert [step.text for step in payload.stages[0].steps] == [
        "確認公司名稱",
        "確認負責人資料",
    ]
    assert payload.stages[1].title == "正式送件"
    assert [step.text for step in payload.stages[1].steps] == [
        "送出登記申請",
        "追蹤補件",
    ]


def test_workflow_dialog_dash_steps_keep_legacy_stage_breaks_without_blank_line(qapp) -> None:
    from taxops.ui.dialogs.work_records_dialogs import WorkflowTemplateDialog

    dlg = WorkflowTemplateDialog(title="新增流程")
    dlg._name.setText("舊格式流程")
    dlg._stages.setPlainText(
        "前期準備\n"
        "- 確認公司名稱\n"
        "- 確認負責人資料\n"
        "正式送件\n"
        "- 送出登記申請"
    )

    payload = dlg.payload()

    assert [stage.title for stage in payload.stages] == ["前期準備", "正式送件"]
    assert [step.text for step in payload.stages[0].steps] == [
        "確認公司名稱",
        "確認負責人資料",
    ]
    assert [step.text for step in payload.stages[1].steps] == ["送出登記申請"]


@pytest.mark.parametrize(
    ("name", "stages_text", "error_code", "focused_field"),
    [
        ("", "前期準備\n確認公司名稱", "work_record.template.name.required", "_name"),
        ("有效流程", "", "work_record.stage.required", "_stages"),
    ],
)
def test_workflow_dialog_invalid_submit_stays_open_preserves_content_and_focuses_error(
    qapp, monkeypatch, name, stages_text, error_code, focused_field
) -> None:
    from taxops.ui.dialogs.work_records_dialogs import WorkflowTemplateDialog

    submitted = []

    def reject_invalid(payload) -> None:
        submitted.append(payload)
        raise WorkRecordValidationError(error_code)

    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)
    dlg = WorkflowTemplateDialog(title="新增流程", on_submit=reject_invalid)
    dlg._name.setText(name)
    dlg._stages.setPlainText(stages_text)
    dlg.show()
    QApplication.processEvents()

    dlg.accept()
    QApplication.processEvents()

    assert submitted
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert dlg.isVisible()
    assert dlg._name.text() == name
    assert dlg._stages.toPlainText() == stages_text
    assert getattr(dlg, focused_field).hasFocus()
    dlg.reject()


def test_work_records_rename_and_delete_run_writes_db_and_audit(container) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)

    renamed = container.work_records.rename_run(run.id, "公司設立執行 A")
    assert renamed.name == "公司設立執行 A"

    container.work_records.delete_run(run.id)
    assert container.work_records.list_runs() == []
    actions = [
        row["action"]
        for row in container.conn.execute(
            "SELECT action FROM audit_logs WHERE target_type='workflow_run'"
        ).fetchall()
    ]
    assert "work_record.workflow_run.rename" in actions
    assert "work_record.workflow_run.delete" in actions


def test_work_records_step_image_paste_stores_image_on_selected_run_step(qapp, container) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)
    page = WorkRecordsPage(container)
    page._runs_table.selectRow(0)
    page._update_workflow_detail()
    first_stage = page._workflow_detail.topLevelItem(1)
    first_step = first_stage.child(0)
    page._workflow_detail.setCurrentItem(first_step)

    image = QImage(28, 18, QImage.Format.Format_ARGB32)
    image.fill(QColor("green"))
    QApplication.clipboard().setPixmap(QPixmap.fromImage(image))
    page._on_paste_template_image()

    updated = next(r for r in container.work_records.list_runs() if r.id == run.id)
    stages = container.work_records.stages_for_row(updated)
    first_item = stages[0]["items"][0]
    assert first_item["image_path"].startswith("images/")
    assert first_item["image_width"] == 28
    assert first_item["image_height"] == 18
    assert (container.work_records.workflow_assets_dir / first_item["image_path"]).is_file()


def test_work_records_template_step_image_paste_targets_selected_step(qapp, container) -> None:
    template = container.work_records.create_standard_company_setup_template()
    page = WorkRecordsPage(container)
    page._templates_table.selectRow(0)
    page._update_workflow_detail()
    first_stage = page._workflow_detail.topLevelItem(1)
    first_step = first_stage.child(0)
    page._workflow_detail.setCurrentItem(first_step)

    image = QImage(30, 22, QImage.Format.Format_ARGB32)
    image.fill(QColor("yellow"))
    QApplication.clipboard().setPixmap(QPixmap.fromImage(image))
    page._on_paste_template_image()

    updated = next(t for t in container.work_records.list_templates() if t.id == template.id)
    stages = container.work_records.stages_for_row(updated)
    first_item = stages[0]["items"][0]
    assert first_item["image_path"].startswith("images/")
    assert first_item["image_width"] == 30
    assert first_item["image_height"] == 22
    assert (container.work_records.workflow_assets_dir / first_item["image_path"]).is_file()
    assert updated.context_snapshot is None


def test_work_records_run_buttons_are_connected_and_layout_prioritizes_detail(qapp, container) -> None:
    page = WorkRecordsPage(container)
    page.resize(640, 520)
    page.show()
    QApplication.processEvents()
    assert page._edit_run_btn.text() == "編輯執行"
    assert page._delete_run_btn.text() == "刪除執行"
    assert page._workflow_detail.minimumWidth() < 420
    assert page._workflow_image.minimumHeight() >= 260
    assert page._templates_table.columnWidth(1) >= 48
    assert page._runs_table.columnWidth(1) >= 48


def test_update_template_success_and_validation(container) -> None:
    service = container.work_records
    template = service.create_standard_company_setup_template()
    updated = service.update_template(
        template.id,
        CreateWorkflowTemplateInput(
            name="Updated workflow",
            stages=(
                WorkflowStageInput(
                    title="Updated stage",
                    steps=(WorkflowStepInput("Updated step"),),
                ),
            ),
        ),
    )
    assert updated.name == "Updated workflow"
    assert updated.version == template.version + 1

    with pytest.raises(WorkRecordValidationError) as missing:
        service.update_template(999999, CreateWorkflowTemplateInput(name="x", stages=()))
    assert missing.value.code == "work_record.template.not_found"

    with pytest.raises(WorkRecordValidationError) as blank:
        service.update_template(
            template.id,
            CreateWorkflowTemplateInput(name="   ", stages=()),
        )
    assert blank.value.code == "work_record.template.name.required"


@pytest.mark.parametrize(
    "payload, code",
    [
        (CreateWorkflowTemplateInput(name="No stages", stages=()), "work_record.stage.required"),
        (
            CreateWorkflowTemplateInput(
                name="Blank stage",
                stages=(WorkflowStageInput(title=" ", steps=()),),
            ),
            "work_record.stage.required",
        ),
    ],
)
def test_create_template_rejects_invalid_stage_shapes(container, payload, code) -> None:
    with pytest.raises(WorkRecordValidationError) as exc:
        container.work_records.create_template(payload)
    assert exc.value.code == code


def test_missing_run_template_and_step_targets_are_rejected(container) -> None:
    service = container.work_records
    with pytest.raises(WorkRecordValidationError) as instantiate:
        service.instantiate_run(999999)
    assert instantiate.value.code == "work_record.template.not_found"

    template = service.create_standard_company_setup_template()
    run = service.instantiate_run(template.id)
    stages = service.stages_for_row(run)
    stage_id = stages[0]["id"]
    item_id = stages[0]["items"][0]["id"]

    with pytest.raises(WorkRecordValidationError) as missing_run:
        service.set_run_step_done(
            999999, stage_id=stage_id, item_id=item_id, done=True
        )
    assert missing_run.value.code == "work_record.run.not_found"

    with pytest.raises(WorkRecordValidationError) as missing_step:
        service.set_run_step_done(
            run.id, stage_id=stage_id, item_id="missing", done=True
        )
    assert missing_step.value.code == "work_record.step.not_found"

    with pytest.raises(WorkRecordValidationError) as rename_missing:
        service.rename_run(999999, "name")
    assert rename_missing.value.code == "work_record.run.not_found"

    with pytest.raises(WorkRecordValidationError) as rename_blank:
        service.rename_run(run.id, "   ")
    assert rename_blank.value.code == "work_record.run.name.required"

    with pytest.raises(WorkRecordValidationError) as save_missing:
        service.save_run_as_template(999999, "name")
    assert save_missing.value.code == "work_record.run.not_found"

    with pytest.raises(WorkRecordValidationError) as save_blank:
        service.save_run_as_template(run.id, "   ")
    assert save_blank.value.code == "work_record.template.name.required"


def test_delete_missing_workflow_records_are_rejected(container) -> None:
    with pytest.raises(WorkRecordValidationError) as template_exc:
        container.work_records.delete_template(999999)
    assert template_exc.value.code == "work_record.template.not_found"

    with pytest.raises(WorkRecordValidationError) as run_exc:
        container.work_records.delete_run(999999)
    assert run_exc.value.code == "work_record.run.not_found"


def test_workflow_image_import_rejects_invalid_sources(container, tmp_path) -> None:
    invalid_extension = tmp_path / "image.txt"
    invalid_extension.write_text("not an image", encoding="utf-8")
    with pytest.raises(WorkRecordValidationError) as extension_exc:
        container.work_records.import_workflow_image_asset(invalid_extension)
    assert extension_exc.value.code == "work_record.asset.extension_invalid"

    with pytest.raises(WorkRecordValidationError) as missing_exc:
        container.work_records.import_workflow_image_asset(tmp_path / "missing.png")
    assert missing_exc.value.code == "work_record.asset.not_found"

    invalid_image = tmp_path / "invalid.png"
    invalid_image.write_bytes(b"not a png")
    with pytest.raises(WorkRecordValidationError) as image_exc:
        container.work_records.import_workflow_image_asset(invalid_image)
    assert image_exc.value.code == "work_record.asset.image_invalid"


@pytest.mark.usefixtures("qapp")
def test_workflow_toolbar_click_path_covers_full_run_lifecycle(
    container, monkeypatch, tmp_path
) -> None:
    page = WorkRecordsPage(container)
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    page._create_standard_btn.click()
    assert page._templates_table.rowCount() == 1
    page._templates_table.selectRow(0)

    image_path = tmp_path / "workflow-toolbar.png"
    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    image.fill(QColor("#CC3300"))
    assert image.save(str(image_path), "PNG")
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(image_path), ""),
    )
    page._set_template_image_btn.click()

    page._templates_table.selectRow(0)
    page._instantiate_btn.click()
    assert page._runs_table.rowCount() == 1
    page._runs_table.selectRow(0)

    answers = iter([("Renamed run", True), ("Saved from run", True)])
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QInputDialog.getText",
        lambda *_args, **_kwargs: next(answers),
    )
    page._edit_run_btn.click()
    assert container.work_records.list_runs()[0].name == "Renamed run"

    page._runs_table.selectRow(0)
    stage_item = next(
        page._workflow_detail.topLevelItem(index)
        for index in range(page._workflow_detail.topLevelItemCount())
        if page._workflow_detail.topLevelItem(index).childCount() > 0
    )
    page._workflow_detail.setCurrentItem(stage_item.child(0))
    page._toggle_first_btn.click()
    selected = page._selected_workflow_step()
    assert selected is not None and selected[3] is True

    page._overwrite_template_btn.click()
    page._runs_table.selectRow(0)
    page._save_as_template_btn.click()
    assert {row.name for row in container.work_records.list_templates()} >= {
        "Saved from run"
    }

    page._runs_table.selectRow(0)
    page._delete_run_btn.click()
    assert container.work_records.list_runs() == []

    page._templates_table.selectRow(0)
    page._delete_template_btn.click()
    assert page._templates_table.rowCount() == 1


@pytest.mark.usefixtures("qapp")
def test_work_records_empty_selection_actions_are_safe_noops(
    container, monkeypatch
) -> None:
    page = WorkRecordsPage(container)
    warnings = []
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QInputDialog.getText",
        lambda *_args, **_kwargs: ("", False),
    )

    page._on_edit_template()
    page._on_delete_template()
    page._on_edit_run()
    page._on_delete_run()
    page._on_set_template_image()
    page._on_paste_template_image()
    page._on_instantiate_run()
    page._on_overwrite_template()
    page._on_save_run_as_template()
    page._on_toggle_selected_run_step()

    assert len(warnings) == 1


def test_work_records_action_registry_contracts() -> None:
    labels = {contract.button_label: contract for contract in actions_for_page(PAGE_WORK_RECORDS)}

    assert labels["建立標準公司設立流程"].service == (
        "WorkRecordsService.create_standard_company_setup_template"
    )
    assert labels["新增流程"].service == "WorkRecordsService.create_template"
    assert labels["編輯流程"].service == "WorkRecordsService.update_template"
    assert labels["刪除流程"].repository == "WorkRecordsRepository.soft_delete_template"
    assert labels["編輯執行"].service == "WorkRecordsService.rename_run"
    assert labels["刪除執行"].repository == "WorkRecordsRepository.soft_delete_run"
    assert "update_run_stages" in labels["匯入流程圖片"].repository
    assert "set_run_step_image_asset" in labels["貼上截圖"].service
    assert "set_template_step_image_asset" in labels["貼上截圖"].service
    assert labels["建立執行清單"].repository == "WorkRecordsRepository.insert_run"
    assert labels["完成/取消完成選取步驟"].audit_action == "work_record.workflow_run.step_update"
    assert labels["覆蓋回原範本"].service == "WorkRecordsService.overwrite_template_from_run"
    assert labels["另存為新範本"].repository == "WorkRecordsRepository.insert_template"


def test_hidden_work_record_features_are_not_advertised_as_enabled_actions() -> None:
    labels = {contract.button_label: contract for contract in actions_for_page(PAGE_WORK_RECORDS)}

    for label in ("新增錯誤回顧並追加防呆", "新增筆記", "儲存畫布", "插入圖片", "匯出 PDF"):
        assert labels[label].enabled is False, f"{label} is hidden from users"


@pytest.mark.usefixtures("qapp")
def test_workflow_create_and_edit_buttons_use_real_dialog_fields_and_persist_audit(
    container, monkeypatch
) -> None:
    from taxops.ui.dialogs.work_records_dialogs import WorkflowTemplateDialog

    class SubmittedWorkflowDialog(WorkflowTemplateDialog):
        def exec(self) -> int:
            if self.windowTitle() == "新增流程":
                self._name.setText("客戶報稅流程")
                self._stages.setPlainText("資料準備\n確認統編\n確認申報期間")
            else:
                assert self._name.text() == "客戶報稅流程"
                assert "確認統編" in self._stages.toPlainText()
                self._name.setText("客戶報稅流程（複核版）")
                self._stages.setPlainText("資料準備\n確認統編\n覆核申報期間")
            self.accept()
            return self.result()

    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.WorkflowTemplateDialog",
        SubmittedWorkflowDialog,
    )
    page = WorkRecordsPage(container)

    page._create_template_btn.click()
    assert page._templates_table.rowCount() == 1
    page._templates_table.selectRow(0)
    page._edit_template_btn.click()

    stored = container.work_records.list_templates()[0]
    assert stored.name == "客戶報稅流程（複核版）"
    assert "覆核申報期間" in stored.stages_json
    audit_actions = {
        row["action"]
        for row in container.conn.execute(
            "SELECT action FROM audit_logs WHERE target_type='workflow_template'"
        ).fetchall()
    }
    assert {
        "work_record.workflow_template.create",
        "work_record.workflow_template.update",
    }.issubset(audit_actions)


@pytest.mark.usefixtures("qapp")
def test_workflow_toolbar_cancel_and_invalid_image_paths_preserve_records(
    container, monkeypatch, tmp_path
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)
    page = WorkRecordsPage(container)
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QInputDialog.getText",
        lambda *_args, **_kwargs: ("不應寫入", False),
    )

    page._templates_table.selectRow(0)
    page._delete_template_btn.click()
    page._runs_table.selectRow(0)
    page._delete_run_btn.click()
    page._edit_run_btn.click()
    page._save_as_template_btn.click()

    invalid_image = tmp_path / "broken.png"
    invalid_image.write_bytes(b"not an image")
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(invalid_image), ""),
    )
    page._templates_table.selectRow(0)
    page._set_template_image_btn.click()

    QApplication.clipboard().clear()
    page._paste_template_image_btn.click()

    assert [row.id for row in container.work_records.list_templates()] == [template.id]
    assert [row.id for row in container.work_records.list_runs()] == [run.id]
    assert len(warnings) == 2


@pytest.mark.usefixtures("qapp")
def test_workflow_page_reports_stale_selection_service_failures(
    container, monkeypatch
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    page = WorkRecordsPage(container)
    page._templates_table.selectRow(0)
    container.work_records.delete_template(template.id)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QMessageBox.warning",
        lambda _parent, title, body: warnings.append((title, body)),
    )

    page._instantiate_btn.click()

    assert warnings and warnings[0][0] == "建立失敗"
    assert container.work_records.list_runs() == []


@pytest.mark.usefixtures("qapp")
def test_workflow_page_rejects_corrupt_and_unsafe_saved_image_references(
    container, tmp_path, monkeypatch
) -> None:
    page = WorkRecordsPage(container)
    assert page._template_image_path("not-json") is None
    assert page._template_image_path("[]") is None
    assert page._template_image_path("{}") is None
    assert page._template_image_path('{"image_path":"../secret.png"}') is None
    assert page._workflow_asset_path(None) is None
    assert page._workflow_asset_path("../secret.png") is None

    image_path = tmp_path / "preview.png"
    image = QImage(18, 12, QImage.Format.Format_ARGB32)
    image.fill(QColor("purple"))
    assert image.save(str(image_path), "PNG")
    page._set_workflow_image_path(image_path)
    shown: list[str] = []
    monkeypatch.setattr(QDialog, "exec", lambda dlg: shown.append(dlg.windowTitle()) or 0)
    page._workflow_image.mousePressEvent(None)
    assert shown == ["圖片預覽"]


def test_workflow_context_resolution_rejects_deleted_or_unknown_owners(container) -> None:
    payload = CreateWorkflowTemplateInput(
        name="未知客戶流程",
        stages=(WorkflowStageInput("準備", (WorkflowStepInput("確認資料"),)),),
        client_id=999999,
    )
    with pytest.raises(WorkRecordValidationError) as client_error:
        container.work_records.create_template(payload)
    assert client_error.value.code == "work_record.context_not_found"

    payload = CreateWorkflowTemplateInput(
        name="未知案件流程",
        stages=(WorkflowStageInput("準備", (WorkflowStepInput("確認資料"),)),),
        engagement_id=999999,
    )
    with pytest.raises(WorkRecordValidationError) as engagement_error:
        container.work_records.create_template(payload)
    assert engagement_error.value.code == "work_record.context_not_found"


def test_workflow_asset_guards_reject_unavailable_unsafe_missing_and_invalid_data(
    container, monkeypatch
) -> None:
    service = container.work_records
    original_dir = service._workflow_assets_dir
    monkeypatch.setattr(service, "_workflow_assets_dir", None)
    with pytest.raises(WorkRecordValidationError) as unavailable:
        _ = service.workflow_assets_dir
    assert unavailable.value.code == "work_record.asset.storage_unavailable"
    monkeypatch.setattr(service, "_workflow_assets_dir", original_dir)

    with pytest.raises(WorkRecordValidationError) as unsafe:
        service._safe_workflow_asset_path("../outside.png")
    assert unsafe.value.code == "work_record.asset.path_invalid"
    with pytest.raises(WorkRecordValidationError) as missing:
        service._safe_workflow_asset_path("images/missing.png")
    assert missing.value.code == "work_record.asset.not_found"
    with pytest.raises(WorkRecordValidationError) as invalid:
        service.import_workflow_image_data(QImage())
    assert invalid.value.code == "work_record.asset.image_invalid"


def test_workflow_corrupt_stages_are_rejected_without_writes(container) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)
    container.conn.execute(
        "UPDATE workflow_runs SET stages_json = ? WHERE id = ?",
        ("{corrupt", run.id),
    )
    container.conn.commit()

    with pytest.raises(WorkRecordValidationError) as progress_error:
        container.work_records.progress_for_stages_json("{corrupt")
    assert progress_error.value.code == "work_record.stages.invalid"
    with pytest.raises(WorkRecordValidationError) as update_error:
        container.work_records.set_run_step_done(
            run.id, stage_id="stage", item_id="step", done=True
        )
    assert update_error.value.code == "work_record.stages.invalid"
    assert container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action='work_record.workflow_run.step_update'"
    ).fetchone()[0] == 0


def test_workflow_stale_template_relations_are_rejected(container) -> None:
    service = container.work_records
    template = service.create_standard_company_setup_template()
    run = service.instantiate_run(template.id)
    container.conn.execute(
        "UPDATE workflow_runs SET template_id = NULL WHERE id = ?",
        (run.id,),
    )
    container.conn.commit()
    with pytest.raises(WorkRecordValidationError) as detached:
        service.overwrite_template_from_run(run.id)
    assert detached.value.code == "work_record.template.not_found"

    linked_run = service.instantiate_run(template.id)
    service.delete_template(template.id)
    with pytest.raises(WorkRecordValidationError) as deleted:
        service.overwrite_template_from_run(linked_run.id)
    assert deleted.value.code == "work_record.template.not_found"


def test_workflow_step_image_targets_validate_before_creating_assets(
    container, tmp_path
) -> None:
    source = tmp_path / "step.png"
    image = QImage(10, 10, QImage.Format.Format_ARGB32)
    image.fill(QColor("orange"))
    assert image.save(str(source), "PNG")
    service = container.work_records

    with pytest.raises(WorkRecordValidationError) as missing_template:
        service.set_template_step_image_path(
            999999, stage_id="stage", item_id="step", image_path=str(source)
        )
    assert missing_template.value.code == "work_record.template.not_found"
    with pytest.raises(WorkRecordValidationError) as missing_run:
        service.set_run_step_image_path(
            999999, stage_id="stage", item_id="step", image_path=str(source)
        )
    assert missing_run.value.code == "work_record.run.not_found"
    assert not list(service.workflow_assets_dir.rglob("*.png"))


@pytest.mark.usefixtures("qapp")
def test_workflow_selected_step_file_button_persists_template_and_run_assets(
    container, tmp_path, monkeypatch
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)
    source = tmp_path / "selected-step.png"
    image = QImage(14, 11, QImage.Format.Format_ARGB32)
    image.fill(QColor("cyan"))
    assert image.save(str(source), "PNG")
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )
    page = WorkRecordsPage(container)

    page._templates_table.selectRow(0)
    template_stage = page._workflow_detail.topLevelItem(1)
    page._workflow_detail.setCurrentItem(template_stage.child(0))
    page._set_template_image_btn.click()
    template_after = next(t for t in container.work_records.list_templates() if t.id == template.id)
    template_step = container.work_records.stages_for_row(template_after)[0]["items"][0]
    assert template_step["image_width"] == 14
    assert template_step["image_height"] == 11

    page._runs_table.selectRow(0)
    run_stage = page._workflow_detail.topLevelItem(1)
    page._workflow_detail.setCurrentItem(run_stage.child(0))
    page._set_template_image_btn.click()
    run_after = next(r for r in container.work_records.list_runs() if r.id == run.id)
    run_step = container.work_records.stages_for_row(run_after)[0]["items"][0]
    assert run_step["image_width"] == 14
    assert run_step["image_height"] == 11
    assert run_step["image_path"] != template_step["image_path"]
    actions = {
        row["action"]
        for row in container.conn.execute(
            "SELECT action FROM audit_logs WHERE action LIKE '%step_image_update'"
        ).fetchall()
    }
    assert actions == {
        "work_record.workflow_template.step_image_update",
        "work_record.workflow_run.step_image_update",
    }


def test_workflow_clearing_template_image_removes_unreferenced_asset(
    container, tmp_path
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    source = tmp_path / "main.png"
    image = QImage(13, 9, QImage.Format.Format_ARGB32)
    image.fill(QColor("magenta"))
    assert image.save(str(source), "PNG")

    with_image = container.work_records.set_template_image_path(template.id, str(source))
    rel_path = json.loads(with_image.context_snapshot)["image_path"]
    asset = container.work_records.workflow_assets_dir / rel_path
    assert asset.is_file()

    cleared = container.work_records.set_template_image_path(template.id, None)
    assert cleared.context_snapshot is None
    assert not asset.exists()


@pytest.mark.usefixtures("qapp")
def test_workflow_real_dialog_cancel_does_not_create_or_edit(container, monkeypatch) -> None:
    from taxops.ui.dialogs.work_records_dialogs import WorkflowTemplateDialog

    class CancelledWorkflowDialog(WorkflowTemplateDialog):
        def exec(self) -> int:
            self._name.setText("取消後不應儲存")
            self._stages.setPlainText("階段\n步驟")
            self.reject()
            return self.result()

    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.WorkflowTemplateDialog",
        CancelledWorkflowDialog,
    )
    page = WorkRecordsPage(container)
    page._create_template_btn.click()
    assert container.work_records.list_templates() == []

    existing = container.work_records.create_standard_company_setup_template()
    page.refresh_context()
    page._templates_table.selectRow(0)
    page._edit_template_btn.click()
    unchanged = container.work_records.list_templates()[0]
    assert unchanged.id == existing.id
    assert unchanged.name == "標準公司設立流程"
    assert unchanged.version == existing.version


@pytest.mark.usefixtures("qapp")
def test_workflow_toolbar_shows_service_validation_failures(
    container, monkeypatch
) -> None:
    template = container.work_records.create_standard_company_setup_template()
    run = container.work_records.instantiate_run(template.id)
    page = WorkRecordsPage(container)
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QMessageBox.warning",
        lambda _parent, title, _body: warnings.append(title),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    page._templates_table.selectRow(0)
    monkeypatch.setattr(
        container.work_records,
        "delete_template",
        lambda _id: (_ for _ in ()).throw(
            WorkRecordValidationError("work_record.template.not_found")
        ),
    )
    page._delete_template_btn.click()

    page._runs_table.selectRow(0)
    monkeypatch.setattr(
        container.work_records,
        "delete_run",
        lambda _id: (_ for _ in ()).throw(
            WorkRecordValidationError("work_record.run.not_found")
        ),
    )
    page._delete_run_btn.click()
    monkeypatch.setattr(
        container.work_records,
        "overwrite_template_from_run",
        lambda _id: (_ for _ in ()).throw(
            WorkRecordValidationError("work_record.template.not_found")
        ),
    )
    page._overwrite_template_btn.click()
    monkeypatch.setattr(
        "taxops.ui.pages.work_records_page.QInputDialog.getText",
        lambda *_args, **_kwargs: ("", True),
    )
    page._save_as_template_btn.click()

    assert warnings == ["刪除失敗", "刪除失敗", "覆蓋失敗", "另存失敗"]
    assert [row.id for row in container.work_records.list_templates()] == [template.id]
    assert [row.id for row in container.work_records.list_runs()] == [run.id]
