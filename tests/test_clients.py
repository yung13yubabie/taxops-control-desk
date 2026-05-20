"""Clients service: create / list / update / delete / bulk / validation / audit."""

from __future__ import annotations

import pytest

from taxops.services.clients import (
    ClientValidationError,
    CreateClientInput,
    UpdateClientInput,
)
from taxops.services.clients_bulk import (
    BulkParseError,
    RawRow,
    auto_detect_mapping,
    import_validated,
    parse_clipboard_text,
    validate_rows,
)
from taxops.services.container import ServiceContainer


def test_create_client_persists_and_writes_audit(container: ServiceContainer) -> None:
    payload = CreateClientInput(
        client_code="C001",
        client_name="測試公司A",
        tax_id="12345678",
        contact_name="王小明",
    )
    client = container.clients.create_client(payload)
    assert client.id > 0
    assert client.client_code == "C001"
    assert client.client_name == "測試公司A"
    assert client.tax_id == "12345678"
    assert client.contact_name == "王小明"
    assert client.created_at.endswith("Z")

    fetched = container.clients.get_client(client.id)
    assert fetched is not None
    assert fetched.id == client.id
    assert fetched.client_code == "C001"

    by_code = container.clients.find_by_code("C001")
    assert by_code is not None and by_code.id == client.id

    audit_rows = container.audit._repo.list_recent(limit=10)  # type: ignore[attr-defined]
    actions = [r.action for r in audit_rows]
    assert "client.create" in actions
    target_ids = [r.target_id for r in audit_rows if r.action == "client.create"]
    assert str(client.id) in target_ids


def test_list_clients_returns_inserted(container: ServiceContainer) -> None:
    container.clients.create_client(
        CreateClientInput(client_code="C002", client_name="A 公司")
    )
    container.clients.create_client(
        CreateClientInput(client_code="C001", client_name="B 公司")
    )
    items = container.clients.list_clients()
    codes = [c.client_code for c in items]
    assert codes == sorted(codes)  # ordered by client_code
    assert {"C001", "C002"}.issubset(set(codes))


def test_create_requires_client_code(container: ServiceContainer) -> None:
    with pytest.raises(ClientValidationError) as exc:
        container.clients.create_client(
            CreateClientInput(client_code="   ", client_name="X 公司")
        )
    assert exc.value.code == "client.client_code.required"


def test_create_requires_client_name(container: ServiceContainer) -> None:
    with pytest.raises(ClientValidationError) as exc:
        container.clients.create_client(
            CreateClientInput(client_code="C010", client_name="   ")
        )
    assert exc.value.code == "client.client_name.required"


def test_duplicate_client_code_rejected(container: ServiceContainer) -> None:
    container.clients.create_client(
        CreateClientInput(client_code="C100", client_name="第一家")
    )
    with pytest.raises(ClientValidationError) as exc:
        container.clients.create_client(
            CreateClientInput(client_code="C100", client_name="第二家")
        )
    assert exc.value.code == "client.client_code.duplicate"


def test_invalid_tax_id_rejected(container: ServiceContainer) -> None:
    with pytest.raises(ClientValidationError) as exc:
        container.clients.create_client(
            CreateClientInput(
                client_code="C200", client_name="測試公司B", tax_id="abc"
            )
        )
    assert exc.value.code == "client.tax_id.invalid"


def test_blank_tax_id_is_allowed(container: ServiceContainer) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="C300", client_name="無統編客戶", tax_id="")
    )
    assert client.tax_id is None


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_client_persists_and_writes_audit(container: ServiceContainer) -> None:
    created = container.clients.create_client(
        CreateClientInput(client_code="U001", client_name="舊名稱")
    )
    updated = container.clients.update_client(
        created.id,
        UpdateClientInput(client_code="U001", client_name="新名稱", contact_phone="0912345678"),
    )
    assert updated.client_name == "新名稱"
    assert updated.contact_phone == "0912345678"

    audit_rows = container.audit._repo.list_recent(limit=10)  # type: ignore[attr-defined]
    actions = [r.action for r in audit_rows]
    assert "client.update" in actions


def test_update_client_code_can_change(container: ServiceContainer) -> None:
    created = container.clients.create_client(
        CreateClientInput(client_code="OLD01", client_name="舊代號")
    )
    updated = container.clients.update_client(
        created.id,
        UpdateClientInput(client_code="NEW01", client_name="舊代號"),
    )
    assert updated.client_code == "NEW01"
    assert container.clients.find_by_code("OLD01") is None


def test_update_duplicate_code_rejected(container: ServiceContainer) -> None:
    container.clients.create_client(CreateClientInput(client_code="X001", client_name="甲"))
    b = container.clients.create_client(CreateClientInput(client_code="X002", client_name="乙"))
    with pytest.raises(ClientValidationError) as exc:
        container.clients.update_client(
            b.id,
            UpdateClientInput(client_code="X001", client_name="乙"),
        )
    assert exc.value.code == "client.client_code.duplicate"


def test_update_same_code_allowed(container: ServiceContainer) -> None:
    created = container.clients.create_client(
        CreateClientInput(client_code="SAME1", client_name="原始")
    )
    updated = container.clients.update_client(
        created.id,
        UpdateClientInput(client_code="SAME1", client_name="更新名稱"),
    )
    assert updated.client_name == "更新名稱"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_client_soft_deletes_and_hides_from_list(
    container: ServiceContainer,
) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="D001", client_name="待停用")
    )
    container.clients.delete_client(client.id)

    # Hidden from service-level get and list
    assert container.clients.get_client(client.id) is None
    listed_ids = [c.id for c in container.clients.list_clients()]
    assert client.id not in listed_ids

    # Row still exists in DB with deleted_at set
    raw = container.conn.execute(
        "SELECT deleted_at FROM clients WHERE id = ?", (client.id,)
    ).fetchone()
    assert raw is not None, "row must still exist after soft delete"
    assert raw["deleted_at"] is not None, "deleted_at must be set"

    audit_rows = container.audit._repo.list_recent(limit=10)  # type: ignore[attr-defined]
    actions = [r.action for r in audit_rows]
    assert "client.delete" in actions


def test_delete_nonexistent_raises(container: ServiceContainer) -> None:
    with pytest.raises(ClientValidationError) as exc:
        container.clients.delete_client(99999)
    assert exc.value.code == "client.not_found"


def test_delete_already_deleted_raises(container: ServiceContainer) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="D002", client_name="二次刪除測試")
    )
    container.clients.delete_client(client.id)
    with pytest.raises(ClientValidationError) as exc:
        container.clients.delete_client(client.id)
    assert exc.value.code == "client.not_found"


def test_restore_client_brings_back_to_list(container: ServiceContainer) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="D003", client_name="待復原")
    )
    container.clients.delete_client(client.id)
    assert container.clients.get_client(client.id) is None

    container.clients.restore_client(client.id)

    restored = container.clients.get_client(client.id)
    assert restored is not None
    assert restored.client_name == "待復原"
    assert restored.deleted_at is None

    audit_rows = container.audit._repo.list_recent(limit=10)  # type: ignore[attr-defined]
    actions = [r.action for r in audit_rows]
    assert "client.restore" in actions


def test_restore_active_client_raises(container: ServiceContainer) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="D004", client_name="未刪除")
    )
    with pytest.raises(ClientValidationError) as exc:
        container.clients.restore_client(client.id)
    assert exc.value.code == "client.not_found"


def test_deleted_client_code_remains_reserved(container: ServiceContainer) -> None:
    """Soft-deleted client codes stay reserved — prevents accidental reuse."""
    client = container.clients.create_client(
        CreateClientInput(client_code="REUSE1", client_name="原始")
    )
    container.clients.delete_client(client.id)

    with pytest.raises(ClientValidationError) as exc:
        container.clients.create_client(
            CreateClientInput(client_code="REUSE1", client_name="嘗試重用")
        )
    assert exc.value.code == "client.client_code.duplicate"


def test_purge_deleted_client_removes_row_and_writes_audit(
    container: ServiceContainer,
) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="P001", client_name="永久刪除測試")
    )
    container.clients.delete_client(client.id)

    container.clients.purge_client(client.id)

    raw = container.conn.execute(
        "SELECT id FROM clients WHERE id = ?", (client.id,)
    ).fetchone()
    assert raw is None
    audit_rows = container.audit._repo.list_recent(limit=10)  # type: ignore[attr-defined]
    assert any(
        row.action == "client.purge" and row.target_id == str(client.id)
        for row in audit_rows
    )


def test_purge_active_client_is_blocked(container: ServiceContainer) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="P002", client_name="未封存不可永久刪除")
    )

    with pytest.raises(ClientValidationError) as exc:
        container.clients.purge_client(client.id)

    assert exc.value.code == "client.purge.requires_deleted"


def test_purge_deleted_client_with_engagement_is_blocked(
    container: ServiceContainer,
) -> None:
    from taxops.services.engagements import CreateEngagementInput

    client = container.clients.create_client(
        CreateClientInput(client_code="P003", client_name="有案件不可永久刪除")
    )
    container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="保留關聯案件",
            tax_type="vat",
            period_name="2026",
        )
    )
    container.clients.delete_client(client.id)

    with pytest.raises(ClientValidationError) as exc:
        container.clients.purge_client(client.id)

    assert exc.value.code == "client.purge.has_engagements"
    raw = container.conn.execute(
        "SELECT deleted_at FROM clients WHERE id = ?", (client.id,)
    ).fetchone()
    assert raw is not None
    assert raw["deleted_at"] is not None


# ---------------------------------------------------------------------------
# Bulk service
# ---------------------------------------------------------------------------


def test_parse_clipboard_tab_delimited() -> None:
    text = "客戶代號\t客戶名稱\t統一編號\nB001\t批量公司甲\t12345678\n"
    headers, rows = parse_clipboard_text(text)
    assert headers == ["客戶代號", "客戶名稱", "統一編號"]
    assert len(rows) == 1
    assert rows[0].data["客戶代號"] == "B001"


def test_parse_clipboard_empty_raises() -> None:
    with pytest.raises(BulkParseError) as exc:
        parse_clipboard_text("   ")
    assert exc.value.code == "client.bulk.no_valid_rows"


def test_auto_detect_mapping_chinese_headers() -> None:
    headers = ["客戶代號", "客戶名稱", "統一編號", "備註"]
    mapping = auto_detect_mapping(headers)
    assert mapping["客戶代號"] == "client_code"
    assert mapping["客戶名稱"] == "client_name"
    assert mapping["統一編號"] == "tax_id"
    assert mapping["備註"] == "note"


def test_validate_rows_marks_missing_required(container: ServiceContainer) -> None:
    raw = [RawRow(row_number=2, data={"客戶名稱": "有名無號"})]
    mapping = auto_detect_mapping(["客戶名稱"])
    results = validate_rows(raw, mapping, container.clients_repo)
    assert not results[0].is_valid
    assert any("客戶代號" in e for e in results[0].errors)


def test_validate_rows_marks_duplicate_code(container: ServiceContainer) -> None:
    container.clients.create_client(CreateClientInput(client_code="DUP1", client_name="已有"))
    headers = ["客戶代號", "客戶名稱"]
    raw = [RawRow(row_number=2, data={"客戶代號": "DUP1", "客戶名稱": "新的"})]
    mapping = auto_detect_mapping(headers)
    results = validate_rows(raw, mapping, container.clients_repo)
    assert results[0].is_valid  # warnings, not errors
    assert results[0].is_duplicate_code


def test_import_validated_creates_clients(container: ServiceContainer) -> None:
    text = "客戶代號\t客戶名稱\nIMP1\t匯入公司甲\nIMP2\t匯入公司乙\n"
    headers, raw = parse_clipboard_text(text)
    mapping = auto_detect_mapping(headers)
    vrows = validate_rows(raw, mapping, container.clients_repo)
    result = import_validated(vrows, container.clients)
    assert result.imported == 2
    assert result.skipped == 0
    assert container.clients.find_by_code("IMP1") is not None


def test_import_validated_skips_duplicate_by_default(container: ServiceContainer) -> None:
    container.clients.create_client(CreateClientInput(client_code="SK01", client_name="原有"))
    text = "客戶代號\t客戶名稱\nSK01\t覆蓋嘗試\nNEW1\t全新\n"
    headers, raw = parse_clipboard_text(text)
    mapping = auto_detect_mapping(headers)
    vrows = validate_rows(raw, mapping, container.clients_repo)
    result = import_validated(vrows, container.clients, on_duplicate_code="skip")
    assert result.imported == 1
    assert result.skipped == 1
    # original unchanged
    assert container.clients.find_by_code("SK01").client_name == "原有"


def test_import_validated_overwrites_on_policy(container: ServiceContainer) -> None:
    container.clients.create_client(CreateClientInput(client_code="OW01", client_name="舊名"))
    text = "客戶代號\t客戶名稱\nOW01\t新名\n"
    headers, raw = parse_clipboard_text(text)
    mapping = auto_detect_mapping(headers)
    vrows = validate_rows(raw, mapping, container.clients_repo)
    result = import_validated(vrows, container.clients, on_duplicate_code="overwrite")
    assert result.overwritten == 1
    assert container.clients.find_by_code("OW01").client_name == "新名"
