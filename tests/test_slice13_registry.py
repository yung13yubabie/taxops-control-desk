"""Tests for Slice 13: 工商 / 稅籍查詢頁完整化.

Covers: local search success/not-found, "公司不存在" prohibition,
apply-to-client diff dialog, audit log, UI handler integration,
action_registry contracts.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _fresh_container():
    from taxops.core.paths import resolve_paths
    from taxops.db.connection import open_connection
    from taxops.db.migrate import apply_migrations
    from taxops.services.container import build_container

    tmp = pathlib.Path(tempfile.mkdtemp())
    paths = resolve_paths(override_root=tmp / "TestSlice13")
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    conn = open_connection(paths.db_path)
    apply_migrations(conn)
    return build_container(paths, conn)


def _seed_registry(container, *, tax_id: str = "12345678", business_name: str = "測試公司") -> None:
    conn = container.conn
    conn.execute(
        "INSERT INTO tax_registry_cache("
        "tax_id, business_name, business_address, cache_version, imported_at"
        ") VALUES (?, ?, ?, ?, datetime('now'))",
        (tax_id, business_name, "台北市中正區測試路1號", "v1"),
    )
    conn.commit()


def _seed_client(container, *, client_code: str = "C001", client_name: str = "舊客戶名稱",
                 tax_id: str | None = None, address: str | None = None) -> int:
    conn = container.conn
    cur = conn.execute(
        "INSERT INTO clients(client_code, client_name, tax_id, address, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
        (client_code, client_name, tax_id, address),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Repository: TaxRegistryRepository.search
# ---------------------------------------------------------------------------

class TestRegistrySearch:
    def test_search_by_exact_tax_id(self):
        container = _fresh_container()
        _seed_registry(container, tax_id="12345678", business_name="精確查詢公司")
        rows = container.tax_registry_repo.search("12345678")
        assert len(rows) == 1
        assert rows[0]["business_name"] == "精確查詢公司"

    def test_search_by_name_partial(self):
        container = _fresh_container()
        _seed_registry(container, tax_id="87654321", business_name="部分名稱股份有限公司")
        rows = container.tax_registry_repo.search("部分名稱")
        assert len(rows) == 1
        assert rows[0]["tax_id"] == "87654321"

    def test_search_not_found_returns_empty(self):
        container = _fresh_container()
        rows = container.tax_registry_repo.search("99999999")
        assert rows == []

    def test_search_empty_query_returns_empty(self):
        container = _fresh_container()
        _seed_registry(container)
        rows = container.tax_registry_repo.search("")
        assert rows == []

    def test_search_not_found_no_company_not_exist(self):
        """查無資料時，不得在任何地方回傳「公司不存在」文字。"""
        container = _fresh_container()
        rows = container.tax_registry_repo.search("99999999")
        assert rows == []
        from taxops.ui.pages.registry_page import _NOT_FOUND_MSG
        assert "公司不存在" not in _NOT_FOUND_MSG


# ---------------------------------------------------------------------------
# RegistryPage UI handler integration
# ---------------------------------------------------------------------------

class TestRegistryPageUI:
    def setup_method(self):
        self._app = _make_app()

    def _make_page(self, container):
        from taxops.ui.pages.registry_page import RegistryPage
        return RegistryPage(container)

    def test_page_creates_without_error(self):
        container = _fresh_container()
        page = self._make_page(container)
        assert page is not None

    def test_search_found_shows_result_group(self):
        container = _fresh_container()
        _seed_registry(container, tax_id="11223344", business_name="有料公司")
        page = self._make_page(container)
        page._query_edit.setText("11223344")
        page._on_search_local()
        assert not page._result_group.isHidden()
        assert page._apply_btn.isEnabled()
        assert page._result is not None
        assert page._result["business_name"] == "有料公司"

    def test_search_not_found_hides_result_group(self):
        container = _fresh_container()
        page = self._make_page(container)
        page._query_edit.setText("00000000")
        page._on_search_local()
        assert page._result_group.isHidden()
        assert not page._apply_btn.isEnabled()
        assert page._result is None

    def test_search_not_found_status_no_company_not_exist(self):
        container = _fresh_container()
        page = self._make_page(container)
        page._query_edit.setText("00000000")
        page._on_search_local()
        assert "公司不存在" not in page._status_label.text()

    def test_search_not_found_shows_cache_message(self):
        container = _fresh_container()
        page = self._make_page(container)
        page._query_edit.setText("00000000")
        page._on_search_local()
        assert "快取" in page._status_label.text()

    def test_empty_query_does_not_crash(self):
        container = _fresh_container()
        page = self._make_page(container)
        page._query_edit.setText("")
        page._on_search_local()
        assert not page._result_group.isVisible()

    def test_gcis_button_disabled(self):
        container = _fresh_container()
        page = self._make_page(container)
        assert not page._gcis_btn.isEnabled()

    def test_apply_btn_disabled_before_search(self):
        container = _fresh_container()
        page = self._make_page(container)
        assert not page._apply_btn.isEnabled()

    def test_load_clients_populates_combo(self):
        container = _fresh_container()
        _seed_client(container, client_code="LOAD01", client_name="載入測試客戶")
        page = self._make_page(container)
        assert page._client_combo.count() >= 2


# ---------------------------------------------------------------------------
# RegistryApplyDialog
# ---------------------------------------------------------------------------

class TestRegistryApplyDialog:
    def setup_method(self):
        self._app = _make_app()

    def _make_fake_registry_row(self, conn, **kwargs):
        defaults = {
            "tax_id": "12345678",
            "business_name": "稅籍公司名",
            "business_address": "台北市中正區新地址88號",
            "cache_version": "v1",
        }
        defaults.update(kwargs)
        conn.execute(
            "INSERT INTO tax_registry_cache("
            "tax_id, business_name, business_address, cache_version, imported_at"
            ") VALUES (:tax_id, :business_name, :business_address, :cache_version, datetime('now'))",
            defaults,
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM tax_registry_cache WHERE tax_id = ?",
            (defaults["tax_id"],),
        ).fetchone()

    def test_dialog_shows_diff_fields(self):
        from taxops.repositories.clients import ClientRow
        from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog

        container = _fresh_container()
        reg_row = self._make_fake_registry_row(container.conn)
        client_row = ClientRow(
            id=1, client_code="C001", client_name="舊名稱", tax_id=None,
            short_name=None, contact_name=None, contact_phone=None,
            contact_email=None, address=None, note=None,
            created_at="2025-01-01", updated_at="2025-01-01", deleted_at=None,
        )
        dlg = RegistryApplyDialog(reg_row, client_row, container)
        assert "client_name" in dlg._checkboxes
        assert "tax_id" in dlg._checkboxes

    def test_dialog_no_diff_disables_ok(self):
        from taxops.repositories.clients import ClientRow
        from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog

        container = _fresh_container()
        reg_row = self._make_fake_registry_row(
            container.conn,
            tax_id="12345678",
            business_name="完全相同名稱",
            business_address="完全相同地址",
        )
        client_row = ClientRow(
            id=1, client_code="C002", client_name="完全相同名稱", tax_id="12345678",
            short_name=None, contact_name=None, contact_phone=None,
            contact_email=None, address="完全相同地址", note=None,
            created_at="2025-01-01", updated_at="2025-01-01", deleted_at=None,
        )
        dlg = RegistryApplyDialog(reg_row, client_row, container)
        assert dlg._checkboxes == {}
        assert not dlg._ok_btn.isEnabled()

    def test_apply_writes_audit_log(self):
        from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog

        container = _fresh_container()
        client_id = _seed_client(container, client_code="AUDIT1", client_name="舊名", address="舊地址")
        reg_row = self._make_fake_registry_row(
            container.conn,
            tax_id="99887766",
            business_name="新名稱",
            business_address="新地址",
        )
        client_rows = container.clients.list_clients(limit=10, offset=0)
        client_row = next(c for c in client_rows if c.client_code == "AUDIT1")

        dlg = RegistryApplyDialog(reg_row, client_row, container)
        dlg._on_save()

        audit_rows = container.conn.execute(
            "SELECT * FROM audit_logs WHERE action = 'client.update' ORDER BY id DESC LIMIT 5"
        ).fetchall()
        assert len(audit_rows) >= 1


# ---------------------------------------------------------------------------
# Action registry contracts
# ---------------------------------------------------------------------------

class TestRegistryActionContracts:
    def test_search_local_contract_exists(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_REGISTRY

        contracts = [a for a in ACTION_REGISTRY if a.page == PAGE_REGISTRY and a.enabled]
        labels = [a.button_label for a in contracts]
        assert "查詢本地快取" in labels

    def test_apply_to_client_contract_exists(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_REGISTRY

        contracts = [a for a in ACTION_REGISTRY if a.page == PAGE_REGISTRY and a.enabled]
        labels = [a.button_label for a in contracts]
        assert "套用至客戶主檔" in labels

    def test_gcis_button_disabled_in_registry(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_REGISTRY

        disabled = [a for a in ACTION_REGISTRY if a.page == PAGE_REGISTRY and not a.enabled]
        labels = [a.button_label for a in disabled]
        assert any("GCIS" in lbl or "工商查詢" in lbl for lbl in labels)

    def test_search_contract_has_correct_service(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_REGISTRY

        contract = next(
            a for a in ACTION_REGISTRY
            if a.page == PAGE_REGISTRY and a.button_label == "查詢本地快取"
        )
        assert "TaxRegistryRepository" in contract.service
        assert contract.test_marker == "test_registry_local_search"

    def test_apply_contract_has_audit_action(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_REGISTRY

        contract = next(
            a for a in ACTION_REGISTRY
            if a.page == PAGE_REGISTRY and a.button_label == "套用至客戶主檔"
        )
        assert contract.audit_action == "client.update"
