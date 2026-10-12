"""Synthetic schema-28 domain preservation across portable backup and restart."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

import pytest

from taxops.core.paths import resolve_paths
from taxops.services.attachments import UploadAttachmentInput
from taxops.services.backup import BackupError
from taxops.services.client_industries import IndustryInput
from taxops.services.client_leases import LeaseInput
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.ui.app import bootstrap


TABLES = (
    "clients",
    "client_leases",
    "client_industries",
    "compliance_profiles",
    "compliance_profile_items",
    "annual_workspaces",
    "annual_work_items",
    "annual_work_transactions",
    "engagements",
    "document_requests",
    "document_request_items",
    "workflow_tasks",
    "attachment_versions",
)


def _snapshot(conn):
    # Names are fixed constants, never supplied by a user.
    return {
        name: [tuple(row) for row in conn.execute(f"SELECT * FROM {name} ORDER BY id")]
        for name in TABLES
    }


def _seed(value, tmp_path):
    client = value.clients.create_client(
        CreateClientInput(
            "SYN-28",
            "合成年度客戶",
            registered_address="合成登記地址一號",
            contact_address="合成通訊地址二號",
            contact_address_same=False,
        )
    )
    value.client_industries.replace_from_registry(
        client.id,
        [
            IndustryInput("SYN01", "合成主要業別", True),
            IndustryInput("SYN02", "合成次要業別"),
        ],
        source="synthetic",
        source_version="fixture-28",
    )
    assets = {}
    for index in range(2):
        lease = value.client_leases.create_lease(
            client.id,
            LeaseInput(
                f"合成租約{index}",
                premises_address=f"合成租址{index}",
                landlord_name="合成房東",
                start_date="2026-01-01",
                end_date="2026-12-31",
                monthly_rent=30000 + index,
                deposit_amount=60000,
                notes="第一行\n第二行",
            ),
        )
        file = tmp_path / f"lease-{index}.txt"
        file.write_text(f"Synthetic lease evidence {index}\n", encoding="utf-8")
        row = value.attachments.upload_lease_attachment(client.id, lease.id, file)
        value.attachments.accept_attachment(row.id)
        assert row.engagement_id is None and row.client_id == client.id
        assets[row.id] = file.read_bytes()
    value.compliance_profiles.upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("corporate_income_tax", "annual"),),
    )
    drafts = value.annual_work.preview(client.id, 2026)
    item = value.annual_work.confirm_preview(client.id, 2026, drafts).items[0]
    linked = value.annual_work.create_linked_request(
        item.id,
        request_name="年度合成索件",
        item_names=("合成憑證", "合成帳冊"),
        due_date="2026-10-31",
    )
    task = value.annual_work.create_linked_task(
        item.id, title="合成年度核對", due_date="2026-10-30", next_step="核對合成資料"
    )
    value.annual_work.set_work_status(item.id, "in_progress")
    file = tmp_path / "annual-document.txt"
    file.write_bytes(b"Synthetic annual document\n")
    row = value.attachments.upload_attachment(
        UploadAttachmentInput(linked.engagement.id, linked.request.id, file)
    )
    value.attachments.accept_attachment(row.id)
    assets[row.id] = file.read_bytes()
    for category, amount in (
        ("tax_liability", 62000),
        ("client_tax_collection", 43400),
        ("tax_payment", 40000),
        ("tax_credit_or_refund", 0),
        ("fee_receivable", 5000),
        ("fee_receipt", 2000),
    ):
        value.annual_transactions.add(item.id, category, amount, "2026-05-15")
    assert task.annual_work_item_id == item.id
    return client.id, item.id, assets


def test_schema28_domains_assets_and_balances_roundtrip_reopen_rebackup(tmp_path):
    source = bootstrap(resolve_paths(override_root=tmp_path / "source"))
    target_paths = resolve_paths(override_root=tmp_path / "乾淨 還原目錄")
    target = bootstrap(target_paths)
    try:
        client_id, item_id, assets = _seed(source, tmp_path)
        before = _snapshot(source.conn)
        attachment_rows = [
            dict(row)
            for row in source.conn.execute("SELECT * FROM attachments ORDER BY id")
        ]
        audit_rows = [
            tuple(row)
            for row in source.conn.execute("SELECT * FROM audit_logs ORDER BY id")
        ]
        archive = Path(source.backup.create_backup(source.paths).backup_path)
        archive_hash = sha256(archive.read_bytes()).hexdigest()
        target.backup.restore_backup(archive, target.paths)
        assert _snapshot(target.conn) == before
        assert sha256(archive.read_bytes()).hexdigest() == archive_hash
        for original in attachment_rows:
            restored = dict(
                target.conn.execute(
                    "SELECT * FROM attachments WHERE id=?", (original["id"],)
                ).fetchone()
            )
            original.pop("stored_filename")
            restored.pop("stored_filename")
            assert restored == original
        assert [
            tuple(row)
            for row in target.conn.execute("SELECT * FROM audit_logs ORDER BY id")
        ][: len(audit_rows)] == audit_rows
        target.close()
        target = bootstrap(target_paths)
        assert _snapshot(target.conn) == before
        client = target.clients.get_client(client_id)
        assert (
            client.registered_address,
            client.contact_address,
            client.contact_address_same,
        ) == ("合成登記地址一號", "合成通訊地址二號", False)
        assert len(target.client_leases.list_for_client(client_id)) == 2
        assert len(target.client_industries.list_for_client(client_id)) == 2
        for attachment_id, expected in assets.items():
            assert (
                target.attachments.resolve_file_path(attachment_id).read_bytes()
                == expected
            )
        balance = target.annual_transactions.balance(item_id)
        assert (
            balance.unpaid_tax,
            balance.collection_shortfall,
            balance.outstanding_fee,
        ) == (22000, 18600, 3000)
        assert target.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        second_archive = Path(target.backup.create_backup(target.paths).backup_path)
        with ZipFile(second_archive) as zipped:
            manifest = json.loads(zipped.read("manifest.json"))
            assert (
                len(
                    [
                        entry
                        for entry in manifest["files"]
                        if entry["path"].startswith("attachments/")
                    ]
                )
                == 3
            )
        with closing(sqlite3.connect(target.paths.db_path)) as fresh:
            assert _snapshot(fresh) == before
    finally:
        source.close()
        target.close()


def test_missing_active_lease_asset_fails_before_backup_record_commit(tmp_path):
    source = bootstrap(resolve_paths(override_root=tmp_path / "source"))
    try:
        _, _, assets = _seed(source, tmp_path)
        lease_attachment_id = next(iter(assets))
        source.attachments.resolve_file_path(lease_attachment_id).unlink()
        before = list(source.conn.iterdump())
        with pytest.raises(BackupError, match="backup.assets.incomplete"):
            source.backup.create_backup(source.paths)
        assert list(source.conn.iterdump()) == before
        assert list(source.paths.backups_dir.glob("*.taxops.zip")) == []
    finally:
        source.close()


def test_future_bundle_version_is_rejected_without_live_changes(tmp_path):
    source = bootstrap(resolve_paths(override_root=tmp_path / "source"))
    target = bootstrap(resolve_paths(override_root=tmp_path / "target"))
    try:
        _seed(source, tmp_path)
        archive = Path(source.backup.create_backup(source.paths).backup_path)
        future = tmp_path / "future-format.taxops.zip"
        with ZipFile(archive) as current, ZipFile(future, "w") as output:
            for entry in current.infolist():
                payload = current.read(entry.filename)
                if entry.filename == "manifest.json":
                    manifest = json.loads(payload)
                    manifest["version"] = 2
                    payload = json.dumps(manifest).encode()
                output.writestr(entry, payload)
        before = list(target.conn.iterdump())
        with pytest.raises(BackupError, match="backup.invalid_file"):
            target.backup.restore_backup(future, target.paths)
        assert list(target.conn.iterdump()) == before
        assert not any(target.paths.attachments_dir.rglob("*"))
    finally:
        source.close()
        target.close()
