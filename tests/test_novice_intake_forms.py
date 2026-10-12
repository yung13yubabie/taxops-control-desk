"""Real Qt reproduction of novice intake modal overflow and load failures."""
import os
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea, QMessageBox
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from taxops.ui.style import apply
from taxops.ui.dialogs.new_task_dialog import NewTaskDialog
from taxops.ui.dialogs.task_bulk_dialogs import BulkCreateTasksDialog, BulkEditTasksDialog
from taxops.ui.dialogs.document_item_template_dialog import DocumentItemTemplateDialog
from taxops.ui.pages.attachments_page import _AttachmentInfoDialog


@pytest.fixture(autouse=True)
def discard_test_cleanup(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    apply(app)
    return app


def clients(count=1):
    rows = [SimpleNamespace(id=i + 1, client_name=f"合成客戶{i + 1} " + "長中文名稱" * 25) for i in range(count)]
    return SimpleNamespace(list_clients=lambda limit=500, offset=0: rows[offset:offset + limit])


@pytest.mark.parametrize("kind", ["new", "bulk", "edit", "template", "info"])
@pytest.mark.parametrize("size", [(520, 420), (1093, 614), (1366, 768)])
def test_modal_body_scrolls_and_footer_remains_reachable(app, container, kind, size, tmp_path):
    if kind == "new":
        dialog = NewTaskDialog(container.tasks, clients_service=clients())
    elif kind == "bulk":
        dialog = BulkCreateTasksDialog(clients())
    elif kind == "edit":
        dialog = BulkEditTasksDialog(201)
    elif kind == "template":
        dialog = DocumentItemTemplateDialog(container, "vat")
    else:
        attachment = SimpleNamespace(id=1, original_filename="長中文檔名" * 100 + ".pdf", stored_filename="資料夾/" * 100, extension=".pdf", file_size=123, file_hash_sha256="a" * 64, mime_type="application/pdf", status="uploaded", uploaded_by="測試者", uploaded_at="2026-10-12", accepted_by=None, accepted_at=None, notes="長備註\n" * 50)
        dialog = _AttachmentInfoDialog(attachment)
    dialog.resize(*size)
    dialog.show()
    app.processEvents()
    assert dialog.width() == size[0]
    assert dialog.height() == size[1]
    scroll = dialog.findChild(QScrollArea)
    assert scroll is not None
    assert scroll.geometry().right() < dialog.width()
    assert scroll.geometry().bottom() < dialog.height()
    assert scroll.horizontalScrollBar().maximum() == 0
    for buttons in dialog.findChildren(QDialogButtonBox):
        assert buttons.isVisible()
        assert buttons.mapTo(dialog, buttons.rect().bottomRight()).y() < dialog.height()
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    app.processEvents()
    evidence = Path(os.environ.get("TAXOPS_TEST_SCREENSHOTS", str(tmp_path)))
    evidence.mkdir(parents=True, exist_ok=True)
    assert dialog.grab().save(str(evidence / f"{kind}-{size[0]}.png"))
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def test_task_client_load_failure_blocks_write_and_retry_preserves_input(app, container, monkeypatch):
    source = clients()
    original = source.list_clients
    source.list_clients = lambda **kw: (_ for _ in ()).throw(OSError("synthetic"))
    dialog = NewTaskDialog(container.tasks, clients_service=source)
    dialog.show()
    dialog._title.setText("合成待辦，不應丟失")
    writes = []
    monkeypatch.setattr(container.tasks, "create_task", lambda payload: writes.append(payload))
    assert not dialog._save_btn.isEnabled()
    assert dialog._load_error.isVisible()
    dialog.on_save()
    assert not writes
    source.list_clients = original
    QTest.mouseClick(dialog._retry_btn, Qt.MouseButton.LeftButton)
    assert dialog._save_btn.isEnabled()
    assert dialog._title.text() == "合成待辦，不應丟失"
    dialog.reject()
    assert not writes
    dialog.deleteLater()


def test_task_engagement_load_failure_not_empty(app, container):
    source = SimpleNamespace(list_all=lambda **kw: (_ for _ in ()).throw(OSError("synthetic")))
    dialog = NewTaskDialog(container.tasks, engagements_service=source)
    assert dialog._engagements_failed
    assert not dialog._save_btn.isEnabled()
    assert "載入失敗" in dialog._eng_combo.currentText()
    source.list_all = lambda **kw: []
    dialog._retry_context()
    assert dialog._save_btn.isEnabled()
    assert dialog._eng_combo.currentText() == "（不綁案件）"
    dialog.reject()
    dialog.deleteLater()


def test_task_selector_includes_client_and_case_501(app, container):
    rows = [SimpleNamespace(id=i + 1, engagement_name=f"合成案件{i + 1}") for i in range(501)]
    source = SimpleNamespace(list_all=lambda limit=500, offset=0: rows[offset:offset + limit])
    dialog = NewTaskDialog(container.tasks, clients_service=clients(501), engagements_service=source)
    assert dialog._client_combo.findData(501) > 0
    assert dialog._eng_combo.findData(501) > 0
    assert dialog._title.text() == dialog._assignee.text() == dialog._notes.toPlainText() == ""
    for field in (dialog._title, dialog._assignee, dialog._next_step, dialog._notes):
        assert field.placeholderText()
        assert field.accessibleName()
    dialog.reject()
    dialog.deleteLater()


def test_task_selected_client_case_201_remains_available(app, container):
    rows = [SimpleNamespace(id=i + 1, engagement_name=f"合成案件{i + 1}") for i in range(201)]
    source = SimpleNamespace(list_all=lambda **kw: [], list_by_client=lambda client_id, limit=200, offset=0: rows[offset:offset + limit])
    dialog = NewTaskDialog(container.tasks, clients_service=clients(), engagements_service=source)
    dialog._client_combo.setCurrentIndex(1)
    assert dialog._eng_combo.findData(201) > 0
    dialog.reject()
    dialog.deleteLater()


def test_repeated_context_page_reports_error_instead_of_looping(app, container):
    rows = [SimpleNamespace(id=i + 1, client_name=f"合成客戶{i}") for i in range(500)]
    dialog = NewTaskDialog(container.tasks, clients_service=SimpleNamespace(list_clients=lambda **kw: rows))
    assert dialog._clients_failed
    assert not dialog._save_btn.isEnabled()
    dialog.reject()
    dialog.deleteLater()


def test_context_limit_is_explicit_and_does_not_allow_partial_selection(app, container, monkeypatch):
    monkeypatch.setattr("taxops.ui.dialogs.new_task_dialog._MAX_CONTEXT_ROWS", 500)
    dialog = NewTaskDialog(container.tasks, clients_service=clients(501))
    assert dialog._context_limit_hit
    assert not dialog._save_btn.isEnabled()
    assert "載入上限" in dialog._load_error.text()
    assert dialog._client_combo.count() == 1
    dialog.reject()
    dialog.deleteLater()


def test_real_task_form_validation_cancel_and_save(app, container, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog = NewTaskDialog(container.tasks, clients_service=container.clients, engagements_service=container.engagements)
    dialog.show()
    QTest.mouseClick(dialog._save_btn, Qt.MouseButton.LeftButton)
    assert warnings
    assert container.tasks.list_all() == []
    assert dialog._save_btn.isEnabled()
    dialog._title.setText("合成核對工作")
    dialog._assignee.setText("合成承辦")
    dialog._notes.setPlainText("長中文備註\n第二行")
    QTest.mouseClick(dialog._save_btn, Qt.MouseButton.LeftButton)
    rows = container.tasks.list_all()
    assert len(rows) == 1
    assert rows[0].title == "合成核對工作"
    assert rows[0].assignee == "合成承辦"
    assert rows[0].notes == "長中文備註\n第二行"
    cancelled = NewTaskDialog(container.tasks)
    cancelled._title.setText("應取消")
    cancelled.reject()
    assert len(container.tasks.list_all()) == 1
    dialog.deleteLater()
    cancelled.deleteLater()


@pytest.mark.parametrize("kind", ["new", "bulk", "edit"])
@pytest.mark.parametrize("exit_method", ["reject", "close", "escape"])
def test_dirty_dialog_cancel_keeps_input_or_explicitly_discards(app, container, monkeypatch, kind, exit_method):
    dialog = NewTaskDialog(container.tasks) if kind == "new" else BulkCreateTasksDialog(clients()) if kind == "bulk" else BulkEditTasksDialog(2)
    dialog.show()
    field = dialog._title if kind != "edit" else dialog._assignee
    field.setText("尚未儲存的合成內容")
    answers = []
    def stay(*args):
        answers.append(args)
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox, "question", stay)
    if exit_method == "escape":
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        getattr(dialog, exit_method)()
    assert answers and dialog.isVisible()
    assert field.text() == "尚未儲存的合成內容"
    assert container.tasks.list_all() == []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    dialog.reject()
    assert not dialog.isVisible()
    assert container.tasks.list_all() == []
    dialog.deleteLater()


@pytest.mark.parametrize("kind", ["new", "bulk", "edit"])
def test_notes_tab_reaches_footer_instead_of_inserting_tab(app, container, kind):
    dialog = NewTaskDialog(container.tasks) if kind == "new" else BulkCreateTasksDialog(clients()) if kind == "bulk" else BulkEditTasksDialog(2)
    dialog.show()
    dialog._notes.setFocus()
    app.processEvents()
    QTest.keyClick(dialog._notes, Qt.Key.Key_Tab)
    footer = dialog._save_btn if kind == "new" else dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert app.focusWidget() == footer
    assert dialog._notes.toPlainText() == ""
    dialog.reject()
    dialog.deleteLater()


@pytest.mark.parametrize("failure", ["client", "engagement", "missing"])
def test_retry_preserves_exact_selected_context_or_blocks_missing(app, container, failure):
    client_source = clients(2)
    original = client_source.list_clients
    engs = [SimpleNamespace(id=7, engagement_name="合成案件七")]
    engagement_source = SimpleNamespace(list_all=lambda **kw: engs, list_by_client=lambda *args, **kw: engs)
    dialog = NewTaskDialog(container.tasks, clients_service=client_source, engagements_service=engagement_source, preset_client_id=2)
    dialog._eng_combo.setCurrentIndex(dialog._eng_combo.findData(7))
    dialog._title.setText("保留輸入")
    if failure == "client":
        client_source.list_clients = lambda **kw: (_ for _ in ()).throw(OSError("synthetic"))
    elif failure == "engagement":
        engagement_source.list_by_client = lambda *args, **kw: (_ for _ in ()).throw(OSError("synthetic"))
    else:
        client_source.list_clients = lambda **kw: []
    dialog._retry_context()
    assert not dialog._save_btn.isEnabled()
    if failure == "missing":
        assert "已失效" in dialog._load_error.text()
    client_source.list_clients = original
    engagement_source.list_by_client = lambda *args, **kw: engs
    dialog._retry_context()
    assert dialog._save_btn.isEnabled()
    assert dialog._client_combo.currentData() == 2
    assert dialog._eng_combo.currentData() == 7
    assert dialog._title.text() == "保留輸入"
    dialog.reject()
    dialog.deleteLater()


def test_stale_preset_client_does_not_become_unlinked_task(app, container):
    dialog = NewTaskDialog(container.tasks, clients_service=clients(), preset_client_id=999)
    assert not dialog._save_btn.isEnabled()
    assert "已失效" in dialog._load_error.text()
    dialog.reject()
    dialog.deleteLater()
