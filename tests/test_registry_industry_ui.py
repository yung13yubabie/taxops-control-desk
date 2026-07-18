from __future__ import annotations

import re

import pytest

from taxops.services.clients import CreateClientInput


def _seed_registry(container, **overrides):
    values = {
        "tax_id": "53821476",
        "business_name": "精準資訊股份有限公司",
        "business_address": "臺北市信義區測試路1號",
        "industry_code_primary": "6201",
        "industry_name_primary": "電腦程式設計業",
        "industry_code_1": "7409",
        "industry_name_1": "其他專門設計業",
        "industry_code_2": "6312",
        "industry_name_2": "資料處理服務業",
        "industry_code_3": None,
        "industry_name_3": None,
        "cache_version": "20260716",
    }
    values.update(overrides)
    container.conn.execute(
        """
        INSERT INTO tax_registry_cache(
            tax_id, business_name, business_address,
            industry_code_primary, industry_name_primary,
            industry_code_1, industry_name_1,
            industry_code_2, industry_name_2,
            industry_code_3, industry_name_3, cache_version, imported_at
        ) VALUES (
            :tax_id, :business_name, :business_address,
            :industry_code_primary, :industry_name_primary,
            :industry_code_1, :industry_name_1,
            :industry_code_2, :industry_name_2,
            :industry_code_3, :industry_name_3, :cache_version, datetime('now')
        )
        """,
        values,
    )
    container.conn.commit()
    return container.conn.execute(
        "SELECT * FROM tax_registry_cache WHERE tax_id = ?", (values["tax_id"],)
    ).fetchone()


def test_search_finds_primary_and_secondary_industry_code_and_name(container):
    _seed_registry(container)

    for query in ("6201", "電腦程式", "7409", "其他專門", "6312", "資料處理"):
        assert [r["tax_id"] for r in container.tax_registry_repo.search(query)] == [
            "53821476"
        ]


def test_search_preserves_exact_name_precedence_limit_and_literal_wildcards(container):
    _seed_registry(container, tax_id="11111111", business_name="相同名稱")
    _seed_registry(container, tax_id="22222222", business_name="相同名稱")
    _seed_registry(container, tax_id="33333333", business_name="相同名稱分店")

    assert [r["tax_id"] for r in container.tax_registry_repo.search("相同名稱", limit=1)] == [
        "11111111"
    ]
    assert container.tax_registry_repo.search("%' OR 1=1 --") == []
    assert container.tax_registry_repo.search("%") == []


def test_exact_tax_id_hit_executes_one_indexable_select_without_like_or_cte(container):
    _seed_registry(container, tax_id="24681357")
    statements: list[str] = []
    container.conn.set_trace_callback(statements.append)
    try:
        rows = container.tax_registry_repo.search("24681357", limit=20)
    finally:
        container.conn.set_trace_callback(None)

    assert [row["tax_id"] for row in rows] == ["24681357"]
    selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    assert len(selects) == 1
    actual_sql = selects[0]
    normalized_sql = re.sub(r"\s+", " ", actual_sql.strip()).upper()
    assert normalized_sql.startswith("SELECT ")
    assert " FROM TAX_REGISTRY_CACHE " in normalized_sql
    assert re.search(r"\bWHERE TAX_ID\s*=", normalized_sql)
    assert "WITH" not in normalized_sql
    assert "LIKE" not in normalized_sql

    plan = container.conn.execute(f"EXPLAIN QUERY PLAN {actual_sql}").fetchall()
    details = "\n".join(str(row["detail"]) for row in plan)
    assert "idx_tax_registry_cache_tax_id" in details
    assert "SCAN" not in details.upper()
    assert "TEMP B-TREE" not in details.upper()


def test_exact_tax_id_miss_falls_back_to_name_and_industry_search(container):
    _seed_registry(
        container,
        tax_id="13572468",
        business_name="代碼 87654321 公司",
        industry_code_1="87654321",
        industry_name_1="八位數行業代碼測試",
    )
    statements: list[str] = []
    container.conn.set_trace_callback(statements.append)
    try:
        rows = container.tax_registry_repo.search("87654321", limit=1)
    finally:
        container.conn.set_trace_callback(None)

    assert [row["tax_id"] for row in rows] == ["13572468"]
    selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]
    assert len(selects) == 2
    exact_sql = re.sub(r"\s+", " ", selects[0].strip()).upper()
    fallback_sql = re.sub(r"\s+", " ", selects[1].strip()).upper()
    assert re.search(r"\bWHERE TAX_ID\s*=", exact_sql)
    assert "LIKE" not in exact_sql
    assert "LIKE" in fallback_sql


def test_registry_search_ui_explicitly_mentions_industry_queries(container, qapp):
    from PySide6.QtWidgets import QGroupBox

    from taxops.ui.dialogs.new_client_dialog import NewClientDialog
    from taxops.ui.pages.registry_page import RegistryPage

    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    page = RegistryPage(container)

    assert "行業代碼／名稱" in dialog._search_input.placeholderText()
    assert any(
        "行業代碼／名稱" in group.title()
        for group in dialog.findChildren(QGroupBox)
    )
    assert "行業代碼／名稱" in page._query_edit.placeholderText()


def test_registry_page_shows_primary_column_all_unique_industries_and_gcis_unavailable(
    container, qapp,
):
    from taxops.ui.pages.registry_page import RegistryPage

    row = dict(_seed_registry(container, industry_code_2="7409", industry_name_2="其他專門設計業"))
    page = RegistryPage(container)
    page._populate_results_table([row])

    assert page._results_table.columnCount() == 4
    assert page._results_table.horizontalHeaderItem(3).text() == "主要行業"
    assert page._results_table.item(0, 3).text() == "6201 電腦程式設計業"
    assert page._result_labels["industries"].text().splitlines() == [
        "6201 電腦程式設計業",
        "7409 其他專門設計業",
    ]

    page._show_gcis_result(
        {
            "tax_id": "20828393",
            "business_name": "GCIS 公司",
            "business_address": "臺北市",
            "source": "GCIS 官方線上查詢",
        }
    )
    assert page._result_labels["industries"].text() == "此來源未提供行業資料"


def test_secondary_only_registry_data_is_never_promoted_to_primary(container, qapp):
    from taxops.services.registry.industries import (
        industries_from_registry,
        primary_industry_display,
    )
    from taxops.ui.pages.registry_page import RegistryPage

    row = dict(
        _seed_registry(
            container,
            tax_id="53821477",
            industry_code_primary=None,
            industry_name_primary=None,
            industry_code_1="7409",
            industry_name_1="其他專門設計業",
            industry_code_2=None,
            industry_name_2=None,
        )
    )

    industries = industries_from_registry(row)
    assert [(item.industry_code, item.is_primary) for item in industries] == [
        ("7409", False)
    ]
    assert primary_industry_display(row) is None

    page = RegistryPage(container)
    page._populate_results_table([row])
    assert page._results_table.item(0, 3).text() == "此來源未提供主要行業"
    assert page._result_labels["industries"].text() == "7409 其他專門設計業"


def test_existing_apply_real_click_persists_industries_and_preserves_multiline_contact(
    container, monkeypatch, qapp
):
    from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog

    client = container.clients.create_client(
        CreateClientInput(
            client_code="RI001",
            client_name="舊名稱",
            registered_address="舊登記地址",
            contact_address="一樓收件\n請先電話聯絡",
            contact_address_same=False,
        )
    )
    row = _seed_registry(container)
    monkeypatch.setattr(
        "taxops.ui.dialogs.registry_apply_dialog.QMessageBox.critical",
        lambda *_args: None,
    )
    dialog = RegistryApplyDialog(row, client, container)
    assert "industries" in dialog._checkboxes

    dialog._ok_btn.click()

    saved = container.clients.get_client(client.id)
    assert saved is not None
    assert saved.registered_address == "臺北市信義區測試路1號"
    assert saved.contact_address == "一樓收件\n請先電話聯絡"
    assert [
        (r.code, r.name, r.is_primary)
        for r in container.client_industries.list_for_client(client.id)
    ] == [
        ("6201", "電腦程式設計業", True),
        ("7409", "其他專門設計業", False),
        ("6312", "資料處理服務業", False),
    ]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_registry_address_apply_breaks_same_flag_and_preserves_exact_old_contact(
    container, qapp
):
    from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog

    old_address = "舊登記地址\n舊地址第二行"
    client = container.clients.create_client(
        CreateClientInput(
            client_code="RI-SAME",
            client_name="地址相同客戶",
            registered_address=old_address,
            contact_address=old_address,
            contact_address_same=True,
        )
    )
    row = _seed_registry(
        container,
        tax_id="53821478",
        business_address="新登記地址\n新地址第二行",
    )
    dialog = RegistryApplyDialog(row, client, container)

    assert "只更新登記地址，既有聯絡地址不會被覆寫" in dialog.address_notice.text()
    dialog._ok_btn.click()

    saved = container.clients.get_client(client.id)
    assert saved is not None
    assert saved.registered_address == "新登記地址\n新地址第二行"
    assert saved.contact_address == old_address
    assert saved.contact_address_same is False


def test_existing_apply_rolls_back_and_reenables_button_without_fake_success(
    container, monkeypatch, qapp
):
    from taxops.services.client_industries import IndustryInput
    from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="RI002", client_name="不可變", registered_address="舊址")
    )
    container.client_industries.replace_from_registry(
        client.id, [IndustryInput("OLD", "舊行業", True)], "manual", None
    )
    row = _seed_registry(container, tax_id="12344321")
    baseline_client = dict(
        container.conn.execute("SELECT * FROM clients WHERE id = ?", (client.id,)).fetchone()
    )
    baseline_industries = [
        dict(row)
        for row in container.conn.execute(
            "SELECT * FROM client_industries WHERE client_id = ? ORDER BY id",
            (client.id,),
        ).fetchall()
    ]
    baseline_audits = [
        dict(row)
        for row in container.conn.execute(
            "SELECT * FROM audit_logs ORDER BY id"
        ).fetchall()
    ]
    baseline_fts = [
        tuple(row)
        for row in container.conn.execute(
            "SELECT rowid, client_code, client_name, tax_id, short_name, contact_name, note "
            "FROM fts_clients ORDER BY rowid"
        ).fetchall()
    ]
    errors: list[str] = []
    original_record = container.audit.record

    def fail_final_registry_audit(**kwargs):
        if kwargs["action"] == "client.registry.apply":
            raise RuntimeError("final registry audit failed")
        return original_record(**kwargs)

    monkeypatch.setattr(
        container.audit,
        "record",
        fail_final_registry_audit,
    )
    monkeypatch.setattr(
        "taxops.ui.dialogs.registry_apply_dialog.QMessageBox.critical",
        lambda _parent, _title, body: errors.append(body),
    )
    dialog = RegistryApplyDialog(row, client, container)

    dialog._ok_btn.click()

    assert dict(
        container.conn.execute("SELECT * FROM clients WHERE id = ?", (client.id,)).fetchone()
    ) == baseline_client
    assert [
        dict(row)
        for row in container.conn.execute(
            "SELECT * FROM client_industries WHERE client_id = ? ORDER BY id",
            (client.id,),
        ).fetchall()
    ] == baseline_industries
    assert [
        dict(row) for row in container.conn.execute("SELECT * FROM audit_logs ORDER BY id")
    ] == baseline_audits
    assert [
        tuple(row)
        for row in container.conn.execute(
            "SELECT rowid, client_code, client_name, tax_id, short_name, contact_name, note "
            "FROM fts_clients ORDER BY rowid"
        ).fetchall()
    ] == baseline_fts
    assert dialog.result() != dialog.DialogCode.Accepted
    assert dialog._ok_btn.isEnabled()
    assert errors


def test_existing_apply_double_click_is_idempotent(container, qapp):
    from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="RI003", client_name="舊名稱")
    )
    row = _seed_registry(container, tax_id="88887777")
    dialog = RegistryApplyDialog(row, client, container)

    dialog._ok_btn.click()
    dialog._ok_btn.click()

    assert [r.code for r in container.client_industries.list_for_client(client.id)] == [
        "6201", "7409", "6312"
    ]
    audits = container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'client.registry.apply' AND target_id = ?",
        (str(client.id),),
    ).fetchone()[0]
    assert audits == 1


def test_new_client_lookup_shows_primary_and_creates_client_with_industries_atomically(
    container, qapp, monkeypatch
):
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    _seed_registry(container, tax_id="55667788")
    errors: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.QMessageBox.warning",
        lambda _parent, _title, body: errors.append(body),
    )
    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog._search_input.setText("55667788")
    dialog._search_btn.click()
    assert "6201 電腦程式設計業" in dialog._result_combo.itemText(0)
    dialog._result_combo.setCurrentIndex(0)
    dialog._fill_btn.click()
    dialog.profile_form.client_code.setText("NEW-REG")

    dialog.save_button.click()

    saved = container.clients.find_by_code("NEW-REG")
    assert saved is not None, errors
    assert saved.registered_address == "臺北市信義區測試路1號"
    assert [row.code for row in container.client_industries.list_for_client(saved.id)] == [
        "6201", "7409", "6312"
    ]
    assert errors == []


def test_new_client_secondary_only_registry_snapshot_persists_without_fake_primary(
    container, qapp, monkeypatch
):
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    _seed_registry(
        container,
        tax_id="55667789",
        industry_code_primary=None,
        industry_name_primary=None,
        industry_code_1="7409",
        industry_name_1="其他專門設計業",
        industry_code_2=None,
        industry_name_2=None,
    )
    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.QMessageBox.warning", lambda *_args: None
    )
    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog._search_input.setText("55667789")
    dialog._search_btn.click()
    assert "7409" not in dialog._result_combo.itemText(0)
    dialog._result_combo.setCurrentIndex(0)
    dialog._fill_btn.click()
    dialog.profile_form.client_code.setText("NEW-SECONDARY")
    dialog.save_button.click()

    saved = container.clients.find_by_code("NEW-SECONDARY")
    assert saved is not None
    industries = container.client_industries.list_for_client(saved.id)
    assert [(row.code, row.is_primary) for row in industries] == [("7409", False)]


def test_new_client_staged_lease_and_registry_industries_share_one_transaction(
    container, qapp, monkeypatch
):
    from taxops.services.client_leases import LeaseInput
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    _seed_registry(container, tax_id="66778899")
    monkeypatch.setattr(
        "taxops.ui.dialogs.new_client_dialog.QMessageBox.warning", lambda *_args: None
    )
    dialog = NewClientDialog(container, tax_registry_repo=container.tax_registry_repo)
    dialog._search_input.setText("66778899")
    dialog._search_btn.click()
    dialog._result_combo.setCurrentIndex(0)
    dialog._fill_btn.click()
    dialog.profile_form.client_code.setText("NEW-LEASE-REG")
    dialog.add_staged_lease(
        LeaseInput(
            lease_name="信義辦公室",
            premises_address="臺北市信義區測試路1號",
            start_date="2026-01-01",
            end_date="2026-12-31",
        )
    )

    dialog.save_button.click()

    saved = container.clients.find_by_code("NEW-LEASE-REG")
    assert saved is not None
    assert [lease.lease_name for lease in container.client_leases.list_for_client(saved.id)] == [
        "信義辦公室"
    ]
    assert [row.code for row in container.client_industries.list_for_client(saved.id)] == [
        "6201", "7409", "6312"
    ]


def test_new_profile_industry_audit_failure_rolls_back_client_lease_and_industry(
    container, monkeypatch
):
    from taxops.services.client_industries import IndustryInput
    from taxops.services.client_leases import LeaseInput

    original_record = container.audit.record
    baseline_audits = [
        dict(row) for row in container.conn.execute("SELECT * FROM audit_logs ORDER BY id")
    ]
    baseline_fts = [
        tuple(row)
        for row in container.conn.execute(
            "SELECT rowid, client_code, client_name, tax_id, short_name, contact_name, note "
            "FROM fts_clients ORDER BY rowid"
        ).fetchall()
    ]

    def fail_industry_audit(**kwargs):
        if kwargs["action"] == "client.industries.replace":
            raise RuntimeError("industry audit failed")
        return original_record(**kwargs)

    monkeypatch.setattr(container.audit, "record", fail_industry_audit)
    try:
        container.client_profiles.create_client_with_leases(
            CreateClientInput(client_code="ROLLBACK-REG", client_name="應回滾"),
            [
                LeaseInput(
                    lease_name="應回滾租約",
                    premises_address="臺北市",
                    start_date="2026-01-01",
                    end_date="2026-12-31",
                )
            ],
            industries=[IndustryInput("6201", "電腦程式設計業", True)],
            industry_source="MOF-BGMOPEN1",
            industry_source_version="20260716",
        )
    except RuntimeError as exc:
        assert str(exc) == "industry audit failed"
    else:
        raise AssertionError("expected industry audit failure")

    assert container.clients.find_by_code("ROLLBACK-REG") is None
    assert container.conn.execute(
        "SELECT COUNT(*) FROM client_leases WHERE lease_name = '應回滾租約'"
    ).fetchone()[0] == 0
    assert container.conn.execute(
        "SELECT COUNT(*) FROM client_industries WHERE industry_code = '6201'"
    ).fetchone()[0] == 0
    assert [
        dict(row) for row in container.conn.execute("SELECT * FROM audit_logs ORDER BY id")
    ] == baseline_audits
    assert [
        tuple(row)
        for row in container.conn.execute(
            "SELECT rowid, client_code, client_name, tax_id, short_name, contact_name, note "
            "FROM fts_clients ORDER BY rowid"
        ).fetchall()
    ] == baseline_fts


def test_registry_industry_source_version_and_single_primary_are_exact(container, qapp):
    from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog

    client = container.clients.create_client(
        CreateClientInput(client_code="RI-SOURCE", client_name="來源客戶")
    )
    row = _seed_registry(container, tax_id="53821479", cache_version="2026-07-17-v2")
    dialog = RegistryApplyDialog(row, client, container)
    dialog._ok_btn.click()

    industries = container.client_industries.list_for_client(client.id)
    assert {item.source for item in industries} == {"MOF-BGMOPEN1"}
    assert {item.source_version for item in industries} == {"2026-07-17-v2"}
    assert sum(item.is_primary for item in industries) == 1
    assert len({item.code for item in industries}) == len(industries)


def test_registry_client_service_rejects_mixed_sqlite_connections(
    container, tmp_path
):
    from taxops.db.connection import open_connection
    from taxops.repositories.client_industries import ClientIndustriesRepository
    from taxops.repositories.clients import ClientsRepository
    from taxops.repositories.search import SearchRepository
    from taxops.services.registry_client import RegistryClientService

    other = open_connection(tmp_path / "miswired-registry.sqlite")
    try:
        with pytest.raises(ValueError, match="registry_client.connection.mismatch"):
            RegistryClientService(
                container.conn,
                ClientsRepository(other),
                ClientIndustriesRepository(container.conn),
                container.audit,
                SearchRepository(container.conn),
            )
    finally:
        other.close()


def test_registry_page_apply_button_executes_real_dialog_and_persists_industries(
    container, qapp, monkeypatch
):
    from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog as RealDialog
    from taxops.ui.pages.registry_page import RegistryPage

    client = container.clients.create_client(
        CreateClientInput(client_code="PAGE-REG", client_name="舊名稱")
    )
    row = dict(_seed_registry(container, tax_id="90909090"))

    class SubmitDialog(RealDialog):
        def exec(self):
            self._ok_btn.click()
            return self.result()

    monkeypatch.setattr("taxops.ui.pages.registry_page.RegistryApplyDialog", SubmitDialog)
    monkeypatch.setattr(
        "taxops.ui.pages.registry_page.QMessageBox.information", lambda *_args: None
    )
    page = RegistryPage(container)
    page._set_result(row)
    page._client_combo.setCurrentIndex(page._client_combo.findData(client.id))

    page._apply_btn.click()

    assert [
        industry.code
        for industry in container.client_industries.list_for_client(client.id)
    ] == [
        "6201", "7409", "6312"
    ]
