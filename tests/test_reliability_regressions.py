"""Synthetic round-trips and ordinary failure injection for reliability fixes."""

from __future__ import annotations

import errno
import itertools
import json
import sqlite3
import time
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from taxops.core.paths import resolve_paths
from taxops.services.attachments import UploadAttachmentInput
from taxops.services.backup import BackupError
from taxops.services.canvas_notes import CreateCanvasNoteInput
from taxops.services.clients import CreateClientInput
from taxops.services.document_requests import (
    CreateDocumentRequestInput,
    VALID_ITEM_STATUSES,
    _derive_request_status,
)
from taxops.services.engagements import CreateEngagementInput
from taxops.services.registry.parser import EXPECTED_HEADERS
from taxops.services.work_records import (
    CreateWorkflowTemplateInput,
    WorkflowStageInput,
    WorkflowStepInput,
)
from taxops.ui.app import bootstrap
from taxops.ui.pages.settings_page import SettingsPage


@pytest.fixture
def containers(tmp_path):
    opened = []

    def make(name):
        container = bootstrap(resolve_paths(override_root=tmp_path / name))
        opened.append(container)
        return container

    yield make
    for container in opened:
        container.close()


def seed(container):
    client = container.clients.create_client(CreateClientInput("R001", "合成測試客戶"))
    engagement = container.engagements.create_engagement(
        CreateEngagementInput(client.id, "合成案件", "vat", "2026-10")
    )
    request, _ = container.doc_requests.create_request(
        CreateDocumentRequestInput(engagement.id, "vat", "2026-10")
    )
    return client, engagement, request


def add_attachment(container, tmp_path, engagement_id):
    source = tmp_path / "合成文件.txt"
    source.write_text("synthetic document bytes", encoding="utf-8")
    row = container.attachments.upload_attachment(
        UploadAttachmentInput(engagement_id, None, source)
    )
    container.attachments.accept_attachment(row.id)
    return row, source.read_bytes()


def db_rows(container, table):
    with closing(sqlite3.connect(container.paths.db_path)) as connection:
        return connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def test_full_backup_button_restores_all_asset_kinds_to_fresh_root(
    containers,
    tmp_path,
    qapp,
    monkeypatch,
):
    source = containers("source")
    _, engagement, _ = seed(source)
    attachment, expected_attachment = add_attachment(source, tmp_path, engagement.id)
    image_path = tmp_path / "synthetic.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    assert image.save(str(image_path))
    expected_image = image_path.read_bytes()
    template = source.work_records.create_template(
        CreateWorkflowTemplateInput(
            "合成流程",
            (WorkflowStageInput("階段", (WorkflowStepInput("步驟"),)),),
        )
    )
    source.work_records.set_template_image_path(template.id, str(image_path))
    template = source.work_records.list_templates()[0]
    stage = json.loads(template.stages_json)[0]
    source.work_records.set_template_step_image_path(
        template.id,
        stage_id=stage["id"],
        item_id=stage["items"][0]["id"],
        image_path=str(image_path),
    )
    source.work_records.instantiate_run(template.id)
    note = source.canvas_notes.create_note(CreateCanvasNoteInput("合成筆記"))
    relative = source.canvas_notes.import_image_asset(image_path)
    scene = json.loads(note.scene_json)
    scene["objects"].append({"type": "image", "asset_path": relative})
    source.canvas_notes.update_note(
        note.id, title=note.title, scene_json=json.dumps(scene)
    )
    infos = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args: infos.append(args[1:3])
    )
    page = SettingsPage(source)
    page._backup_btn.click()
    assert infos and "完整備份" in infos[0][1]
    archives = list(source.paths.backups_dir.glob("*.taxops.zip"))
    assert len(archives) == 1
    target = containers("target")
    target.backup.restore_backup(archives[0], target.paths)
    assert (
        target.attachments.resolve_file_path(attachment.id).read_bytes()
        == expected_attachment
    )
    assert target.attachments.get(attachment.id).status == "accepted"
    restored_template = target.work_records.list_templates()[0]
    restored_run = target.work_records.list_runs()[0]
    for record in (restored_template, restored_run):
        snapshot = json.loads(record.context_snapshot)
        assert (
            target.work_records.workflow_assets_dir / snapshot["image_path"]
        ).read_bytes() == expected_image
        stages = json.loads(record.stages_json)
        assert (
            target.work_records.workflow_assets_dir
            / stages[0]["items"][0]["image_path"]
        ).read_bytes() == expected_image
    restored_note = target.canvas_notes.get_note(note.id)
    restored_image = json.loads(restored_note.scene_json)["objects"][0]["asset_path"]
    assert (
        target.canvas_notes.note_assets_dir / restored_image
    ).read_bytes() == expected_image
    journal = json.loads(
        next((target.paths.data_root / "restore_history").glob("*.json")).read_text()
    )
    assert (
        journal["state"] == "committed" and journal["mapping"] and journal["references"]
    )
    assert any(
        journal["restore_id"] in row[-2]
        for row in db_rows(target, "audit_logs")
        if row[-2]
    )
    assert target.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    page.close()


def test_repeated_restore_retains_previous_assets_and_bounded_reference_paths(
    containers, tmp_path
):
    source = containers("source")
    _, engagement, _ = seed(source)
    attachment, expected = add_attachment(source, tmp_path, engagement.id)
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    original = source.attachments.resolve_file_path(attachment.id)
    source.backup.restore_backup(archive, source.paths)
    first = source.attachments.resolve_file_path(attachment.id)
    source.backup.restore_backup(archive, source.paths)
    second = source.attachments.resolve_file_path(attachment.id)
    assert len({original, first, second}) == 3
    assert all(path.read_bytes() == expected for path in (original, first, second))
    assert len(second.relative_to(source.paths.attachments_dir).parts) == 2
    journals = list((source.paths.data_root / "restore_history").glob("*.json"))
    assert len(journals) == 2
    assert all(
        json.loads(path.read_text())["state"] == "committed" for path in journals
    )


def test_missing_current_asset_prevents_full_backup_without_success_record(
    containers, tmp_path
):
    source = containers("source")
    _, engagement, _ = seed(source)
    attachment, _ = add_attachment(source, tmp_path, engagement.id)
    source.attachments.resolve_file_path(attachment.id).unlink()
    previous = db_rows(source, "audit_logs")
    with pytest.raises(BackupError, match="backup.assets.incomplete"):
        source.backup.create_backup(source.paths)
    assert db_rows(source, "audit_logs") == previous
    assert not list(source.paths.backups_dir.glob("*.taxops.zip"))


def test_incomplete_bundle_is_rejected_before_live_database_changes(
    containers, tmp_path
):
    source = containers("source")
    _, engagement, _ = seed(source)
    add_attachment(source, tmp_path, engagement.id)
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    incomplete = tmp_path / "incomplete.taxops.zip"
    # Simulate an interrupted packaging/transfer that lost one regular member.
    with zipfile.ZipFile(archive) as before, zipfile.ZipFile(incomplete, "w") as after:
        for name in before.namelist():
            if not name.startswith("attachments/"):
                after.writestr(name, before.read(name))
    target = containers("target")
    target.clients.create_client(CreateClientInput("KEEP", "保留客戶"))
    previous = db_rows(target, "clients")
    with pytest.raises(BackupError, match="backup.assets.incomplete"):
        target.backup.restore_backup(incomplete, target.paths)
    assert db_rows(target, "clients") == previous
    assert not (target.paths.data_root / "restore_history").exists()


def test_asset_copy_disk_error_keeps_live_database_and_old_files(
    containers, tmp_path, monkeypatch
):
    source = containers("source")
    _, engagement, _ = seed(source)
    attachment, _ = add_attachment(source, tmp_path, engagement.id)
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    target = containers("target")
    _, old_engagement, _ = seed(target)
    old_attachment, old_bytes = add_attachment(target, tmp_path, old_engagement.id)
    old_path = target.attachments.resolve_file_path(old_attachment.id)
    previous = db_rows(target, "audit_logs")

    def disk_full(source_path, destination):
        Path(destination).write_bytes(b"partial")
        raise OSError(errno.ENOSPC, "synthetic disk full")

    monkeypatch.setattr("taxops.services.backup_bundle.shutil.copyfile", disk_full)
    with pytest.raises(BackupError, match="backup.restore.failed"):
        target.backup.restore_backup(archive, target.paths)
    assert db_rows(target, "audit_logs") == previous
    assert target.attachments.resolve_file_path(old_attachment.id) == old_path
    assert old_path.read_bytes() == old_bytes
    journal = json.loads(
        next((target.paths.data_root / "restore_history").glob("*.json")).read_text()
    )
    assert journal["state"] == "failed_before_commit"
    assert journal["namespaces"] and journal["source_files"] and journal["references"]


def test_legacy_snapshot_warning_and_restore_preserve_existing_assets(
    containers, tmp_path, qapp, monkeypatch
):
    container = containers("data")
    _, engagement, _ = seed(container)
    attachment, expected = add_attachment(container, tmp_path, engagement.id)
    original = container.attachments.resolve_file_path(attachment.id)
    legacy = Path(
        container.backup.create_database_snapshot(container.paths).backup_path
    )
    questions = []
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.QFileDialog.getOpenFileName",
        lambda *a: (str(legacy), ""),
    )

    def confirm(parent, title, body, *args):
        questions.append(body)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    page = SettingsPage(container)
    page._restore_btn.click()
    assert any("不包含附件或圖片" in body for body in questions)
    assert container.attachments.resolve_file_path(attachment.id) == original
    assert original.read_bytes() == expected
    page.close()


def test_bulk_dialog_invalid_middle_row_and_retry_leave_no_rows(
    containers, qapp, monkeypatch
):
    from taxops.ui.dialogs.add_document_item_dialog import AddDocumentItemDialog

    container = containers("bulk")
    _, _, request = seed(container)
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args: warnings.append(args[1:3])
    )
    dialog = AddDocumentItemDialog(container.doc_requests, request.id)
    dialog._text_edit.setPlainText("進項憑證\n\u200b\n銀行存摺")
    before = db_rows(container, "audit_logs")
    for _ in range(2):
        dialog._ok_btn.click()
        assert db_rows(container, "document_request_items") == []
        assert db_rows(container, "audit_logs") == before
    assert len(warnings) == 2 and dialog.result() == 0
    dialog._text_edit.setPlainText("進項憑證\n銀行存摺")
    dialog._ok_btn.click()
    assert [
        item.item_name for item in container.doc_requests.list_items(request.id)
    ] == ["進項憑證", "銀行存摺"]
    dialog.close()


def test_bulk_audit_failure_rolls_back_all_items_and_parent_status(
    containers, monkeypatch
):
    container = containers("audit_failure")
    _, _, request = seed(container)
    before = db_rows(container, "audit_logs")
    record = container.audit.record
    calls = 0

    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("synthetic audit write failure")
        return record(**kwargs)

    monkeypatch.setattr(container.audit, "record", fail_second)
    with pytest.raises(sqlite3.OperationalError):
        container.doc_requests.add_items_bulk(request.id, "項目一\n項目二\n項目三")
    assert db_rows(container, "document_request_items") == []
    assert db_rows(container, "audit_logs") == before
    assert container.doc_requests.get_request(request.id).status == "not_requested"


@pytest.mark.parametrize(
    "first,second", itertools.product(sorted(VALID_ITEM_STATUSES), repeat=2)
)
def test_document_status_pair_matrix(first, second):
    states = {first, second}
    resolved = {"accepted", "not_applicable", "client_said_none"}
    if states <= resolved:
        expected = "accepted"
    elif "pending_confirm" in states:
        expected = "pending_confirm"
    elif states & {"invalid", "incomplete"}:
        expected = "under_validation"
    elif states & {"received", "accepted", "not_applicable", "client_said_none"}:
        expected = "partially_received"
    else:
        expected = "requested"
    assert _derive_request_status(frozenset(states)) == expected


def test_accepting_received_item_preserves_partial_progress(containers):
    container = containers("status")
    _, _, request = seed(container)
    items = container.doc_requests.add_items_bulk(request.id, "進項憑證\n銀行存摺")
    container.doc_requests.mark_requested(request.id)
    container.doc_requests.set_item_status(items[0].id, item_status="received")
    assert container.doc_requests.get_request(request.id).status == "partially_received"
    container.doc_requests.set_item_status(items[0].id, item_status="accepted")
    assert container.doc_requests.get_request(request.id).status == "partially_received"


def write_synthetic_registry(path):
    row = [
        "合成地址",
        "12345678",
        "",
        "合成商號",
        "1000",
        "1150101",
        "獨資",
        "Y",
        "123456",
        "合成業別",
        "",
        "",
        "",
        "",
        "",
        "",
    ]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "BGMOPEN1.csv", ",".join(EXPECTED_HEADERS) + "\n" + ",".join(row) + "\n"
        )


def test_download_button_persists_provenance_after_real_worker_closes(
    containers, qapp, monkeypatch
):
    container = containers("download")
    monkeypatch.setattr(
        "taxops.ui.pages.settings_page.download_registry_zip",
        lambda url, dest: write_synthetic_registry(dest),
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes
    )
    infos, errors = [], []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[1:3]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: errors.append(a[1:3]))
    page = SettingsPage(container)
    page._download_btn.click()
    worker = page._active_worker
    assert worker is not None
    deadline = time.monotonic() + 10
    while page._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    assert page._active_worker is None
    assert not errors and infos
    with closing(sqlite3.connect(container.paths.db_path)) as connection:
        actions = [
            row[0] for row in connection.execute("SELECT action FROM audit_logs")
        ]
        metadata = dict(connection.execute("SELECT key, value FROM tax_cache_metadata"))
    assert actions.count("tax_cache.download") == 1
    assert actions.count("tax_cache.import.zip") == 1
    assert metadata["source_url"] == "https://eip.fia.gov.tw/data/BGMOPEN1.zip"
    assert not (container.paths.data_root / "_registry_download_tmp.zip").exists()
    page.close()
    page.deleteLater()
    # Flush only the widget owned by this test, not unrelated queued deletes
    # from other modules' Qt fixtures in the aggregate suite.
    QCoreApplication.sendPostedEvents(page, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_download_audit_failure_rolls_back_import_and_metadata(
    containers, tmp_path, monkeypatch
):
    container = containers("download_failure")
    synthetic = tmp_path / "registry.zip"
    write_synthetic_registry(synthetic)
    before_logs = db_rows(container, "audit_logs")
    record = container.audit.record

    def fail_download(**kwargs):
        if kwargs["action"] == "tax_cache.download":
            raise sqlite3.OperationalError("synthetic audit failure")
        return record(**kwargs)

    monkeypatch.setattr(container.audit, "record", fail_download)
    with pytest.raises(Exception, match="registry.import.failed"):
        container.tax_cache_importer.import_zip(
            synthetic,
            source_url="https://eip.fia.gov.tw/data/BGMOPEN1.zip",
            record_download=True,
        )
    assert container.tax_registry_repo.count() == 0
    assert container.tax_cache_metadata_repo.get_all() == {}
    assert db_rows(container, "audit_logs") == before_logs


def test_restore_audit_failure_retains_recovery_files_without_replacing_database(
    containers,
    tmp_path,
    monkeypatch,
):
    from taxops.services.audit import AuditService

    source = containers("source")
    _, engagement, _ = seed(source)
    add_attachment(source, tmp_path, engagement.id)
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    target = containers("target")
    target.clients.create_client(CreateClientInput("KEEP", "保留客戶"))
    previous = db_rows(target, "clients")
    record = AuditService.record

    def fail_restore(self, **kwargs):
        if kwargs["action"] == "backup.restore":
            raise sqlite3.OperationalError("synthetic audit failure")
        return record(self, **kwargs)

    monkeypatch.setattr(AuditService, "record", fail_restore)
    with pytest.raises(BackupError, match="backup.restore.failed"):
        target.backup.restore_backup(archive, target.paths)
    assert db_rows(target, "clients") == previous
    journal = json.loads(
        next((target.paths.data_root / "restore_history").glob("*.json")).read_text()
    )
    assert journal["state"] == "failed_before_commit"
    assert journal["planned_mapping"] == journal["mapping"]
    assert list(target.paths.attachments_dir.glob("restored_*/*"))


def test_full_backup_audit_failure_removes_only_new_archive(containers, monkeypatch):
    container = containers("data")
    existing = Path(container.backup.create_backup(container.paths).backup_path)
    before = existing.read_bytes()
    record = container.audit.record

    def fail_create(**kwargs):
        if kwargs["action"] == "backup.create":
            raise sqlite3.OperationalError("synthetic audit failure")
        return record(**kwargs)

    monkeypatch.setattr(container.audit, "record", fail_create)
    with pytest.raises(BackupError, match="backup.create.failed"):
        container.backup.create_backup(container.paths)
    assert existing.read_bytes() == before
    assert list(container.paths.backups_dir.glob("*.taxops.zip")) == [existing]
