from __future__ import annotations

import json
import sqlite3

import pytest

from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.compliance_profiles import ComplianceProfilesRepository
from taxops.db.connection import open_connection
from taxops.services.audit import AuditService
from taxops.services.clients import CreateClientInput
from taxops.services.compliance_profiles import (
    ComplianceProfileItemInput,
    ComplianceProfileValidationError,
    ComplianceProfilesService,
)


def _client(container: object, code: str = "C-COMPLIANCE") -> int:
    clients = getattr(container, "clients")
    return clients.create_client(
        CreateClientInput(client_code=code, client_name="年度規則測試客戶")
    ).id


def _item(
    work_type: str = "vat",
    frequency: str = "bimonthly",
    *,
    enabled: bool = True,
    notes: str | None = None,
) -> ComplianceProfileItemInput:
    return ComplianceProfileItemInput(
        work_type=work_type,
        frequency=frequency,
        enabled=enabled,
        notes=notes,
    )


def test_container_wires_profile_service_and_repository_connection(container: object) -> None:
    service = getattr(container, "compliance_profiles")
    assert service.connection is getattr(container, "conn")
    assert service.repository.connection is getattr(container, "conn")


def test_create_and_update_single_profile_preserves_disabled_and_multiline_notes(
    container: object,
) -> None:
    client_id = _client(container)
    service = getattr(container, "compliance_profiles")

    created = service.upsert_profile(
        client_id,
        fiscal_year_start_month=1,
        items=(
            _item(notes="第一行\n第二行"),
            _item("company_annual", "annual", enabled=False, notes="保留停用"),
        ),
    )
    updated = service.upsert_profile(
        client_id,
        fiscal_year_start_month=7,
        items=(_item(enabled=False, notes="停用但不刪除"),),
    )

    assert created.profile.id == updated.profile.id
    assert updated.profile.fiscal_year_start_month == 7
    assert [(row.work_type, row.enabled, row.notes) for row in updated.items] == [
        ("vat", False, "停用但不刪除"),
        ("company_annual", False, "保留停用"),
    ]
    assert service.get_for_client(client_id) == updated


def test_exact_same_payload_is_idempotent_without_timestamp_or_fake_audit(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _client(container)
    service = getattr(container, "compliance_profiles")
    payload = (_item(notes="內容不變\n仍保留"),)
    first = service.upsert_profile(client_id, 1, payload)
    audit_count = getattr(container, "audit")._repo.count()
    monkeypatch.setattr(
        "taxops.repositories.compliance_profiles.now_iso",
        lambda: (_ for _ in ()).throw(AssertionError("idempotent save wrote a row")),
    )

    second = service.upsert_profile(client_id, 1, payload)

    assert second == first
    assert getattr(container, "audit")._repo.count() == audit_count


def test_update_audit_contains_only_safe_profile_metadata(container: object) -> None:
    client_id = _client(container)
    secret_note = "客戶私密說明\n請勿進 audit"
    service = getattr(container, "compliance_profiles")

    saved = service.upsert_profile(
        client_id,
        4,
        (
            _item(notes=secret_note),
            _item("provisional_tax", "annual", enabled=False, notes="另一個秘密"),
        ),
    )

    rows = [
        row
        for row in getattr(container, "audit")._repo.list_recent(limit=20)
        if row.action == "compliance_profile.update"
    ]
    assert len(rows) == 1
    assert rows[0].target_type == "compliance_profile"
    assert rows[0].target_id == str(saved.profile.id)
    detail = json.loads(rows[0].detail_json or "{}")
    assert detail == {
        "client_id": client_id,
        "fiscal_year_start_month": 4,
        "item_count": 2,
        "items": [
            {"work_type": "vat", "frequency": "bimonthly", "enabled": True},
            {
                "work_type": "provisional_tax",
                "frequency": "annual",
                "enabled": False,
            },
        ],
    }
    assert secret_note not in (rows[0].detail_json or "")
    assert "另一個秘密" not in (rows[0].detail_json or "")


def test_missing_or_archived_client_is_rejected_without_rows(container: object) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    getattr(container, "clients").delete_client(client_id)

    for invalid_id in (client_id, 999_999):
        with pytest.raises(ComplianceProfileValidationError) as exc:
            service.upsert_profile(invalid_id, 1, (_item(),))
        assert exc.value.code == "compliance_profile.client_not_found"
    assert getattr(container, "conn").execute(
        "SELECT COUNT(*) FROM compliance_profiles"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("client_id", [True, 0, -1, 1.0, "1"])
def test_client_id_requires_positive_exact_integer(container: object, client_id: object) -> None:
    service = getattr(container, "compliance_profiles")
    with pytest.raises(ComplianceProfileValidationError) as exc:
        service.upsert_profile(client_id, 1, ())  # type: ignore[arg-type]
    assert exc.value.code == "compliance_profile.client_id.invalid"


@pytest.mark.parametrize("month", [True, 0, 13, 1.0, "1"])
def test_profile_fiscal_month_requires_exact_integer(container: object, month: object) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    with pytest.raises(ComplianceProfileValidationError) as exc:
        service.upsert_profile(client_id, month, ())  # type: ignore[arg-type]
    assert exc.value.code == "compliance_profile.fiscal_start_month.invalid"


@pytest.mark.parametrize("items", ["vat", b"vat", [_item(), object()]])
def test_profile_items_require_typed_sequence(container: object, items: object) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    with pytest.raises(ComplianceProfileValidationError) as exc:
        service.upsert_profile(client_id, 1, items)  # type: ignore[arg-type]
    assert exc.value.code == "compliance_profile.items.invalid"


@pytest.mark.parametrize(
    ("item", "code"),
    [
        (_item("unknown", "annual"), "compliance_profile.work_type.unknown"),
        (_item("vat", "weekly"), "compliance_profile.frequency.invalid"),
        (_item("vat", "annual"), "compliance_profile.frequency.invalid"),
        (
            ComplianceProfileItemInput(1, "annual"),  # type: ignore[arg-type]
            "compliance_profile.work_type.invalid",
        ),
        (
            ComplianceProfileItemInput("vat", True),  # type: ignore[arg-type]
            "compliance_profile.frequency.invalid",
        ),
        (
            ComplianceProfileItemInput("vat", "bimonthly", enabled=1),  # type: ignore[arg-type]
            "compliance_profile.enabled.invalid",
        ),
        (
            ComplianceProfileItemInput("vat", "bimonthly", notes=12),  # type: ignore[arg-type]
            "compliance_profile.notes.invalid",
        ),
    ],
)
def test_profile_item_validation_uses_stable_errors(
    container: object, item: ComplianceProfileItemInput, code: str
) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    with pytest.raises(ComplianceProfileValidationError) as exc:
        service.upsert_profile(client_id, 1, (item,))
    assert exc.value.code == code


def test_duplicate_work_type_rejected_before_mutation(container: object) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    with pytest.raises(ComplianceProfileValidationError) as exc:
        service.upsert_profile(client_id, 1, (_item(), _item(enabled=False)))
    assert exc.value.code == "compliance_profile.work_type.duplicate"
    assert service.get_for_client(client_id) is None


def test_notes_preserve_newlines_but_reject_overlong_text(container: object) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    with pytest.raises(ComplianceProfileValidationError) as exc:
        service.upsert_profile(client_id, 1, (_item(notes="說" * 2001),))
    assert exc.value.code == "compliance_profile.notes.too_long"
    assert service.get_for_client(client_id) is None


def test_audit_failure_rolls_back_new_profile_items_and_audit(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    before_audits = getattr(container, "audit")._repo.count()

    def fail_record(**_kwargs: object) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(getattr(container, "audit"), "record", fail_record)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        service.upsert_profile(client_id, 1, (_item(),))

    conn = getattr(container, "conn")
    assert conn.execute("SELECT COUNT(*) FROM compliance_profiles").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM compliance_profile_items").fetchone()[0] == 0
    assert getattr(container, "audit")._repo.count() == before_audits


def test_audit_failure_restores_exact_existing_profile_and_items(
    container: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    original = service.upsert_profile(
        client_id, 1, (_item(notes="原始\n內容"),)
    )
    before_audits = getattr(container, "audit")._repo.count()

    def fail_record(**_kwargs: object) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(getattr(container, "audit"), "record", fail_record)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        service.upsert_profile(
            client_id,
            7,
            (_item(enabled=False, notes="不可留下"),),
        )

    assert service.get_for_client(client_id) == original
    assert getattr(container, "audit")._repo.count() == before_audits


def test_repository_lists_disabled_rows_in_canonical_order(db_conn: sqlite3.Connection) -> None:
    client_id = db_conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at) "
        "VALUES ('C-REPO', 'repo', 't', 't')"
    ).lastrowid
    repo = ComplianceProfilesRepository(db_conn)
    profile = repo.upsert_profile(int(client_id or 0), 1)
    repo.upsert_item(profile.id, "vat", "bimonthly", False, "停用")
    repo.upsert_item(profile.id, "monthly_bookkeeping", "monthly", True, None)

    assert [(row.work_type, row.enabled) for row in repo.list_items(profile.id)] == [
        ("monthly_bookkeeping", True),
        ("vat", False),
    ]


def test_service_constructor_fails_fast_on_connection_mismatch(
    db_conn: sqlite3.Connection,
) -> None:
    other = sqlite3.connect(":memory:")
    try:
        repo = ComplianceProfilesRepository(db_conn)
        mismatched_audit = AuditService(AuditLogRepository(other))
        with pytest.raises(ValueError, match="compliance_profile.connection.mismatch"):
            ComplianceProfilesService(db_conn, repo, mismatched_audit)
    finally:
        other.close()


def test_service_rejects_preexisting_transaction(container: object) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    try:
        with pytest.raises(ComplianceProfileValidationError) as exc:
            service.upsert_profile(client_id, 1, (_item(),))
        assert exc.value.code == "compliance_profile.transaction.already_active"
    finally:
        conn.rollback()


def test_writer_lock_maps_to_stable_busy_error_without_partial_profile(
    container: object,
) -> None:
    service = getattr(container, "compliance_profiles")
    client_id = _client(container)
    contender = getattr(container, "conn")
    original_timeout = contender.execute("PRAGMA busy_timeout").fetchone()[0]
    writer = open_connection(getattr(container, "paths").db_path)
    writer.execute("PRAGMA busy_timeout = 0")
    contender.execute("PRAGMA busy_timeout = 0")
    writer.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ComplianceProfileValidationError) as exc:
            service.upsert_profile(client_id, 1, (_item(),))
        assert exc.value.code == "compliance_profile.transaction.busy"
    finally:
        writer.rollback()
        writer.close()
        contender.execute(f"PRAGMA busy_timeout = {int(original_timeout)}")

    assert service.get_for_client(client_id) is None
