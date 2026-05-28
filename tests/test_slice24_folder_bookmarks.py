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
