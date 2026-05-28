"""Folder bookmarks service (Slice 24 / v0.15.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..repositories.folder_bookmarks import (
    FolderBookmarkRow,
    FolderBookmarksRepository,
)
from .audit import AuditService


_MAX_NAME_LEN = 100
_MAX_PATH_LEN = 1024
_MAX_CATEGORY_LEN = 50


class FolderBookmarkValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateBookmarkInput:
    name: str
    path: str
    category: str | None = None
    sort_order: int = 0


@dataclass(frozen=True)
class UpdateBookmarkInput:
    bookmark_id: int
    name: str
    path: str
    category: str | None = None
    sort_order: int = 0


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _validate_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise FolderBookmarkValidationError("folder_bookmark.name.required")
    if len(cleaned) > _MAX_NAME_LEN:
        raise FolderBookmarkValidationError("folder_bookmark.name.too_long")
    return cleaned


def _validate_path(path: str) -> str:
    cleaned = (path or "").strip()
    if not cleaned:
        raise FolderBookmarkValidationError("folder_bookmark.path.required")
    if len(cleaned) > _MAX_PATH_LEN:
        raise FolderBookmarkValidationError("folder_bookmark.path.too_long")
    if "\x00" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise FolderBookmarkValidationError("folder_bookmark.path.invalid")
    return cleaned


def _validate_category(category: str | None) -> str | None:
    if category is None:
        return None
    cleaned = category.strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_CATEGORY_LEN:
        raise FolderBookmarkValidationError("folder_bookmark.category.too_long")
    return cleaned


class FolderBookmarksService:
    def __init__(
        self,
        repo: FolderBookmarksRepository,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._audit = audit

    def list_bookmarks(self) -> list[FolderBookmarkRow]:
        return self._repo.list_all()

    def list_by_category(self, category: str | None) -> list[FolderBookmarkRow]:
        return self._repo.list_by_category(category)

    def get_bookmark(self, bookmark_id: int) -> FolderBookmarkRow | None:
        return self._repo.get(bookmark_id)

    def list_categories(self) -> list[str]:
        return self._repo.list_categories()

    def create_bookmark(self, payload: CreateBookmarkInput) -> FolderBookmarkRow:
        name = _validate_name(payload.name)
        path = _validate_path(payload.path)
        category = _validate_category(payload.category)
        sort_order = max(0, int(payload.sort_order or 0))
        timestamp = _now_iso()
        new_id = self._repo.insert(
            name=name,
            path=path,
            category=category,
            sort_order=sort_order,
            timestamp=timestamp,
        )
        self._audit.record(
            action="folder_bookmark.create",
            target_type="folder_bookmark",
            target_id=str(new_id),
            detail={"name": name, "path": path, "category": category},
        )
        row = self._repo.get(new_id)
        assert row is not None
        return row

    def update_bookmark(self, payload: UpdateBookmarkInput) -> FolderBookmarkRow:
        existing = self._repo.get(payload.bookmark_id)
        if existing is None:
            raise FolderBookmarkValidationError("folder_bookmark.not_found")
        name = _validate_name(payload.name)
        path = _validate_path(payload.path)
        category = _validate_category(payload.category)
        sort_order = max(0, int(payload.sort_order or 0))
        timestamp = _now_iso()
        updated = self._repo.update(
            bookmark_id=payload.bookmark_id,
            name=name,
            path=path,
            category=category,
            sort_order=sort_order,
            timestamp=timestamp,
        )
        if updated == 0:
            raise FolderBookmarkValidationError("folder_bookmark.not_found")
        self._audit.record(
            action="folder_bookmark.update",
            target_type="folder_bookmark",
            target_id=str(payload.bookmark_id),
            detail={"name": name, "path": path, "category": category},
        )
        row = self._repo.get(payload.bookmark_id)
        assert row is not None
        return row

    def delete_bookmark(self, bookmark_id: int) -> None:
        existing = self._repo.get(bookmark_id)
        if existing is None:
            raise FolderBookmarkValidationError("folder_bookmark.not_found")
        timestamp = _now_iso()
        deleted = self._repo.soft_delete(bookmark_id, timestamp)
        if deleted == 0:
            raise FolderBookmarkValidationError("folder_bookmark.not_found")
        self._audit.record(
            action="folder_bookmark.delete",
            target_type="folder_bookmark",
            target_id=str(bookmark_id),
            detail={"name": existing.name, "path": existing.path},
        )
