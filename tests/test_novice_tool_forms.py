"""Real Qt short-window and novice input regression; isolated synthetic data only."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from taxops.ui.dialogs.template_form_dialog import TemplateFormDialog
from taxops.ui.dialogs.recurring_billing_dialogs import _BulkPasteDialog, PlanDialog
from taxops.ui.dialogs.work_records_dialogs import WorkflowTemplateDialog
from taxops.ui.pages.registry_page import RegistryPage
from taxops.ui.style import apply


@pytest.fixture
def styled_app():
    app = QApplication.instance() or QApplication([])
    old_style = app.styleSheet()
    apply(app)
    yield app
    app.setStyleSheet(old_style)


def _inside(owner, widget):
    return owner.rect().contains(widget.mapTo(owner, QPoint(0, 0))) and owner.rect().contains(
        widget.mapTo(owner, widget.rect().bottomRight()))


def test_template_expanded_short_window_keeps_footer_and_scroll(styled_app, container):
    d = TemplateFormDialog(container.templates, container=container)
    try:
        d.resize(640, 480)
        d.show()
        styled_app.processEvents()
        QTest.mouseClick(d._example_toggle, Qt.MouseButton.LeftButton)
        d._scroll.ensureWidgetVisible(d._help_toggle)
        QTest.mouseClick(d._help_toggle, Qt.MouseButton.LeftButton)
        styled_app.processEvents()
        assert d.size().toTuple() == (640, 480)
        assert _inside(d, d._save_btn)
        assert d._scroll.verticalScrollBar().maximum() > 0
        d._scroll.ensureWidgetVisible(d._variable_help)
        styled_app.processEvents()
        assert _inside(d._scroll.viewport(), d._variable_help)
        assert not d._name.text()
        assert "例如" in d._name.placeholderText()
        cancel = d.findChild(QDialogButtonBox).buttons()[-1]
        QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)
        assert not d.isVisible()
    finally:
        d.close()


def test_bulk_paste_short_window_empty_input_and_cancel(styled_app):
    d = _BulkPasteDialog()
    try:
        d.resize(640, 480)
        d.show()
        styled_app.processEvents()
        assert d.size().toTuple() == (640, 480)
        assert _inside(d, d._ok_btn)
        assert d._text.accessibleName()
        assert d.text() == ""
        d._text.setPlainText("合成測試對象\t1200\t\t合成說明")
        assert "合成測試對象" in d.text()
        d.reject()
        assert not d.isVisible()
    finally:
        d.close()


def test_workflow_blank_validation_repeated_then_cancel(styled_app, monkeypatch):
    warnings = []
    monkeypatch.setattr("taxops.ui.dialogs.work_records_dialogs.QMessageBox.warning", lambda *a: warnings.append(a))
    d = WorkflowTemplateDialog(title="合成流程")
    try:
        d.resize(640, 480)
        d.show()
        styled_app.processEvents()
        assert d.size().toTuple() == (640, 480)
        buttons = d.findChild(QDialogButtonBox)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert ok.text() == "儲存流程"
        assert "例如" in d._name.placeholderText()
        QTest.mouseClick(ok, Qt.MouseButton.LeftButton)
        QTest.mouseClick(ok, Qt.MouseButton.LeftButton)
        assert len(warnings) == 2
        assert d.isVisible()
        QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Cancel), Qt.MouseButton.LeftButton)
        assert not d.isVisible()
    finally:
        d.close()


def test_registry_long_synthetic_result_scrolls_to_apply(styled_app, container):
    d = RegistryPage(container)
    try:
        d.resize(640, 480)
        d.show()
        d._set_result({"tax_id": "12345678", "business_name": "合成測試長中文名稱" * 20,
                       "business_address": "臺北市合成測試地址" * 30})
        styled_app.processEvents()
        assert d.size().toTuple() == (640, 480)
        d._scroll.ensureWidgetVisible(d._apply_btn)
        styled_app.processEvents()
        assert _inside(d._scroll.viewport(), d._apply_btn)
        assert d._scroll.horizontalScrollBar().maximum() == 0
        d._query_edit.clear()
        d._search_btn.click()
        assert "請輸入" in d._status_label.text()
        assert not d._apply_btn.isEnabled()
    finally:
        d.close()


def test_plan_examples_do_not_supply_business_values(styled_app, container):
    d = PlanDialog(container.recurring_billing, 1)
    try:
        assert d._name.text() == d._contract_ref.text() == ""
        assert "例如" in d._name.placeholderText()
        assert "例如" in d._contract_ref.placeholderText()
    finally:
        d.close()
