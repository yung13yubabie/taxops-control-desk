from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.usefixtures("qapp")
def test_clipboard_import_walks_every_visible_step_and_writes_exact_clients(
    container, monkeypatch
):
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_import_wizard.QMessageBox.information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    wizard = BulkImportWizard(container.clients, container.clients_repo)
    wizard._rb_paste.setChecked(True)
    wizard._paste_edit.setPlainText(
        "client_code\tclient_name\ttax_id\tcontact_phone\n"
        "BULK-001\t大量匯入甲公司\t12345678\t0912345678\n"
        "BULK-002\t大量匯入乙公司\t87654321\t0922333444\n"
    )

    wizard._next_btn.click()
    assert wizard._current_step() == 1
    assert set(wizard._mapping) == set()  # mapping is collected on the next step

    wizard._next_btn.click()
    assert wizard._current_step() == 2
    assert len(wizard._validation) == 2
    assert all(row.is_valid for row in wizard._validation)

    wizard._next_btn.click()
    assert wizard._current_step() == 4
    assert "2" in wizard._confirm_label.text()

    wizard._next_btn.click()
    assert wizard._current_step() == 5
    assert wizard._result is not None
    assert (wizard._result.imported, wizard._result.skipped) == (2, 0)
    assert "2" in wizard._result_label.text()

    stored = container.conn.execute(
        "SELECT client_code, client_name, tax_id FROM clients ORDER BY client_code"
    ).fetchall()
    assert [tuple(row) for row in stored] == [
        ("BULK-001", "大量匯入甲公司", "12345678"),
        ("BULK-002", "大量匯入乙公司", "87654321"),
    ]

    wizard._next_btn.click()
    assert wizard.result() == wizard.DialogCode.Accepted


@pytest.mark.usefixtures("qapp")
def test_duplicate_code_path_can_overwrite_existing_client(container):
    from taxops.services.clients import CreateClientInput
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    original = container.clients.create_client(
        CreateClientInput(client_code="BULK-DUP", client_name="原始名稱")
    )
    wizard = BulkImportWizard(container.clients, container.clients_repo)
    wizard._rb_paste.setChecked(True)
    wizard._paste_edit.setPlainText(
        "client_code\tclient_name\nBULK-DUP\t覆寫後名稱\n"
    )

    wizard._next_btn.click()
    wizard._next_btn.click()
    assert wizard._current_step() == 2
    assert wizard._validation[0].is_duplicate_code

    wizard._next_btn.click()
    assert wizard._current_step() == 3
    wizard._rb_overwrite.setChecked(True)
    wizard._next_btn.click()
    assert wizard._current_step() == 4
    wizard._next_btn.click()

    updated = container.clients.get_client(original.id)
    assert updated is not None
    assert updated.client_name == "覆寫後名稱"
    assert wizard._result is not None
    assert wizard._result.overwritten == 1


@pytest.mark.usefixtures("qapp")
def test_invalid_clipboard_data_stays_on_source_step_and_warns(
    container, monkeypatch
):
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    warnings = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_import_wizard.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    wizard = BulkImportWizard(container.clients, container.clients_repo)
    wizard._rb_paste.setChecked(True)
    wizard._paste_edit.setPlainText("")

    wizard._next_btn.click()

    assert wizard._current_step() == 0
    assert len(warnings) == 1


@pytest.mark.usefixtures("qapp")
def test_copy_template_button_writes_exact_clipboard_and_visible_feedback(
    container, monkeypatch
):
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard, _PASTE_TEMPLATE

    infos: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_import_wizard.QMessageBox.information",
        lambda _parent, _title, body: infos.append(body),
    )
    wizard = BulkImportWizard(container.clients, container.clients_repo)

    wizard._copy_template_btn.click()

    assert QApplication.clipboard().text() == _PASTE_TEMPLATE
    assert len(infos) == 1
    assert "已複製到剪貼簿" in infos[0]


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("source", ["excel", "csv"])
def test_file_source_missing_selection_and_browse_paths_are_visible(
    container, monkeypatch, tmp_path, source
):
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_import_wizard.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    wizard = BulkImportWizard(container.clients, container.clients_repo)
    if source == "excel":
        wizard._rb_excel.setChecked(True)
        selected = tmp_path / "clients.xlsx"
    else:
        wizard._rb_csv.setChecked(True)
        selected = tmp_path / "clients.csv"

    wizard._next_btn.click()
    assert wizard._current_step() == 0
    assert "請先選擇" in warnings[-1]

    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_import_wizard.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(selected), ""),
    )
    browse_button = next(
        button for button in wizard.findChildren(QPushButton) if button.text() == "選擇檔案…"
    )
    browse_button.click()
    assert wizard._file_path_label.text() == str(selected)


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("source", ["excel", "csv"])
def test_file_parse_failures_stay_on_source_step_and_sanitize_feedback(
    container, monkeypatch, tmp_path, source
):
    from taxops.services.clients_bulk import BulkParseError
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_import_wizard.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    wizard = BulkImportWizard(container.clients, container.clients_repo)
    if source == "excel":
        wizard._rb_excel.setChecked(True)
        parser_name = "parse_excel"
    else:
        wizard._rb_csv.setChecked(True)
        parser_name = "parse_csv"
    wizard._file_path_label.setText(str(tmp_path / f"broken.{source}"))
    monkeypatch.setattr(
        f"taxops.ui.dialogs.bulk_import_wizard.{parser_name}",
        lambda _path: (_ for _ in ()).throw(BulkParseError("bulk.file.invalid")),
    )

    wizard._next_btn.click()

    assert wizard._current_step() == 0
    assert len(warnings) == 1
    assert warnings[0].strip()


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("unexpected", [False, True])
def test_import_failures_stay_on_confirm_step_and_reenable_button(
    container, monkeypatch, unexpected
):
    from taxops.services.clients_bulk import BulkParseError
    from taxops.ui.dialogs.bulk_import_wizard import BulkImportWizard

    wizard = BulkImportWizard(container.clients, container.clients_repo)
    wizard._rb_paste.setChecked(True)
    wizard._paste_edit.setPlainText(
        "client_code\tclient_name\nBULK-FAIL\t失敗不得寫入\n"
    )
    wizard._next_btn.click()
    wizard._next_btn.click()
    wizard._next_btn.click()
    assert wizard._current_step() == 4
    error = RuntimeError("secret sqlite detail") if unexpected else BulkParseError(
        "bulk.import.failed"
    )
    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_import_wizard.import_validated",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    criticals: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.dialogs.bulk_import_wizard.QMessageBox.critical",
        lambda _parent, _title, body: criticals.append(body),
    )

    wizard._next_btn.click()

    assert wizard._current_step() == 4
    assert wizard._next_btn.isEnabled()
    assert len(criticals) == 1
    assert "secret sqlite detail" not in criticals[0]
    assert container.conn.execute(
        "SELECT COUNT(*) FROM clients WHERE client_code = 'BULK-FAIL'"
    ).fetchone()[0] == 0
