"""Tests for Slice 13: 工商 / 稅籍查詢頁完整化.

Covers: local search success/not-found, "公司不存在" prohibition,
apply-to-client diff dialog, audit log, UI handler integration,
action_registry contracts.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _wait_for_local_search(page, timeout: float = 5.0) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    app = _make_app()
    deadline = time.monotonic() + timeout
    worker = page._local_worker
    assert worker is not None
    while worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert not worker.isRunning()
    assert worker.wait(1_000)
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert page._local_worker is None


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

    def test_search_exact_same_name_returns_all_matching_businesses(self):
        container = _fresh_container()
        _seed_registry(container, tax_id="11111111", business_name="同名商號")
        _seed_registry(container, tax_id="22222222", business_name="同名商號")

        rows = container.tax_registry_repo.search("同名商號", limit=20)

        assert [row["tax_id"] for row in rows] == ["11111111", "22222222"]

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
        _wait_for_local_search(page)
        assert page._result_group.isHidden()
        assert not page._apply_btn.isEnabled()
        assert page._result is None

    def test_search_not_found_status_no_company_not_exist(self):
        container = _fresh_container()
        page = self._make_page(container)
        page._query_edit.setText("00000000")
        page._on_search_local()
        _wait_for_local_search(page)
        assert "公司不存在" not in page._status_label.text()

    def test_search_not_found_shows_cache_message(self):
        container = _fresh_container()
        page = self._make_page(container)
        page._query_edit.setText("00000000")
        page._on_search_local()
        _wait_for_local_search(page)
        assert "快取" in page._status_label.text()

    def test_empty_query_does_not_crash(self):
        container = _fresh_container()
        page = self._make_page(container)
        page._query_edit.setText("")
        page._on_search_local()
        assert not page._result_group.isVisible()

    def test_gcis_button_is_enabled_official_online_fallback(self):
        container = _fresh_container()
        page = self._make_page(container)
        assert page._gcis_btn.isEnabled()

    def test_gcis_button_queries_official_service_and_displays_result(self, monkeypatch):
        import time
        from PySide6.QtWidgets import QApplication

        container = _fresh_container()
        page = self._make_page(container)
        monkeypatch.setattr(
            "taxops.ui.pages.registry_page.query_gcis_by_tax_id",
            lambda tax_id: {
                "tax_id": tax_id,
                "business_name": "GCIS 補查公司",
                "business_address": "臺北市官方路1號",
                "organization_type": "公司",
                "registered_date_roc": "1150101",
                "business_status": "核准設立",
                "source": "GCIS 官方線上查詢",
            },
        )
        page._query_edit.setText("20828393")

        page._gcis_btn.click()

        deadline = time.monotonic() + 2
        while page._gcis_worker is not None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        assert page._result["business_name"] == "GCIS 補查公司"
        assert not page._result_group.isHidden()
        assert "GCIS" in page._status_label.text()

    def test_local_name_search_runs_in_worker_and_offers_multiple_results(self, monkeypatch):
        import time
        from PySide6.QtWidgets import QApplication

        container = _fresh_container()
        _seed_registry(container, tax_id="11111111", business_name="同名商號")
        _seed_registry(container, tax_id="22222222", business_name="同名商號")
        page = self._make_page(container)
        page._query_edit.setText("同名商號")

        page._search_btn.click()
        deadline = time.monotonic() + 3
        while page.has_active_operation() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        assert not page.has_active_operation()
        assert page._results_table.rowCount() == 2
        page._results_table.selectRow(1)
        QApplication.processEvents()
        assert page._result["tax_id"] == "22222222"

    def test_background_result_is_ignored_if_query_changed_programmatically(self):
        container = _fresh_container()
        page = self._make_page(container)
        page._query_edit.setText("新的查詢")

        page._show_local_results(
            [
                {
                    "tax_id": "11111111",
                    "business_name": "舊結果",
                    "business_address": "舊地址",
                }
            ],
            expected_query="舊的查詢",
        )

        assert page._result is None
        assert page._results_table.rowCount() == 0
        assert "已忽略" in page._status_label.text()

    def test_background_searches_are_mutually_exclusive_and_disable_both_buttons(
        self, monkeypatch
    ):
        container = _fresh_container()
        page = self._make_page(container)
        sentinel = object()
        page._gcis_worker = sentinel
        page._query_edit.setText("同名企業")

        page._on_search_local()

        assert page._local_worker is None
        page._gcis_worker = None

        class FakeLocalWorker:
            pass

        page._local_worker = FakeLocalWorker()
        page._query_edit.setText("20828393")
        page._on_search_gcis()
        assert page._gcis_worker is None

    def test_gcis_search_clears_stale_local_choices(self, monkeypatch):
        container = _fresh_container()
        page = self._make_page(container)
        page._populate_results_table(
            [
                {
                    "tax_id": "11111111",
                    "business_name": "舊的本機結果",
                    "business_address": "舊地址",
                }
            ]
        )
        monkeypatch.setattr(
            "taxops.ui.pages.registry_page._GCISWorker.start", lambda _worker: None
        )
        page._query_edit.setText("20828393")

        page._on_search_gcis()

        assert page._results_table.rowCount() == 0
        assert page._results_table.isHidden()
        assert not page._query_edit.isEnabled()
        assert not page._search_btn.isEnabled()
        assert not page._gcis_btn.isEnabled()

    def test_gcis_invalid_busy_not_found_and_error_paths_are_visible(self, monkeypatch):
        import time
        from PySide6.QtWidgets import QApplication
        from taxops.services.gcis import GCISQueryError

        container = _fresh_container()
        page = self._make_page(container)

        page._query_edit.setText("bad")
        page._on_search_gcis()
        assert page._result is None
        assert "8" in page._status_label.text()

        sentinel = object()
        page._gcis_worker = sentinel
        page._query_edit.setText("20828393")
        page._on_search_gcis()
        assert page._gcis_worker is sentinel
        assert page.has_active_operation()

        page._gcis_worker = None
        page._show_gcis_result(None)
        assert page._result is None
        assert not page._apply_btn.isEnabled()
        assert not page.has_active_operation()

        monkeypatch.setattr(
            "taxops.ui.pages.registry_page.query_gcis_by_tax_id",
            lambda _tax_id: (_ for _ in ()).throw(GCISQueryError("gcis.network_error")),
        )
        page._on_search_gcis()
        deadline = time.monotonic() + 2
        while page._gcis_worker is not None and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        assert page._gcis_worker is None
        assert page._gcis_btn.isEnabled()
        assert page._result is None
        assert page._status_label.text()

    def test_apply_btn_disabled_before_search(self):
        container = _fresh_container()
        page = self._make_page(container)
        assert not page._apply_btn.isEnabled()

    def test_load_clients_populates_combo(self):
        container = _fresh_container()
        _seed_client(container, client_code="LOAD01", client_name="載入測試客戶")
        page = self._make_page(container)
        assert page._client_combo.count() >= 2

    def test_client_filter_can_find_customer_outside_initial_dropdown(self, monkeypatch):
        container = _fresh_container()
        target_id = _seed_client(
            container,
            client_code="FIND501",
            client_name="篩選才能找到的客戶",
        )
        page = self._make_page(container)
        monkeypatch.setattr(
            container.clients,
            "list_clients",
            lambda **_kwargs: [],
        )
        page._load_clients()
        assert page._client_combo.findData(target_id) == -1

        page._client_filter_edit.setText("FIND501")
        page._client_filter_btn.click()

        assert page._client_combo.findData(target_id) >= 0

    def test_search_button_failure_clears_stale_result_and_shows_status(self, monkeypatch):
        container = _fresh_container()
        _seed_registry(container, tax_id="11223344", business_name="先前結果")
        page = self._make_page(container)
        page._query_edit.setText("11223344")
        page._search_btn.click()
        assert page._result is not None
        monkeypatch.setattr(
            container.tax_registry_repo,
            "find_by_tax_id",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db locked")),
        )

        page._query_edit.setText("55667788")
        page._search_btn.click()

        assert page._result is None
        assert page._result_group.isHidden()
        assert page._status_label.text() == "查詢失敗，請稍後再試。"

    def test_load_clients_failure_is_visible_in_combo(self, monkeypatch):
        container = _fresh_container()
        page = self._make_page(container)
        monkeypatch.setattr(
            container.clients,
            "list_clients",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("db locked")),
        )

        page.refresh_context()

        assert page._client_combo.itemText(1) == "（客戶資料載入失敗，請重新整理）"

    def test_apply_guards_no_result_no_client_and_missing_client(self, monkeypatch):
        container = _fresh_container()
        _seed_registry(container, tax_id="55667788", business_name="套用公司")
        page = self._make_page(container)
        warnings: list[str] = []
        monkeypatch.setattr(
            "taxops.ui.pages.registry_page.QMessageBox.warning",
            lambda _parent, _title, body: warnings.append(body),
        )

        page._on_apply_to_client()
        page._query_edit.setText("55667788")
        page._search_btn.click()
        page._apply_btn.click()
        assert warnings == [
            "請先查詢稅籍資料後再套用。",
            "請先選擇要更新的客戶。",
        ]

        page._client_combo.addItem("已刪除客戶", 99999)
        page._client_combo.setCurrentIndex(page._client_combo.count() - 1)
        page._apply_btn.click()
        assert warnings[-1] == "找不到選取的客戶資料。"

    def test_apply_real_dialog_updates_exact_client_and_reports_success(self, monkeypatch):
        from taxops.ui.dialogs.registry_apply_dialog import RegistryApplyDialog as RealDialog

        container = _fresh_container()
        client_id = _seed_client(
            container, client_code="APPLY01", client_name="舊公司名", address="舊地址"
        )
        _seed_registry(
            container,
            tax_id="87654321",
            business_name="新公司名",
        )

        class SubmitDialog(RealDialog):
            def exec(self):
                for checkbox in self._checkboxes.values():
                    checkbox.setChecked(True)
                self._on_save()
                return self.result()

        monkeypatch.setattr("taxops.ui.pages.registry_page.RegistryApplyDialog", SubmitDialog)
        infos: list[str] = []
        monkeypatch.setattr(
            "taxops.ui.pages.registry_page.QMessageBox.information",
            lambda _parent, _title, body: infos.append(body),
        )
        page = self._make_page(container)
        page._query_edit.setText("87654321")
        page._search_btn.click()
        page._client_combo.setCurrentIndex(page._client_combo.findData(client_id))

        page._apply_btn.click()

        updated = container.clients.get_client(client_id)
        assert (updated.client_name, updated.tax_id, updated.address) == (
            "新公司名",
            "87654321",
            "台北市中正區測試路1號",
        )
        assert infos == ["客戶資料已依官方登記資料更新。"]

    def test_refresh_preserves_client_selection(self):
        container = _fresh_container()
        _seed_client(container, client_code="KEEP01", client_name="第一位")
        selected_id = _seed_client(container, client_code="KEEP02", client_name="保留選取")
        page = self._make_page(container)
        page._client_combo.setCurrentIndex(page._client_combo.findData(selected_id))

        page.refresh_context()

        assert page._client_combo.currentData() == selected_id

    def test_apply_client_load_failure_is_critical_and_dialog_does_not_open(self, monkeypatch):
        container = _fresh_container()
        client_id = _seed_client(container, client_code="BROKEN01", client_name="讀取失敗")
        _seed_registry(container, tax_id="33445566", business_name="查詢成功")
        page = self._make_page(container)
        page._query_edit.setText("33445566")
        page._search_btn.click()
        page._client_combo.setCurrentIndex(page._client_combo.findData(client_id))
        criticals: list[str] = []
        monkeypatch.setattr(
            container.clients,
            "get_client",
            lambda _client_id: (_ for _ in ()).throw(RuntimeError("db locked")),
        )
        monkeypatch.setattr(
            "taxops.ui.pages.registry_page.QMessageBox.critical",
            lambda _parent, _title, body: criticals.append(body),
        )

        page._apply_btn.click()

        assert criticals == ["無法載入客戶資料，請稍後再試。"]


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
        _seed_client(container, client_code="AUDIT1", client_name="舊名", address="舊地址")
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

    def test_gcis_button_has_enabled_official_query_contract(self):
        from taxops.ui.action_registry import ACTION_REGISTRY, PAGE_REGISTRY

        contract = next(
            a for a in ACTION_REGISTRY
            if a.page == PAGE_REGISTRY and a.button_label == "GCIS 工商查詢"
        )
        assert contract.enabled
        assert contract.handler == "RegistryPage._on_search_gcis"
        assert contract.service == "query_gcis_by_tax_id"

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
