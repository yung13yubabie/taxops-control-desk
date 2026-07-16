from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from taxops.security.file_guard import MAX_FILE_SIZE
from taxops.services.attachments import AttachmentValidationError
from taxops.services.client_leases import LeaseInput
from taxops.services.clients import CreateClientInput


def _client_and_lease(container, code: str = "LA01"):
    client = container.clients.create_client(
        CreateClientInput(client_code=code, client_name="租約附件客戶")
    )
    lease = container.client_leases.create_lease(
        client.id, LeaseInput(lease_name="總公司租約", start_date="2026-01-01")
    )
    return client, lease


def _source(tmp_path: Path, name: str = "租約證明.pdf", body: bytes = b"lease") -> Path:
    path = tmp_path / name
    path.write_bytes(body)
    return path


def _stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def test_upload_list_resolve_and_archive_lease_attachment(container, tmp_path):
    client, lease = _client_and_lease(container)
    source = _source(tmp_path, body=b"real lease content")

    row = container.attachments.upload_lease_attachment(
        client.id, lease.id, source, notes="中文備註\n第二行"
    )

    assert row.engagement_id is None
    assert row.request_id is None
    assert row.client_id == client.id
    assert row.lease_id == lease.id
    assert row.notes == "中文備註\n第二行"
    assert len(row.file_hash_sha256) == 64
    assert container.attachments.list_by_lease(lease.id) == [row]
    assert container.attachments.resolve_file_path(row.id).read_bytes() == b"real lease content"
    assert container.conn.execute(
        "SELECT COUNT(*) FROM attachment_versions WHERE attachment_id = ?", (row.id,)
    ).fetchone()[0] == 1

    archived = container.attachments.delete_attachment(row.id)
    assert archived.status == "archived"
    assert container.attachments.list_by_lease(lease.id) == []


def test_archived_lease_keeps_existing_attachment_readable_and_manageable(
    container, tmp_path
):
    client, lease = _client_and_lease(container)
    row = container.attachments.upload_lease_attachment(
        client.id,
        lease.id,
        _source(tmp_path, body=b"historical lease evidence"),
    )

    container.client_leases.archive_lease(lease.id)

    assert container.attachments.list_by_lease(lease.id) == [row]
    assert (
        container.attachments.resolve_file_path(row.id).read_bytes()
        == b"historical lease evidence"
    )
    archived_attachment = container.attachments.delete_attachment(row.id)
    assert archived_attachment.status == "archived"
    assert container.attachments.list_by_lease(lease.id) == []
    assert container.attachments.list_by_lease(
        lease.id, include_archived=True
    ) == [archived_attachment]


def test_same_original_filename_never_overwrites(container, tmp_path):
    client, lease = _client_and_lease(container)
    first = container.attachments.upload_lease_attachment(
        client.id, lease.id, _source(tmp_path, body=b"first")
    )
    second = container.attachments.upload_lease_attachment(
        client.id, lease.id, _source(tmp_path, body=b"second")
    )
    assert first.stored_filename != second.stored_filename
    assert container.attachments.resolve_file_path(first.id).read_bytes() == b"first"
    assert container.attachments.resolve_file_path(second.id).read_bytes() == b"second"


def test_mismatched_client_or_archived_owner_leaves_no_artifact(container, tmp_path):
    client, lease = _client_and_lease(container)
    other = container.clients.create_client(
        CreateClientInput(client_code="OTHER", client_name="另一客戶")
    )
    source = _source(tmp_path)

    with pytest.raises(AttachmentValidationError) as mismatch:
        container.attachments.upload_lease_attachment(other.id, lease.id, source)
    assert mismatch.value.code == "attachment.lease_not_found"

    container.client_leases.archive_lease(lease.id)
    with pytest.raises(AttachmentValidationError) as archived:
        container.attachments.upload_lease_attachment(client.id, lease.id, source)
    assert archived.value.code == "attachment.lease_not_found"
    assert container.conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    assert _stored_files(container.paths.attachments_dir) == []


def test_deleted_client_owner_is_rejected(container, tmp_path):
    client, lease = _client_and_lease(container)
    container.clients.delete_client(client.id)
    with pytest.raises(AttachmentValidationError) as exc:
        container.attachments.upload_lease_attachment(
            client.id, lease.id, _source(tmp_path)
        )
    assert exc.value.code == "attachment.lease_not_found"
    assert _stored_files(container.paths.attachments_dir) == []


def test_lease_upload_uses_extension_and_size_guards(container, tmp_path, monkeypatch):
    client, lease = _client_and_lease(container)
    with pytest.raises(AttachmentValidationError) as extension:
        container.attachments.upload_lease_attachment(
            client.id, lease.id, _source(tmp_path, "evil.exe")
        )
    assert extension.value.code == "attachment.extension_not_allowed"

    source = _source(tmp_path)
    original_stat = Path.stat

    def oversized(path: Path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == source:
            class Stat:
                st_size = MAX_FILE_SIZE + 1
            return Stat()
        return result

    monkeypatch.setattr(Path, "stat", oversized)
    with pytest.raises(AttachmentValidationError) as large:
        container.attachments.upload_lease_attachment(client.id, lease.id, source)
    assert large.value.code == "attachment.file_too_large"
    assert _stored_files(container.paths.attachments_dir) == []


@pytest.mark.parametrize("failure_layer", ["db", "audit"])
def test_db_or_audit_failure_rolls_back_and_cleans_file(
    container, tmp_path, monkeypatch, failure_layer
):
    client, lease = _client_and_lease(container)
    target = (
        container.attachments._repo
        if failure_layer == "db"
        else container.attachments._audit
    )
    method = "insert_for_lease" if failure_layer == "db" else "record"
    monkeypatch.setattr(
        target,
        method,
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(failure_layer)),
    )
    with pytest.raises(RuntimeError, match=failure_layer):
        container.attachments.upload_lease_attachment(
            client.id, lease.id, _source(tmp_path)
        )
    assert container.conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    assert _stored_files(container.paths.attachments_dir) == []


def test_copy_failure_cleans_partial_file(container, tmp_path, monkeypatch):
    client, lease = _client_and_lease(container)

    def fail_copy(_source, destination):
        Path(destination).write_bytes(b"partial")
        raise OSError("copy failed")

    monkeypatch.setattr("taxops.services.attachments.shutil.copy2", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        container.attachments.upload_lease_attachment(
            client.id, lease.id, _source(tmp_path)
        )
    assert _stored_files(container.paths.attachments_dir) == []


def test_repeated_storage_collision_is_stable_validation_error(
    container, tmp_path, monkeypatch
):
    client, lease = _client_and_lease(container)

    class FixedUuid:
        hex = "a" * 32

    monkeypatch.setattr("taxops.services.attachments.uuid.uuid4", lambda: FixedUuid())
    now = datetime.now(timezone.utc)
    collision = (
        container.paths.attachments_dir
        / f"{now.year:04d}"
        / f"{now.month:02d}"
        / ("a" * 32 + ".pdf")
    )
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_bytes(b"keep")

    with pytest.raises(AttachmentValidationError) as exc:
        container.attachments.upload_lease_attachment(
            client.id, lease.id, _source(tmp_path)
        )
    assert exc.value.code == "attachment.filename_collision"
    assert collision.read_bytes() == b"keep"
    assert container.conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
