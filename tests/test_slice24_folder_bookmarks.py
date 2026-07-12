"""Slice 24 / v0.15.1: folder_bookmarks repository + service + page."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_create_and_list_bookmark(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    bm = container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="工作底稿", path=r"C:\Users\test\Docs", category="工作")
    )
    assert bm.id > 0
    assert bm.name == "工作底稿"
    assert bm.path == r"C:\Users\test\Docs"
    assert bm.category == "工作"

    bookmarks = container.folder_bookmarks.list_bookmarks()
    assert len(bookmarks) == 1
    assert bookmarks[0].id == bm.id


def test_unc_path_accepted(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    bm = container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="共用資料", path=r"\\server\share\folder", category="共享")
    )
    assert bm.path.startswith(r"\\")


def test_name_required(container):
    from taxops.services.folder_bookmarks import (
        CreateBookmarkInput,
        FolderBookmarkValidationError,
    )
    with pytest.raises(FolderBookmarkValidationError) as exc_info:
        container.folder_bookmarks.create_bookmark(
            CreateBookmarkInput(name="", path=r"C:\test")
        )
    assert exc_info.value.code == "folder_bookmark.name.required"


def test_path_required(container):
    from taxops.services.folder_bookmarks import (
        CreateBookmarkInput,
        FolderBookmarkValidationError,
    )
    with pytest.raises(FolderBookmarkValidationError) as exc_info:
        container.folder_bookmarks.create_bookmark(
            CreateBookmarkInput(name="N", path="")
        )
    assert exc_info.value.code == "folder_bookmark.path.required"


def test_path_rejects_newline(container):
    from taxops.services.folder_bookmarks import (
        CreateBookmarkInput,
        FolderBookmarkValidationError,
    )
    with pytest.raises(FolderBookmarkValidationError) as exc_info:
        container.folder_bookmarks.create_bookmark(
            CreateBookmarkInput(name="bad", path="C:\\test\nrm -rf /")
        )
    assert exc_info.value.code == "folder_bookmark.path.invalid"


def test_update_bookmark(container):
    from taxops.services.folder_bookmarks import (
        CreateBookmarkInput,
        UpdateBookmarkInput,
    )
    bm = container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="原名", path=r"C:\old")
    )
    updated = container.folder_bookmarks.update_bookmark(
        UpdateBookmarkInput(
            bookmark_id=bm.id, name="新名", path=r"C:\new", category="新分類", sort_order=5
        )
    )
    assert updated.name == "新名"
    assert updated.path == r"C:\new"
    assert updated.category == "新分類"
    assert updated.sort_order == 5


def test_update_nonexistent(container):
    from taxops.services.folder_bookmarks import (
        FolderBookmarkValidationError,
        UpdateBookmarkInput,
    )
    with pytest.raises(FolderBookmarkValidationError) as exc_info:
        container.folder_bookmarks.update_bookmark(
            UpdateBookmarkInput(bookmark_id=99999, name="x", path="C:\\x")
        )
    assert exc_info.value.code == "folder_bookmark.not_found"


def test_soft_delete_hides_bookmark(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    bm = container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="刪", path=r"C:\delete")
    )
    container.folder_bookmarks.delete_bookmark(bm.id)
    assert container.folder_bookmarks.get_bookmark(bm.id) is None
    assert container.folder_bookmarks.list_bookmarks() == []


def test_list_categories(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    container.folder_bookmarks.create_bookmark(CreateBookmarkInput(name="a", path=r"C:\a", category="工作"))
    container.folder_bookmarks.create_bookmark(CreateBookmarkInput(name="b", path=r"C:\b", category="私人"))
    container.folder_bookmarks.create_bookmark(CreateBookmarkInput(name="c", path=r"C:\c", category="工作"))
    container.folder_bookmarks.create_bookmark(CreateBookmarkInput(name="d", path=r"C:\d"))
    cats = container.folder_bookmarks.list_categories()
    assert cats == ["工作", "私人"]


def test_audit_log_on_create(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="A", path=r"C:\a")
    )
    rows = container.conn.execute(
        "SELECT action FROM audit_logs WHERE action='folder_bookmark.create'"
    ).fetchall()
    assert len(rows) == 1


@pytest.mark.usefixtures("qapp")
def test_page_instantiates_and_lists_empty(container):
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage
    page = FolderBookmarksPage(container)
    assert page._table.rowCount() == 0


@pytest.mark.usefixtures("qapp")
def test_page_lists_existing_bookmarks(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage
    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="L1", path=r"C:\one")
    )
    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="L2", path=r"\\srv\share")
    )
    page = FolderBookmarksPage(container)
    assert page._table.rowCount() == 2


@pytest.mark.usefixtures("qapp")
def test_page_filters_and_shows_parent_path(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="A客戶", path=r"C:\Tax\A\2026", category="工作")
    )
    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="B客戶", path=r"C:\Tax\B\2026", category="共享")
    )
    page = FolderBookmarksPage(container)

    parent_col = 2
    assert page._table.item(0, parent_col).text() == r"C:\Tax\A"

    idx = page._category_filter.findData("共享")
    page._category_filter.setCurrentIndex(idx)
    assert page._table.rowCount() == 1
    assert page._table.item(0, 1).text() == "B客戶"

    page._clear_filters()
    page._search_edit.setText("A\\2026")
    assert page._table.rowCount() == 1
    assert page._table.item(0, 1).text() == "A客戶"


@pytest.mark.usefixtures("qapp")
def test_page_clear_filter_resets_sidebar_context(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Alpha", path=r"C:\Tax\Alpha", category="工作")
    )
    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Beta", path=r"C:\Tax\Beta", category="共享")
    )
    page = FolderBookmarksPage(container)
    page._search_edit.setText("Alpha")
    assert page._table.rowCount() == 1

    page.clear_filter()

    assert page._search_edit.text() == ""
    assert page._category_filter.currentData() == "__all__"
    assert page._table.rowCount() == 2


@pytest.mark.usefixtures("qapp")
def test_page_refresh_preserves_selected_bookmark_by_id(container):
    from taxops.services.folder_bookmarks import CreateBookmarkInput, UpdateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    first = container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Alpha", path=r"C:\Tax\A")
    )
    second = container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Zulu", path=r"C:\Tax\Z")
    )
    page = FolderBookmarksPage(container)
    for row in range(page._table.rowCount()):
        if page._table.item(row, 0).text() == str(second.id):
            page._table.selectRow(row)
            break

    container.folder_bookmarks.update_bookmark(
        UpdateBookmarkInput(
            bookmark_id=second.id,
            name="Aardvark",
            path=r"C:\Tax\0",
        )
    )
    page._refresh()

    assert page._selected_id() == second.id
    assert page._selected_id() != first.id


@pytest.mark.usefixtures("qapp")
def test_page_toolbar_buttons_initially(container):
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage
    page = FolderBookmarksPage(container)
    assert page._new_btn.isEnabled()
    assert not page._edit_btn.isEnabled()
    assert not page._delete_btn.isEnabled()
    assert not page._open_btn.isEnabled()


@pytest.mark.usefixtures("qapp")
def test_main_window_routes_to_folder_bookmarks(container):
    from taxops.ui.action_registry import PAGE_FOLDER_BOOKMARKS
    from taxops.ui.main_window import MainWindow
    win = MainWindow(container)
    assert PAGE_FOLDER_BOOKMARKS in win._page_indices


@pytest.mark.usefixtures("qapp")
def test_new_button_click_creates_bookmark_and_refreshes_table(
    container, monkeypatch
):
    from taxops.ui.pages.folder_bookmarks_page import (
        FolderBookmarksPage,
        _BookmarkDialog as RealBookmarkDialog,
    )

    class AcceptedDialog(RealBookmarkDialog):
        def exec(self):
            self._name_edit.setText("Click-created")
            self._path_edit.setText(r"C:\Tax\Click")
            self._category_edit.setText("UI")
            self.accept()
            return self.result()

    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page._BookmarkDialog", AcceptedDialog
    )
    page = FolderBookmarksPage(container)

    page._new_btn.click()

    assert page._table.rowCount() == 1
    assert page._table.item(0, 1).text() == "Click-created"
    assert container.folder_bookmarks.list_bookmarks()[0].path == r"C:\Tax\Click"


@pytest.mark.usefixtures("qapp")
def test_edit_button_click_updates_selected_bookmark(container, monkeypatch):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import (
        FolderBookmarksPage,
        _BookmarkDialog as RealBookmarkDialog,
    )

    bookmark = container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Before", path=r"C:\Tax\Before")
    )

    class AcceptedDialog(RealBookmarkDialog):
        def exec(self):
            assert self._name_edit.text() == "Before"
            self._name_edit.setText("After")
            self._path_edit.setText(r"C:\Tax\After")
            self._category_edit.setText("Edited")
            self._sort_order = 7
            self.accept()
            return self.result()

    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page._BookmarkDialog", AcceptedDialog
    )
    page = FolderBookmarksPage(container)
    page._table.selectRow(0)
    assert page._edit_btn.isEnabled()

    page._edit_btn.click()

    updated = container.folder_bookmarks.get_bookmark(bookmark.id)
    assert updated is not None
    assert (updated.name, updated.path, updated.category, updated.sort_order) == (
        "After",
        r"C:\Tax\After",
        "Edited",
        7,
    )
    assert page._table.item(0, 1).text() == "After"


@pytest.mark.usefixtures("qapp")
def test_delete_button_click_requires_confirmation_and_removes_row(
    container, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Delete me", path=r"C:\Tax\Delete")
    )
    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    page = FolderBookmarksPage(container)
    page._table.selectRow(0)

    page._delete_btn.click()

    assert page._table.rowCount() == 0
    assert container.folder_bookmarks.list_bookmarks() == []


@pytest.mark.usefixtures("qapp")
def test_open_button_click_reports_missing_directory(container, monkeypatch):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Missing", path=r"Z:\definitely-missing\taxops")
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QMessageBox.warning",
        lambda _parent, title, body: warnings.append((title, body)),
    )
    page = FolderBookmarksPage(container)
    page._table.selectRow(0)

    page._open_btn.click()

    assert len(warnings) == 1
    assert warnings[0][1].strip()


@pytest.mark.usefixtures("qapp")
def test_bookmark_dialog_browse_and_values(monkeypatch):
    from taxops.ui.pages.folder_bookmarks_page import _BookmarkDialog

    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QFileDialog.getExistingDirectory",
        lambda *_args: r"C:\Tax\Chosen",
    )
    dialog = _BookmarkDialog(
        title="Bookmark", name="Name", path=r"C:\Tax\Start", category="Cat",
        sort_order=3,
    )

    dialog._on_browse()

    assert dialog.values() == ("Name", r"C:\Tax\Chosen", "Cat", 3)


@pytest.mark.usefixtures("qapp")
def test_refresh_failure_preserves_page_and_shows_warning(container, monkeypatch):
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    page = FolderBookmarksPage(container)
    warnings: list[str] = []
    monkeypatch.setattr(
        container.folder_bookmarks,
        "list_bookmarks",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._refresh_btn.click()

    assert len(warnings) == 1
    assert warnings[0].strip()


@pytest.mark.usefixtures("qapp")
def test_new_button_validation_failure_keeps_dialog_open(container, monkeypatch):
    from taxops.ui.pages.folder_bookmarks_page import (
        FolderBookmarksPage,
        _BookmarkDialog as RealBookmarkDialog,
    )

    class RetryDialog(RealBookmarkDialog):
        calls = 0

        def exec(self):
            type(self).calls += 1
            if type(self).calls == 1:
                self._name_edit.clear()
                self._path_edit.setText(r"C:\Tax\Invalid")
                self.accept()
            else:
                self.reject()
            return self.result()

    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page._BookmarkDialog", RetryDialog
    )
    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    page = FolderBookmarksPage(container)

    page._new_btn.click()

    assert RetryDialog.calls == 2
    assert len(warnings) == 1
    assert container.folder_bookmarks.list_bookmarks() == []


@pytest.mark.usefixtures("qapp")
def test_edit_stale_selection_warns_and_refreshes(container, monkeypatch):
    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    bookmark = container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Stale", path=r"C:\Tax\Stale")
    )
    page = FolderBookmarksPage(container)
    page._table.selectRow(0)
    container.folder_bookmarks.delete_bookmark(bookmark.id)
    warnings: list[str] = []
    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._edit_btn.click()

    assert len(warnings) == 1
    assert page._table.rowCount() == 0


@pytest.mark.usefixtures("qapp")
def test_delete_button_no_confirmation_keeps_bookmark(container, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Keep", path=r"C:\Tax\Keep")
    )
    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    page = FolderBookmarksPage(container)
    page._table.selectRow(0)

    page._delete_btn.click()

    assert len(container.folder_bookmarks.list_bookmarks()) == 1


@pytest.mark.usefixtures("qapp")
def test_open_button_success_and_desktop_rejection(
    container, monkeypatch, tmp_path
):
    from pathlib import Path

    from taxops.services.folder_bookmarks import CreateBookmarkInput
    from taxops.ui.pages.folder_bookmarks_page import FolderBookmarksPage

    container.folder_bookmarks.create_bookmark(
        CreateBookmarkInput(name="Existing", path=str(tmp_path))
    )
    warnings: list[str] = []
    opened_urls: list[str] = []

    def reject_open(url):
        opened_urls.append(url.toLocalFile())
        return False

    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QDesktopServices.openUrl",
        reject_open,
    )
    monkeypatch.setattr(
        "taxops.ui.pages.folder_bookmarks_page.QMessageBox.warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    page = FolderBookmarksPage(container)
    page._table.selectRow(0)

    page._open_btn.click()

    assert len(opened_urls) == 1
    assert Path(opened_urls[0]) == tmp_path
    assert len(warnings) == 1


def test_review_notes_table_dropped(db_conn):
    rows = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='review_notes'"
    ).fetchall()
    assert rows == []


def test_folder_bookmarks_table_exists(db_conn):
    rows = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='folder_bookmarks'"
    ).fetchall()
    assert len(rows) == 1


def test_review_notes_label_retained_for_whitelist():
    from taxops.i18n import NAV_LABELS
    assert "review_notes" in NAV_LABELS


def test_folder_bookmarks_label_added():
    from taxops.i18n import NAV_LABELS
    assert NAV_LABELS["folder_bookmarks"] == "資料夾管理"
