"""Small normal compatibility and recovery regressions.

The first five cases originated in the independent repair review and are now
part of the repository suite. Fault injection below uses small local fixtures;
it does not fill the disk, perform network requests or exercise attack inputs.
"""

from contextlib import closing

import json

from pathlib import Path

import sqlite3


import pytest


from PySide6.QtGui import QImage


from taxops.core.paths import resolve_paths

from taxops.services.attachments import UploadAttachmentInput

from taxops.services.backup import BackupError

from taxops.services.canvas_notes import CreateCanvasNoteInput

from taxops.services.clients import CreateClientInput

from taxops.services.document_requests import CreateDocumentRequestInput

from taxops.services.engagements import CreateEngagementInput


from taxops.services.work_records import (
    CreateWorkflowTemplateInput,
    WorkflowStageInput,
    WorkflowStepInput,
)

from taxops.ui.app import bootstrap


@pytest.fixture
def opened(tmp_path):
    values = []

    def create(name):
        value = bootstrap(resolve_paths(override_root=tmp_path / name))
        values.append(value)
        return value

    yield create
    for value in values:
        value.close()


def seed(value, code="SYNTH"):
    client = value.clients.create_client(CreateClientInput(code, "合成客戶"))
    engagement = value.engagements.create_engagement(
        CreateEngagementInput(client.id, "合成案件", "vat", "2026-10")
    )
    request, _ = value.doc_requests.create_request(
        CreateDocumentRequestInput(engagement.id, "vat", "2026-10")
    )
    return engagement, request


def attachment(value, root, engagement):
    source = root / "document.txt"
    source.write_text("Synthetic evidence bytes.\n", encoding="utf-8")
    row = value.attachments.upload_attachment(
        UploadAttachmentInput(engagement.id, None, source)
    )
    value.attachments.accept_attachment(row.id)
    return row, source.read_bytes()


def image(root):
    path = root / "small.png"
    data = QImage(8, 8, QImage.Format.Format_RGB32)
    data.fill(0xAB7654)
    assert data.save(str(path))
    return path


def rows(value, table):
    with closing(sqlite3.connect(value.paths.db_path)) as connection:
        return connection.execute("SELECT * FROM " + table + " ORDER BY id").fetchall()


def test_windows_style_attachment_references_roundtrip_reopen_and_rebackup(
    opened, tmp_path, qapp
):
    source = opened("source")
    engagement, _ = seed(source)
    row, expected = attachment(source, tmp_path, engagement)
    # Match the separators persisted by the ordinary Windows upload service.
    with source.conn:
        source.conn.execute(
            "UPDATE attachments SET stored_filename=? WHERE id=?",
            (row.stored_filename.replace("/", "\\"), row.id),
        )
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    first = opened("first")
    first.backup.restore_backup(archive, first.paths)
    assert first.attachments.resolve_file_path(row.id).read_bytes() == expected
    paths = first.paths
    first.close()
    restarted = bootstrap(paths)
    try:
        assert restarted.attachments.get(row.id).status == "accepted"
        assert restarted.attachments.resolve_file_path(row.id).read_bytes() == expected
        another = Path(restarted.backup.create_backup(paths).backup_path)
    finally:
        restarted.close()
    second = opened("second")
    second.backup.restore_backup(another, second.paths)
    assert second.attachments.resolve_file_path(row.id).read_bytes() == expected
    assert (
        len(
            second.attachments.resolve_file_path(row.id)
            .relative_to(second.paths.attachments_dir)
            .parts
        )
        == 2
    )


def test_workflow_run_survives_template_deletion_and_canvas_can_export_after_restore(
    opened, tmp_path, qapp
):
    source = opened("source")
    file = image(tmp_path)
    template = source.work_records.create_template(
        CreateWorkflowTemplateInput(
            "合成流程", (WorkflowStageInput("階段", (WorkflowStepInput("步驟"),)),)
        )
    )
    source.work_records.set_template_image_path(template.id, str(file))
    source.work_records.instantiate_run(template.id)
    source.work_records.delete_template(template.id)
    note = source.canvas_notes.create_note(CreateCanvasNoteInput("合成畫布"))
    relative = source.canvas_notes.import_image_asset(file)
    scene = json.loads(note.scene_json)
    scene["objects"].append(
        {
            "type": "image",
            "asset_path": relative,
            "x": 0,
            "y": 0,
            "width": 8,
            "height": 8,
        }
    )
    source.canvas_notes.update_note(
        note.id, title=note.title, scene_json=json.dumps(scene)
    )
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    target = opened("target")
    target.backup.restore_backup(archive, target.paths)
    actual_run = target.work_records.list_runs()[0]
    ref = json.loads(actual_run.context_snapshot)["image_path"]
    assert (
        target.work_records.workflow_assets_dir / ref
    ).read_bytes() == file.read_bytes()
    pdf = tmp_path / "restored_note.pdf"
    target.canvas_notes.export_pdf(note.id, pdf)
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert target.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_restore_disk_copy_failure_can_retry_without_changing_old_evidence(
    opened, tmp_path, monkeypatch
):
    source = opened("source")
    engagement, _ = seed(source)
    row, expected = attachment(source, tmp_path, engagement)
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    target = opened("target")
    old_engagement, _ = seed(target, "OLD")
    old, old_bytes = attachment(target, tmp_path, old_engagement)
    original_path = target.attachments.resolve_file_path(old.id)
    baseline = rows(target, "audit_logs")
    import taxops.services.backup_bundle as bundle

    def fail(*args, **kwargs):
        raise OSError("synthetic temporary disk write failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(bundle.shutil, "copyfile", fail)
        with pytest.raises(BackupError):
            target.backup.restore_backup(archive, target.paths)
    assert rows(target, "audit_logs") == baseline
    assert original_path.read_bytes() == old_bytes
    target.backup.restore_backup(archive, target.paths)
    assert target.attachments.resolve_file_path(row.id).read_bytes() == expected
    assert original_path.read_bytes() == old_bytes
    journals = [
        json.loads(path.read_text())
        for path in (target.paths.data_root / "restore_history").glob("*.json")
    ]
    assert sorted(j["state"] for j in journals) == ["committed", "failed_before_commit"]
    assert len({j["restore_id"] for j in journals}) == 2


def test_archived_attachment_missing_bytes_does_not_block_current_backup(
    opened, tmp_path
):
    source = opened("source")
    engagement, _ = seed(source)
    old, _ = attachment(source, tmp_path, engagement)
    old_path = source.attachments.resolve_file_path(old.id)
    source.attachments.delete_attachment(old.id)
    old_path.unlink()
    current, expected = attachment(source, tmp_path, engagement)
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    target = opened("target")
    target.backup.restore_backup(archive, target.paths)
    assert target.attachments.resolve_file_path(current.id).read_bytes() == expected
    assert (
        target.conn.execute(
            "SELECT status FROM attachments WHERE id=?", (old.id,)
        ).fetchone()[0]
        == "archived"
    )
    assert Path(target.backup.create_backup(target.paths).backup_path).is_file()


def test_bulk_parent_update_failure_then_retry_is_atomic_across_connections(
    opened, monkeypatch
):
    value = opened("bulk")
    _, request = seed(value)
    value.doc_requests.mark_requested(request.id)
    baseline = rows(value, "audit_logs")

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic status update failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(value.doc_requests._repo, "update_request_status", fail)
        with pytest.raises(sqlite3.OperationalError):
            value.doc_requests.add_items_bulk(request.id, "進項憑證\n銀行存摺")
    assert rows(value, "document_request_items") == []
    assert rows(value, "audit_logs") == baseline
    made = value.doc_requests.add_items_bulk(request.id, "進項憑證\n銀行存摺")
    assert len(rows(value, "document_request_items")) == 2
    with closing(sqlite3.connect(value.paths.db_path)) as connection:
        audits = connection.execute(
            "SELECT target_id,detail_json FROM audit_logs WHERE action='doc_request_item.create'"
        ).fetchall()
    assert {int(a[0]) for a in audits} == {row.id for row in made}
    assert len(audits) == 2


@pytest.mark.parametrize(
    "operation", ["create_backup", "create_database_snapshot", "restore_backup"]
)
def test_pending_edits_are_neither_committed_nor_overwritten(opened, operation):
    value = opened("pending")
    archive = Path(value.backup.create_backup(value.paths).backup_path)
    value.conn.execute(
        "INSERT INTO app_settings(key,value,updated_at) VALUES ('pending_synthetic','not committed','2026-10-12T00:00:00')"
    )
    with pytest.raises(BackupError, match="backup.pending_changes"):
        if operation == "restore_backup":
            value.backup.restore_backup(archive, value.paths)
        else:
            getattr(value.backup, operation)(value.paths)
    assert value.conn.in_transaction
    with closing(sqlite3.connect(value.paths.db_path)) as fresh:
        assert (
            fresh.execute(
                "SELECT value FROM app_settings WHERE key='pending_synthetic'"
            ).fetchone()
            is None
        )
    value.conn.rollback()


def test_final_history_write_failure_keeps_committed_restore_and_audit_authority(
    opened, monkeypatch
):
    import taxops.services.backup as backup

    source = opened("source")
    seed(source)
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    target = opened("target")
    seed(target, "OLD")
    write = backup.write_restore_history

    def fail_final(paths, restore_id, history):
        if history["state"] == "committed":
            raise OSError("synthetic final history write failure")
        write(paths, restore_id, history)

    monkeypatch.setattr(backup, "write_restore_history", fail_final)
    target.backup.restore_backup(archive, target.paths)
    assert target.clients.list_clients()[0].client_code == "SYNTH"
    journals = list((target.paths.data_root / "restore_history").glob("*.json"))
    assert len(journals) == 1
    journal = json.loads(journals[0].read_text())
    assert journal["state"] == "assets_ready"
    with closing(sqlite3.connect(target.paths.db_path)) as fresh:
        audit = json.loads(
            fresh.execute(
                "SELECT detail_json FROM audit_logs WHERE action='backup.restore'"
            ).fetchone()[0]
        )
    assert audit["restore_id"] == journal["restore_id"]


def test_silent_copy_corruption_is_detected_before_database_commit(
    opened, tmp_path, monkeypatch
):
    import taxops.services.backup_bundle as bundle

    source = opened("source")
    engagement, _ = seed(source)
    attachment(source, tmp_path, engagement)
    archive = Path(source.backup.create_backup(source.paths).backup_path)
    target = opened("target")
    seed(target, "OLD")
    previous = rows(target, "clients")

    def incomplete_copy(src, destination):
        Path(destination).write_bytes(Path(src).read_bytes()[:3])

    monkeypatch.setattr(bundle.shutil, "copyfile", incomplete_copy)
    with pytest.raises(BackupError, match="backup.assets.incomplete"):
        target.backup.restore_backup(archive, target.paths)
    assert rows(target, "clients") == previous
    journals = list((target.paths.data_root / "restore_history").glob("*.json"))
    assert json.loads(journals[0].read_text())["state"] == "failed_before_commit"


def test_changed_active_attachment_is_not_certified_as_complete_backup(
    opened, tmp_path
):
    value = opened("changed")
    engagement, _ = seed(value)
    row, _ = attachment(value, tmp_path, engagement)
    value.attachments.resolve_file_path(row.id).write_text(
        "synthetic accidental external edit"
    )
    with pytest.raises(BackupError, match="backup.assets.incomplete"):
        value.backup.create_backup(value.paths)
    assert rows(value, "backup_records") == []


def test_truncated_transfer_is_rejected_without_live_changes(opened, tmp_path):
    value = opened("transfer")
    seed(value)
    archive = Path(value.backup.create_backup(value.paths).backup_path)
    truncated = tmp_path / "partial-transfer.taxops.zip"
    truncated.write_bytes(archive.read_bytes()[:64])
    before = rows(value, "clients")
    with pytest.raises(BackupError, match="backup.invalid_file"):
        value.backup.restore_backup(truncated, value.paths)
    assert rows(value, "clients") == before


def test_legacy_snapshot_connect_failure_leaves_no_success_record(opened, monkeypatch):
    import taxops.services.backup as backup

    value = opened("snapshot")
    seed(value)

    def connection_error(*a, **kw):
        raise sqlite3.OperationalError("synthetic snapshot open failure")

    monkeypatch.setattr(backup.sqlite3, "connect", connection_error)
    with pytest.raises(BackupError, match="backup.create.failed"):
        value.backup.create_database_snapshot(value.paths)
    assert value.conn.execute("SELECT COUNT(*) FROM backup_records").fetchone()[0] == 0


def test_restore_staging_connect_failure_keeps_live_database(opened, monkeypatch):
    import taxops.services.backup as backup

    value = opened("stage")
    seed(value)
    archive = Path(value.backup.create_backup(value.paths).backup_path)
    before = rows(value, "clients")
    connect = sqlite3.connect

    def connection_error(path, *a, **kw):
        if ".restore_bundle_" in str(path):
            raise sqlite3.OperationalError("synthetic staging open failure")
        return connect(path, *a, **kw)

    monkeypatch.setattr(backup.sqlite3, "connect", connection_error)
    with pytest.raises(BackupError, match="backup.invalid_file"):
        value.backup.restore_backup(archive, value.paths)
    assert rows(value, "clients") == before


def test_restore_staging_directory_failure_keeps_live_database(opened, monkeypatch):
    import taxops.services.backup as backup

    value = opened("stage")
    seed(value)
    archive = Path(value.backup.create_backup(value.paths).backup_path)
    before = rows(value, "clients")

    def directory_error(*a, **kw):
        raise PermissionError("synthetic staging directory unavailable")

    monkeypatch.setattr(backup.tempfile, "TemporaryDirectory", directory_error)
    with pytest.raises(BackupError, match="backup.restore.failed"):
        value.backup.restore_backup(archive, value.paths)
    assert rows(value, "clients") == before


def test_known_prior_schema_snapshot_restores_and_migrates_without_changing_source(
    tmp_path, monkeypatch
):
    import taxops.db.migrate as runner

    known = runner.MIGRATIONS
    with monkeypatch.context() as scoped:
        scoped.setattr(runner, "MIGRATIONS", known[:-1])
        old = bootstrap(resolve_paths(override_root=tmp_path / "older"))
        try:
            old.clients.create_client(CreateClientInput("PRIOR", "舊版合成客戶"))
            snapshot = Path(old.backup.create_database_snapshot(old.paths).backup_path)
        finally:
            old.close()
    before = snapshot.read_bytes()
    new = bootstrap(resolve_paths(override_root=tmp_path / "current"))
    try:
        new.backup.restore_backup(snapshot, new.paths)
        with closing(sqlite3.connect(new.paths.db_path)) as connection:
            applied = {
                row[0]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            clients = [
                row[0] for row in connection.execute("SELECT client_code FROM clients")
            ]
        assert applied == {version for version, _ in known}
        assert clients == ["PRIOR"]
        assert snapshot.read_bytes() == before
        assert Path(new.backup.create_backup(new.paths).backup_path).is_file()
    finally:
        new.close()
