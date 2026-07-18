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


def test_duplicate_client_code_precedes_legacy_lease_date_validation(
    container: ServiceContainer,
) -> None:
    container.clients.create_client(
        CreateClientInput(client_code="DUP-PRECEDENCE", client_name="既有客戶")
    )

    with pytest.raises(ClientValidationError) as exc:
        container.clients.create_client(
            CreateClientInput(
                client_code="DUP-PRECEDENCE",
                client_name="重複客戶",
                lease_start="not-a-date",
            )
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


def test_create_client_persists_separate_registered_and_contact_addresses(
    container: ServiceContainer,
) -> None:
    separate = container.clients.create_client(
        CreateClientInput(
            client_code="ADDR1",
            client_name="地址分離客戶",
            registered_address="臺北市\n信義路 1 號",
            contact_address="新北市板橋路 2 號",
            contact_address_same=False,
        )
    )
    same = container.clients.create_client(
        CreateClientInput(
            client_code="ADDR2",
            client_name="地址相同客戶",
            registered_address="高雄市前鎮區 3 號",
            contact_address="不應保存的聯絡地址",
            contact_address_same=True,
        )
    )

    assert separate.registered_address == "臺北市\n信義路 1 號"
    assert separate.address == separate.registered_address
    assert separate.contact_address == "新北市板橋路 2 號"
    assert separate.contact_address_same is False
    assert same.contact_address == same.registered_address
    assert same.address == same.registered_address
    assert same.contact_address_same is True


def test_create_explicit_contact_without_same_flag_infers_independent(
    container: ServiceContainer,
) -> None:
    row = container.clients.create_client(
        CreateClientInput(
            client_code="ADDR-INFER",
            client_name="推論獨立聯絡地址",
            registered_address="A",
            contact_address="B",
        )
    )

    assert row.registered_address == "A"
    assert row.contact_address == "B"
    assert row.contact_address_same is False


def test_create_client_legacy_address_is_registered_address(
    container: ServiceContainer,
) -> None:
    row = container.clients.create_client(
        CreateClientInput(
            client_code="ADDR3",
            client_name="舊版地址客戶",
            address="臺中市西區公益路",
        )
    )

    assert row.registered_address == "臺中市西區公益路"
    assert row.address == "臺中市西區公益路"
    assert row.contact_address == "臺中市西區公益路"
    assert row.contact_address_same is True


def test_create_client_rejects_conflicting_legacy_and_registered_addresses(
    container: ServiceContainer,
) -> None:
    with pytest.raises(ClientValidationError) as exc:
        container.clients.create_client(
            CreateClientInput(
                client_code="ADDR4",
                client_name="衝突地址客戶",
                address="舊欄地址",
                registered_address="新欄地址",
            )
        )

    assert exc.value.code == "client.address.conflict"


def test_create_client_rejects_overlong_address_without_truncating(
    container: ServiceContainer,
) -> None:
    with pytest.raises(ClientValidationError) as exc:
        container.clients.create_client(
            CreateClientInput(
                client_code="ADDR5",
                client_name="地址過長客戶",
                registered_address="址" * 501,
            )
        )

    assert exc.value.code == "client.address.too_long"
    assert container.clients.find_by_code("ADDR5") is None


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


def test_update_registered_address_preserves_independent_contact_and_syncs_same(
    container: ServiceContainer,
) -> None:
    separate = container.clients.create_client(
        CreateClientInput(
            client_code="UADDR1",
            client_name="獨立聯絡地址",
            registered_address="舊登記",
            contact_address="固定聯絡",
            contact_address_same=False,
        )
    )
    same = container.clients.create_client(
        CreateClientInput(
            client_code="UADDR2",
            client_name="同步聯絡地址",
            registered_address="舊同步地址",
            contact_address_same=True,
        )
    )

    separate_updated = container.clients.update_registered_address(
        separate.id, "新登記\n完整二行"
    )
    same_updated = container.clients.update_registered_address(same.id, None)

    assert separate_updated.registered_address == "新登記\n完整二行"
    assert separate_updated.address == "新登記\n完整二行"
    assert separate_updated.contact_address == "固定聯絡"
    assert separate_updated.contact_address_same is False
    assert same_updated.registered_address is None
    assert same_updated.address is None
    assert same_updated.contact_address is None
    assert same_updated.contact_address_same is True


def test_update_client_address_fields_roll_back_when_audit_fails(
    container: ServiceContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = container.clients.create_client(
        CreateClientInput(
            client_code="UADDR3",
            client_name="交易回滾",
            registered_address="原登記",
            contact_address="原聯絡",
            contact_address_same=False,
        )
    )
    monkeypatch.setattr(
        container.clients._audit,
        "record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        container.clients.update_client(
            original.id,
            UpdateClientInput(
                client_code=original.client_code,
                client_name=original.client_name,
                registered_address="新登記",
                contact_address="新聯絡",
                contact_address_same=True,
            ),
        )

    raw = container.conn.execute(
        "SELECT registered_address, contact_address, contact_address_same, address "
        "FROM clients WHERE id = ?",
        (original.id,),
    ).fetchone()
    assert tuple(raw) == ("原登記", "原聯絡", 0, "原登記")


def test_update_registered_address_rolls_back_on_audit_failure_and_guards_deleted(
    container: ServiceContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = container.clients.create_client(
        CreateClientInput(
            client_code="UADDR4",
            client_name="專用更新交易",
            registered_address="原登記",
            contact_address_same=True,
        )
    )
    monkeypatch.setattr(
        container.clients._audit,
        "record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        container.clients.update_registered_address(client.id, "不可提交")

    raw = container.conn.execute(
        "SELECT registered_address, contact_address, contact_address_same, address "
        "FROM clients WHERE id = ?",
        (client.id,),
    ).fetchone()
    assert tuple(raw) == ("原登記", "原登記", 1, "原登記")

    monkeypatch.undo()
    container.clients.delete_client(client.id)
    with pytest.raises(ClientValidationError) as exc:
        container.clients.update_registered_address(client.id, "刪除後不可更新")
    assert exc.value.code == "client.not_found"


def test_update_explicit_contact_without_same_flag_infers_independent_and_unset_preserves(
    container: ServiceContainer,
) -> None:
    initially_same = container.clients.create_client(
        CreateClientInput(
            client_code="UADDR-INFER1",
            client_name="原本同步",
            registered_address="登記一",
            contact_address_same=True,
        )
    )
    initially_separate = container.clients.create_client(
        CreateClientInput(
            client_code="UADDR-INFER2",
            client_name="原本獨立",
            registered_address="登記二",
            contact_address="聯絡二",
            contact_address_same=False,
        )
    )

    changed_same = container.clients.update_client(
        initially_same.id,
        UpdateClientInput(
            client_code=initially_same.client_code,
            client_name=initially_same.client_name,
            contact_address="新聯絡一",
        ),
    )
    changed_separate = container.clients.update_client(
        initially_separate.id,
        UpdateClientInput(
            client_code=initially_separate.client_code,
            client_name=initially_separate.client_name,
            contact_address="新聯絡二",
        ),
    )

    assert (changed_same.contact_address, changed_same.contact_address_same) == (
        "新聯絡一",
        False,
    )
    assert (changed_separate.contact_address, changed_separate.contact_address_same) == (
        "新聯絡二",
        False,
    )

    unchanged = container.clients.update_client(
        initially_separate.id,
        UpdateClientInput(
            client_code=initially_separate.client_code,
            client_name="只更新名稱",
        ),
    )
    assert (unchanged.contact_address, unchanged.contact_address_same) == (
        "新聯絡二",
        False,
    )


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


def test_purge_deleted_client_with_client_only_task_is_blocked(
    container: ServiceContainer,
) -> None:
    from taxops.services.tasks import CreateTaskInput

    client = container.clients.create_client(
        CreateClientInput(client_code="P004", client_name="Client-only task owner")
    )
    container.tasks.create_task(CreateTaskInput(
        engagement_id=None,
        client_id=client.id,
        title="Retained client-only task",
    ))
    container.clients.delete_client(client.id)

    with pytest.raises(ClientValidationError) as exc:
        container.clients.purge_client(client.id)

    assert exc.value.code == "client.purge.has_references"
    assert container.conn.execute(
        "SELECT deleted_at FROM clients WHERE id = ?",
        (client.id,),
    ).fetchone() is not None
    assert container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs"
        " WHERE action = 'client.purge' AND target_id = ?",
        (str(client.id),),
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "annual_reference",
    ["profile", "workspace", "profile_and_workspace"],
)
def test_purge_deleted_client_with_annual_reference_is_stably_blocked(
    container: ServiceContainer,
    annual_reference: str,
) -> None:
    client = container.clients.create_client(
        CreateClientInput(
            client_code=f"ANNUAL-{annual_reference}",
            client_name="年度資料不可永久刪除",
        )
    )
    if annual_reference in {"profile", "profile_and_workspace"}:
        container.conn.execute(
            "INSERT INTO compliance_profiles("
            "client_id, created_at, updated_at"
            ") VALUES (?, '2026-01-01', '2026-01-01')",
            (client.id,),
        )
    if annual_reference in {"workspace", "profile_and_workspace"}:
        container.conn.execute(
            "INSERT INTO annual_workspaces("
            "client_id, operation_year, fiscal_year_start_month_snapshot, "
            "created_at, updated_at"
            ") VALUES (?, 2026, 1, '2026-01-01', '2026-01-01')",
            (client.id,),
        )
    container.clients.delete_client(client.id)

    with pytest.raises(ClientValidationError) as exc:
        container.clients.purge_client(client.id)

    assert exc.value.code == "client.purge.has_references"
    preserved_client = container.conn.execute(
        "SELECT deleted_at FROM clients WHERE id = ?",
        (client.id,),
    ).fetchone()
    assert preserved_client is not None
    assert preserved_client["deleted_at"] is not None
    expected_profile_count = int(
        annual_reference in {"profile", "profile_and_workspace"}
    )
    expected_workspace_count = int(
        annual_reference in {"workspace", "profile_and_workspace"}
    )
    assert container.conn.execute(
        "SELECT COUNT(*) FROM compliance_profiles WHERE client_id = ?",
        (client.id,),
    ).fetchone()[0] == expected_profile_count
    assert container.conn.execute(
        "SELECT COUNT(*) FROM annual_workspaces WHERE client_id = ?",
        (client.id,),
    ).fetchone()[0] == expected_workspace_count
    assert container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs "
        "WHERE action = 'client.purge' AND target_id = ?",
        (str(client.id),),
    ).fetchone()[0] == 0


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


def test_bulk_import_new_address_headers_and_boolean(container: ServiceContainer) -> None:
    text = (
        "client_code\tclient_name\t登記地址\t聯絡地址\t聯絡地址同登記\n"
        "BADDR1\t新欄匯入\t臺南市一號\t嘉義市二號\t否\n"
    )
    headers, raw = parse_clipboard_text(text)
    rows = validate_rows(raw, auto_detect_mapping(headers), container.clients_repo)

    result = import_validated(rows, container.clients)

    assert result.imported == 1
    stored = container.clients.find_by_code("BADDR1")
    assert stored is not None
    assert stored.registered_address == "臺南市一號"
    assert stored.contact_address == "嘉義市二號"
    assert stored.contact_address_same is False
    assert stored.address == "臺南市一號"


def test_bulk_contact_address_without_same_flag_infers_independent(
    container: ServiceContainer,
) -> None:
    text = (
        "client_code\tclient_name\t登記地址\t聯絡地址\n"
        "BADDR-INFER\t省略同址旗標\tA\tB\n"
    )
    headers, raw = parse_clipboard_text(text)
    rows = validate_rows(raw, auto_detect_mapping(headers), container.clients_repo)

    result = import_validated(rows, container.clients)

    assert result.imported == 1
    stored = container.clients.find_by_code("BADDR-INFER")
    assert stored is not None
    assert stored.registered_address == "A"
    assert stored.contact_address == "B"
    assert stored.contact_address_same is False


def test_bulk_import_invalid_contact_address_same_is_row_error(
    container: ServiceContainer,
) -> None:
    text = (
        "client_code\tclient_name\t設籍地址\t聯絡地址同設籍\n"
        "BADDR2\t錯誤布林\t桃園市一號\t也許\n"
    )
    headers, raw = parse_clipboard_text(text)
    rows = validate_rows(raw, auto_detect_mapping(headers), container.clients_repo)

    assert rows[0].is_valid is False
    assert "client.contact_address_same.invalid" in rows[0].errors
    result = import_validated(rows, container.clients)
    assert result.imported == 0


def test_bulk_import_rejects_conflicting_legacy_and_registered_headers(
    container: ServiceContainer,
) -> None:
    text = (
        "client_code\tclient_name\t地址\t登記地址\n"
        "BADDR-CONFLICT\t衝突地址\t舊欄地址\t新欄地址\n"
    )
    headers, raw = parse_clipboard_text(text)
    rows = validate_rows(raw, auto_detect_mapping(headers), container.clients_repo)

    assert rows[0].is_valid is False
    assert "client.address.conflict" in rows[0].errors


def test_bulk_overwrite_legacy_address_preserves_independent_contact(
    container: ServiceContainer,
) -> None:
    existing = container.clients.create_client(
        CreateClientInput(
            client_code="BADDR3",
            client_name="覆寫前",
            registered_address="原登記",
            contact_address="不可清除的聯絡地址",
            contact_address_same=False,
        )
    )
    text = "client_code\tclient_name\t地址\nBADDR3\t覆寫後\t新登記\n"
    headers, raw = parse_clipboard_text(text)
    rows = validate_rows(raw, auto_detect_mapping(headers), container.clients_repo)

    result = import_validated(rows, container.clients, on_duplicate_code="overwrite")

    assert result.overwritten == 1
    stored = container.clients.get_client(existing.id)
    assert stored is not None
    assert stored.registered_address == "新登記"
    assert stored.address == "新登記"
    assert stored.contact_address == "不可清除的聯絡地址"
    assert stored.contact_address_same is False

    sync_text = (
        "client_code\tclient_name\t登記地址\t聯絡地址同登記\n"
        "BADDR3\t覆寫同步\t同步後登記\t是\n"
    )
    sync_headers, sync_raw = parse_clipboard_text(sync_text)
    sync_rows = validate_rows(
        sync_raw, auto_detect_mapping(sync_headers), container.clients_repo
    )
    sync_result = import_validated(
        sync_rows, container.clients, on_duplicate_code="overwrite"
    )
    synced = container.clients.get_client(existing.id)
    assert sync_result.overwritten == 1
    assert synced is not None
    assert synced.registered_address == "同步後登記"
    assert synced.contact_address == "同步後登記"
    assert synced.contact_address_same is True


# ── lease date validation ──────────────────────────────────────────────────────

def test_create_client_lease_invalid_date_rejected(container: ServiceContainer) -> None:
    with pytest.raises(ClientValidationError) as exc_info:
        container.clients.create_client(
            CreateClientInput(
                client_code="L001",
                client_name="租約測試",
                lease_start="2026-02-31",
            )
        )
    assert exc_info.value.code == "client.lease_date.invalid"


def test_create_client_lease_range_invalid_rejected(container: ServiceContainer) -> None:
    with pytest.raises(ClientValidationError) as exc_info:
        container.clients.create_client(
            CreateClientInput(
                client_code="L002",
                client_name="租約測試",
                lease_start="2026-12-31",
                lease_end="2026-01-01",
            )
        )
    assert exc_info.value.code == "client.lease_range.invalid"


def test_create_client_lease_valid_accepted(container: ServiceContainer) -> None:
    row = container.clients.create_client(
        CreateClientInput(
            client_code="L003",
            client_name="租約測試",
            lease_start="2026-01-01",
            lease_end="2026-12-31",
        )
    )
    assert row.lease_start == "2026-01-01"
    assert row.lease_end == "2026-12-31"


def test_update_client_lease_invalid_date_rejected(container: ServiceContainer) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="L004", client_name="租約更新")
    )
    with pytest.raises(ClientValidationError) as exc_info:
        container.clients.update_client(
            client.id,
            UpdateClientInput(
                client_code="L004",
                client_name="租約更新",
                lease_start="not-a-date",
            ),
        )
    assert exc_info.value.code == "client.lease_date.invalid"


def test_update_client_lease_range_invalid_rejected(container: ServiceContainer) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="L005", client_name="租約更新2")
    )
    with pytest.raises(ClientValidationError) as exc_info:
        container.clients.update_client(
            client.id,
            UpdateClientInput(
                client_code="L005",
                client_name="租約更新2",
                lease_start="2026-06-01",
                lease_end="2026-05-01",
            ),
        )
    assert exc_info.value.code == "client.lease_range.invalid"
