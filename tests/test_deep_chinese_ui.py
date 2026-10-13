"""Synthetic data only: UI language must not depend on the operating system."""
import ast
from pathlib import Path, PurePath, PureWindowsPath
import re

import pytest

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QDialogButtonBox, QFileDialog, QLineEdit, QMessageBox, QPushButton

from taxops.i18n.errors import ERROR_MESSAGES, GENERIC_FALLBACK, error_message
from taxops.i18n.qt import _StandardButtons, install_chinese


def _assert_selected_file(selected: list[str], expected: PurePath) -> None:
    """Qt uses forward slashes on Windows; compare paths, not serialized spelling."""
    assert len(selected) == 1
    actual = type(expected)(selected[0])
    assert actual.is_absolute() and expected.is_absolute()
    assert actual == expected
    # Windows path equality ignores case; the UI must still preserve the filename.
    assert actual.name == expected.name


@pytest.mark.parametrize(("selected", "expected"), [
    (["C:/Users/Test/中文 空格/Original English 公司.pdf"],
     PureWindowsPath(r"C:\Users\Test\中文 空格\Original English 公司.pdf")),
    (["//server/share/中文 空格/Original English 公司.pdf"],
     PureWindowsPath(r"\\server\share\中文 空格\Original English 公司.pdf")),
])
def test_windows_selected_path_separator_equivalence(selected, expected):
    _assert_selected_file(selected, expected)


@pytest.mark.parametrize("selected", [
    ["D:/Users/Test/中文 空格/Original English 公司.pdf"],
    ["C:/Users/Other/中文 空格/Original English 公司.pdf"],
    ["C:/Users/Test/中文 空格/Different 公司.pdf"],
    ["C:/Users/Test/中文 空格/original English 公司.pdf"],
    ["Users/Test/中文 空格/Original English 公司.pdf"],
    [],
    ["C:/Users/Test/中文 空格/Original English 公司.pdf", "C:/extra.pdf"],
])
def test_windows_selected_path_rejects_changed_target_or_filename(selected):
    expected = PureWindowsPath(r"C:\Users\Test\中文 空格\Original English 公司.pdf")
    with pytest.raises(AssertionError):
        _assert_selected_file(selected, expected)


def test_windows_selected_path_rejects_changed_network_share():
    expected = PureWindowsPath(r"\\server\share\中文 空格\Original English 公司.pdf")
    with pytest.raises(AssertionError):
        _assert_selected_file(["//server/other-share/中文 空格/Original English 公司.pdf"], expected)


@pytest.fixture(autouse=True)
def restore_application_presentation(qapp):
    locale = QLocale()
    stylesheet = qapp.styleSheet()
    font = qapp.font()
    previous = getattr(qapp, "_taxops_translators", None)
    yield
    qapp.setStyleSheet(stylesheet)
    qapp.setFont(font)
    QLocale.setDefault(locale)
    if previous is None:
        for translator in getattr(qapp, "_taxops_translators", ()):
            qapp.removeTranslator(translator)
        if hasattr(qapp, "_taxops_translators"):
            del qapp._taxops_translators


def test_standard_buttons_english_locale(qapp):
    original = QLocale()
    QLocale.setDefault(QLocale("en_US"))
    try:
        install_chinese(qapp)
        first = qapp._taxops_translators
        install_chinese(qapp)
        assert first is qapp._taxops_translators
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        assert {b.text().replace('&', '') for b in buttons.buttons()} == {'確定', '取消', '儲存'}
        box = QMessageBox(QMessageBox.Icon.Question, '確認', '是否繼續？', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        assert {b.text().replace('&', '') for b in box.buttons()} == {'是', '否'}
    finally:
        QLocale.setDefault(original)


def test_missing_qm_standard_button_fallback(qapp):
    fallback = _StandardButtons(qapp)
    qapp.installTranslator(fallback)
    try:
        for key, expected in fallback._labels.items():
            assert fallback.translate('QPlatformTheme', '&' + key) == expected
        assert fallback.translate('UserData', 'Save') is None
    finally:
        qapp.removeTranslator(fallback)


def test_qt_file_dialog_catalogue_and_paths(qapp, tmp_path):
    install_chinese(qapp)
    assert not qapp._taxops_translators[0].isEmpty(), 'Bundled Qt catalogue must be shipped'
    folder = tmp_path / '中文 空格'
    folder.mkdir()
    file = folder / 'Original English 公司.pdf'
    file.write_bytes(b'synthetic')
    for mode in (QFileDialog.FileMode.ExistingFile, QFileDialog.FileMode.Directory, QFileDialog.FileMode.AnyFile):
        dialog = QFileDialog(None, '選擇檔案', str(folder))
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        dialog.setFileMode(mode)
        if mode == QFileDialog.FileMode.AnyFile:
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.selectFile(str(file))
        _assert_selected_file(dialog.selectedFiles(), file)
        text = ' '.join(b.text() for b in dialog.findChildren(QPushButton))
        assert 'Cancel' not in text and 'Open' not in text and 'Save' not in text
        assert '取消' in text
        from PySide6.QtWidgets import QLabel
        labels = [w.text() for w in dialog.findChildren(QLabel)]
        assert any('檔案' in t or '目錄' in t for t in labels), labels
        dialog.reject()
        dialog.deleteLater()


def test_service_error_codes_have_specific_chinese_guidance():
    codes = set()
    for source in Path('src/taxops/services').rglob('*.py'):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                for arg in node.exc.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.fullmatch(r'[a-z_]+(?:\.[a-z_]+)+', arg.value):
                        codes.add(arg.value)
    assert codes <= ERROR_MESSAGES.keys(), sorted(codes - ERROR_MESSAGES.keys())
    for code in codes:
        assert re.search(r'[\u4e00-\u9fff]', error_message(code))
        assert error_message(code) != GENERIC_FALLBACK
    assert error_message('SQLite error private payload') == GENERIC_FALLBACK


def test_technical_copy_removed_without_rewriting_user_data(qapp, container):
    from taxops.ui.pages.registry_page import RegistryPage
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage
    install_chinese(qapp)
    for cls in (RegistryPage, FolderBookmarksPage):
        page = cls(container)
        from PySide6.QtWidgets import QWidget
        text = '\n'.join(str(getattr(w, name)()) for w in page.findChildren(QWidget) for name in ('text', 'toolTip', 'placeholderText') if callable(getattr(w, name, None)))
        assert not re.search(r'GCIS|API|UNC|Swagger|file:// URL', text)
        page.deleteLater()
    field = QLineEdit('ACME English 公司')
    assert field.text() == 'ACME English 公司'


def test_file_dialog_accept_and_overwrite_cancel(qapp, tmp_path):
    from PySide6.QtCore import QTimer
    install_chinese(qapp)
    file = tmp_path / '中文 空格 original.txt'
    file.write_text('synthetic unchanged', encoding="utf-8")
    dialog = QFileDialog(None, '選擇檔案', str(tmp_path))
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
    dialog.selectFile(str(file))
    dialog.accept()
    assert dialog.result() == QFileDialog.DialogCode.Accepted
    _assert_selected_file(dialog.selectedFiles(), file)
    dialog = QFileDialog(None, '儲存檔案', str(tmp_path))
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.selectFile(str(file))
    seen = []
    def decline_overwrite():
        box = qapp.activeModalWidget()
        if isinstance(box, QMessageBox):
            seen.append(box.text())
            assert {b.text().replace('&', '') for b in box.buttons()} == {'是', '否'}
            box.done(int(QMessageBox.StandardButton.No))
    QTimer.singleShot(20, decline_overwrite)
    dialog.accept()
    assert seen and not any(word in seen[0] for word in ('already exists', 'replace it'))
    assert file.read_text(encoding="utf-8") == 'synthetic unchanged'
    dialog.reject()


def test_missing_catalogue_really_uses_chinese_buttons(qapp, tmp_path):
    from PySide6.QtCore import QLibraryInfo
    from taxops.i18n.qt import _install_from_path
    assert _install_from_path(qapp, str(tmp_path)) is False
    box = QMessageBox(QMessageBox.Icon.Warning, '測試', '合成錯誤', QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
    assert {b.text().replace('&', '') for b in box.buttons()} == {'確定', '取消'}
    assert _install_from_path(qapp, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) is True


def test_calendar_and_edit_menu_are_chinese(qapp):
    from PySide6.QtWidgets import QCalendarWidget
    QLocale.setDefault(QLocale('en_US'))
    install_chinese(qapp)
    calendar = QCalendarWidget()
    assert calendar.locale().name() == 'zh_TW'
    assert calendar.locale().dayName(1) == '星期一'
    field = QLineEdit('Customer ACME')
    menu = field.createStandardContextMenu()
    assert not re.search('Undo|Redo|Cut|Copy|Paste|Delete|Select All', '\n'.join(a.text() for a in menu.actions()))
    assert all(a.text() for a in menu.actions() if not a.isSeparator())
    assert any('複製' in a.text() for a in menu.actions())
    assert field.text() == 'Customer ACME'


def test_raw_service_value_error_not_displayed(qapp, container, monkeypatch):
    from taxops.ui.main_window import MainWindow
    from taxops.ui.navigation import NavigationTarget
    from taxops.ui.action_registry import PAGE_ENGAGEMENTS
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput
    client = container.clients.create_client(CreateClientInput(client_code='SYNTH', client_name='ACME 合成客戶'))
    case = container.engagements.create_engagement(CreateEngagementInput(client_id=client.id, engagement_name='合成案件', tax_type='vat', period_name='2026-10'))
    window = MainWindow(container)
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda _p, _t, text, *args: messages.append(text))
    monkeypatch.setattr(container.engagements, 'get_engagement', lambda *_args: (_ for _ in ()).throw(ValueError('SQLite payload /private/path SYNTHETIC')))
    assert window.open_target(NavigationTarget(PAGE_ENGAGEMENTS, engagement_id=case.id)) is False
    assert messages and '重新整理' in messages[0]
    assert not any(word in messages[0] for word in ('SQLite', 'payload', '/private', 'SYNTHETIC'))
    window.close()


def test_dynamic_lease_and_task_validation_is_actionable():
    import pytest
    from taxops.services.client_leases import LeaseInput, ClientLeaseValidationError, validate_lease_input
    from taxops.services.tasks import TaskValidationError, _task_text
    fields = [('lease_name', 200), ('premises_address', 500), ('landlord_name', 200), ('notes', 2000), ('start_date', 10), ('status', 20)]
    for field, limit in fields:
        values = {'lease_name': '合成租約', field: '測' * (limit + 1)}
        with pytest.raises(ClientLeaseValidationError) as caught:
            validate_lease_input(LeaseInput(**values))
        message = error_message(caught.value.code)
        assert message != GENERIC_FALLBACK
        assert '資料是否已更新' not in message
    for field, limit in [('title', 200), ('assignee', 100), ('next_step', 500), ('notes', 2000)]:
        with pytest.raises(TaskValidationError) as caught:
            _task_text('測' * (limit + 1), field=field, maximum=limit)
        assert f'{limit:,}' in error_message(caught.value.code)


def test_compact_calendar_weekday_labels_fit(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableView
    from taxops.ui.style import apply
    from taxops.ui.widgets.date_field import _CalendarPopup
    apply(qapp)
    popup = _CalendarPopup(current_iso="2026-10-12")
    popup.show()
    qapp.processEvents()
    view = popup._cal.findChild(QTableView)
    model = view.model()
    labels = [str(model.data(model.index(0, column), Qt.ItemDataRole.DisplayRole) or "") for column in range(model.columnCount())]
    days = [text for text in labels if text in "日一二三四五六" and text]
    assert len(days) == 7, labels
    assert popup.width() == 320
    for column, label in enumerate(labels):
        if label in days:
            assert view.fontMetrics().horizontalAdvance(label) < view.columnWidth(column)
    popup.close()


def test_visible_file_model_metadata_chinese_and_paths_unchanged(qapp, tmp_path, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTreeView
    install_chinese(qapp)
    folder = tmp_path / "English Folder 中文"
    folder.mkdir()
    file = tmp_path / "Original 檔名.pdf"
    file.write_bytes(b"synthetic")
    dialog = QFileDialog(None, "選擇檔案", str(tmp_path))
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
    dialog.setViewMode(QFileDialog.ViewMode.Detail)
    dialog.selectFile(str(file))
    dialog.show()
    view = dialog.findChild(QTreeView)
    model = view.model()
    root = view.rootIndex()
    qtbot.waitUntil(lambda: {folder.name, file.name} <= {str(model.data(model.index(row, 0, root))) for row in range(model.rowCount(root))})
    rows = {str(model.data(model.index(row, 0, root))): [model.data(model.index(row, column, root), Qt.ItemDataRole.DisplayRole) for column in range(4)] for row in range(model.rowCount(root))}
    qapp.processEvents()
    for column in (1, 2, 3):
        for row in range(model.rowCount(root)):
            label = str(model.data(model.index(row, column, root)) or "")
            assert view.fontMetrics().horizontalAdvance(label) < view.columnWidth(column)
    assert rows[folder.name][2] == "資料夾"
    assert rows[file.name][1] == "9 位元組"
    assert rows[file.name][2] == "可攜式文件（PDF）"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", rows[file.name][3])
    _assert_selected_file(dialog.selectedFiles(), file)
    dialog.accept()
    assert dialog.result() == QFileDialog.DialogCode.Accepted
    _assert_selected_file(dialog.selectedFiles(), file)
    assert file.read_bytes() == b"synthetic"
