"""Read-only due reminders for tasks and document-request batches.

Complete request pages are read before rendering. Only referenced cases and
clients are looked up; this is not an annual-work/compliance dashboard.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ...core.clock import today_iso
from ...repositories.document_requests import DocumentRequestRow
from ...repositories.engagements import EngagementRow
from .. import tokens
from ..action_registry import PAGE_ENGAGEMENTS, PAGE_TASKS
from ..navigation import NavigationTarget
from ..today_queue import (
    TodayQueueSummary,
    TodayQueueValidationError,
    TodayWorkItem,
    build_today_queue,
    due_engagement_ids,
    summarize_today_queue,
)
from .buttons import make_button

_log = logging.getLogger(__name__)


def _checked_page(batch, *, kind: str, size: int, seen: set[int]) -> list:
    if not isinstance(batch, list) or len(batch) > size:
        raise TodayQueueValidationError("invalid_page", kind=kind)
    for row in batch:
        if type(row.id) is not int or row.id <= 0:
            raise TodayQueueValidationError("invalid_id", kind=kind)
        if row.id in seen:
            raise TodayQueueValidationError("duplicate_id", kind=kind, record_id=row.id)
        seen.add(row.id)
    return batch


def all_engagements(container) -> list[EngagementRow]:
    """Read every active case in stable ID order, including case 501 onward."""
    result: list[EngagementRow] = []
    seen: set[int] = set()
    while True:
        batch = _checked_page(
            container.engagements.list_all(
                order_by="id", order_dir="ASC", limit=500, offset=len(result)
            ),
            kind="engagement", size=500, seen=seen,
        )
        result.extend(batch)
        if len(batch) < 500:
            return result


def all_document_requests(container) -> list[DocumentRequestRow]:
    """Read and count-check complete pages; an incomplete read is never empty."""
    total = container.doc_requests.count_all()
    if type(total) is not int or total < 0:
        raise TodayQueueValidationError("invalid_count", kind="document_request")
    result: list[DocumentRequestRow] = []
    seen: set[int] = set()
    for offset in range(0, total, 200):
        batch = _checked_page(
            container.doc_requests.list_all(limit=200, offset=offset),
            kind="document_request", size=200, seen=seen,
        )
        if len(batch) != min(200, total - offset):
            raise TodayQueueValidationError("incomplete_snapshot", kind="document_request")
        result.extend(batch)
    final_total = container.doc_requests.count_all()
    if type(final_total) is not int or final_total != total:
        raise TodayQueueValidationError("changed_snapshot", kind="document_request")
    return result


@dataclass(frozen=True)
class _QueueState:
    kind: Literal["loading", "success", "empty", "stale", "error"]
    rows: tuple[TodayWorkItem, ...] = ()
    error: str | None = None
    last_success_at: str | None = None

    def __post_init__(self) -> None:
        if self.kind in {"loading", "empty", "error"} and self.rows:
            raise ValueError("non-data queue state cannot contain rows")
        if self.kind == "success" and not self.rows:
            raise ValueError("successful empty queue must use empty state")
        if self.kind in {"error", "stale"} and not self.error:
            raise ValueError("failed queue state must include an error")
        if self.kind == "stale" and not self.last_success_at:
            raise ValueError("stale queue state must identify its snapshot")


class TodayWorkPanel(QWidget):
    navigate_requested = Signal(object)
    summary_changed = Signal(str)

    def __init__(self, container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self.setObjectName("TodayWorkPanel")
        self.setAccessibleName("待辦與索件提醒")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        font = self.font()
        font.setPixelSize(tokens.FONT_BODY)
        self.setFont(font)
        self._state = _QueueState("loading")
        self._items: list[TodayWorkItem] = []
        self._contexts: dict[tuple[str, int], str] = {}
        self._due_summary: TodayQueueSummary | None = None
        self._compact_summary = "提醒未載入"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACING_MD, tokens.SPACING_MD, tokens.SPACING_MD, tokens.SPACING_MD)
        layout.setSpacing(tokens.SPACING_SM)
        self._title = QLabel("待辦與索件提醒")
        self._title.setObjectName("SectionTitle")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._title)
        self._summary = QLabel(self._compact_summary)
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(True)
        self._summary.setObjectName("WorkbenchMuted")
        layout.addWidget(self._summary)
        self._list = QListWidget()
        self._list.setObjectName("TodayWorkList")
        self._list.setAccessibleName("待辦與索件提醒清單，按 Enter 開啟選取項目")
        self._list.setWordWrap(False)
        self._list.setUniformItemSizes(True)
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemActivated.connect(lambda _item: self.open_current())
        self._list.itemSelectionChanged.connect(self._selection_changed)
        self._list.currentRowChanged.connect(lambda _row: self._selection_changed())
        self._list.hide()
        layout.addWidget(self._list, 1)
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        self._message.setAccessibleName("提醒載入狀態")
        self._message.hide()
        layout.addWidget(self._message)
        self._open_btn = make_button("開啟選取項目", role=tokens.ROLE_SECONDARY, icon_role="open")
        self._open_btn.setAccessibleName("開啟選取的待辦或索件批次")
        self._open_btn.clicked.connect(self.open_current)
        self._open_btn.hide()
        layout.addWidget(self._open_btn)
        self._retry_btn = make_button("重試載入", role=tokens.ROLE_QUIET, icon_role="refresh")
        self._retry_btn.setAccessibleName("重新載入待辦與索件提醒")
        self._retry_btn.clicked.connect(self.refresh)
        self._retry_btn.hide()
        layout.addWidget(self._retry_btn)
        self._browse_btn = make_button("查看全部待辦", role=tokens.ROLE_LINK)
        self._browse_btn.setAccessibleName("前往全部待辦清單")
        self._browse_btn.clicked.connect(
            lambda: self.navigate_requested.emit(NavigationTarget(PAGE_TASKS))
        )
        self._browse_btn.hide()
        layout.addWidget(self._browse_btn)

    @property
    def compact_summary(self) -> str:
        """Use on the collapsed reminder button; failure never masquerades as 0."""
        return self._compact_summary

    @property
    def due_count(self) -> int | None:
        return self._due_summary.count if self._due_summary is not None else None

    @property
    def earliest_due_date(self) -> str | None:
        return self._due_summary.earliest_due_date if self._due_summary is not None else None

    @property
    def state_kind(self) -> str:
        return self._state.kind

    def refresh(self) -> None:
        try:
            today = today_iso()
            tasks = self._container.tasks.list_overdue(today) + self._container.tasks.list_due_today(today)
            requests = all_document_requests(self._container)
            engagements = []
            for engagement_id in sorted(due_engagement_ids(tasks, requests, today)):
                engagement = self._container.engagements.get_engagement(engagement_id)
                if engagement is None or engagement.deleted_at is not None:
                    raise TodayQueueValidationError("engagement_not_found", kind="engagement", record_id=engagement_id)
                engagements.append(engagement)
            items = tuple(build_today_queue(tasks, requests, engagements, today))
            cases = {row.id: row for row in engagements}
            clients: dict[int, str] = {}
            contexts: dict[tuple[str, int], str] = {}
            for work in items:
                if work.client_id is not None and work.client_id not in clients:
                    client = self._container.clients.get_client(work.client_id)
                    if client is None or client.deleted_at is not None:
                        raise TodayQueueValidationError("client_not_found", kind=work.kind, record_id=work.record_id)
                    if not all(isinstance(value, str) and value.strip() for value in (client.client_code, client.client_name)):
                        raise TodayQueueValidationError("invalid_client", kind=work.kind, record_id=work.record_id)
                    clients[work.client_id] = f"{client.client_code} · {client.client_name}"
                if work.engagement_id is not None:
                    contexts[work.key] = f"{clients[work.client_id]} / {cases[work.engagement_id].engagement_name}"
                elif work.client_id is not None:
                    contexts[work.key] = f"{clients[work.client_id]} / 未關聯案件"
                else:
                    contexts[work.key] = "未關聯客戶或案件"
            self._contexts = contexts
            self.render_state(_QueueState(
                "success" if items else "empty", rows=items,
                last_success_at=datetime.now().strftime("%m/%d %H:%M"),
            ), today=today)
        except Exception as exc:
            # Failed reads retain the last successful snapshot and its timestamp.
            # Logging is diagnostic only: the visible state always reports failure.
            _log.warning("due reminder load failed (%s)", type(exc).__name__, exc_info=True)
            previous = self._state
            state = _QueueState(
                "stale" if previous.last_success_at is not None else "error",
                rows=previous.rows if previous.last_success_at is not None else (),
                error="無法載入待辦與索件提醒。請重試。",
                last_success_at=previous.last_success_at,
            )
            self.render_state(state)

    def render_state(self, state: _QueueState, *, today: str | None = None) -> None:
        current = self._list.currentItem()
        old_key = current.data(Qt.ItemDataRole.UserRole).key if current is not None and current.isSelected() else None
        if state.kind in {"success", "empty"}:
            self._list.clear()
            cutoff = date.fromisoformat(today if today is not None else today_iso())
            for work in state.rows:
                days = (cutoff - date.fromisoformat(work.due_date)).days
                timing = f"逾期 {days} 天" if days else "今天到期"
                context = self._contexts[work.key]
                # Keep each row to three concise lines. Preserve original text
                # in its tooltip/accessibility description, including newlines.
                title_line = " ".join(work.title.split())
                context_line = " ".join(context.split())
                item = QListWidgetItem(
                    f"{work.due_date[5:].replace('-', '/')} · {timing} · {'待辦' if work.task_id is not None else '索件'}\n"
                    f"{title_line}\n{context_line}"
                )
                item.setData(Qt.ItemDataRole.UserRole, work)
                item.setToolTip(f"{work.source_label}：{work.title}\n{context}\n截止：{work.due_date}\n{work.status_label}")
                item.setData(Qt.ItemDataRole.AccessibleTextRole, item.toolTip())
                self._list.addItem(item)
                if work.key == old_key:
                    self._list.setCurrentItem(item)
            self._due_summary = summarize_today_queue(state.rows)
            compact = self._due_summary.compact
            self._message.setText("目前沒有今天到期或逾期的待辦與索件。" if state.kind == "empty" else "")
        elif state.kind == "stale":
            # Do not redraw/re-sort the last successful rows after a failed read.
            self._due_summary = summarize_today_queue(state.rows)
            compact = f"{self._due_summary.compact} · 未更新"
            self._message.setText(f"更新失敗，顯示 {state.last_success_at} 的資料。請重試。")
        else:
            self._list.clear()
            self._due_summary = None
            compact = "提醒載入失敗" if state.kind == "error" else "提醒載入中"
            self._message.setText(state.error or "")
        self._summary.setText(compact)
        self._message.setVisible(bool(self._message.text()))
        self._retry_btn.setVisible(state.kind in {"error", "stale"})
        self._browse_btn.setVisible(state.kind == "empty")
        self._list.setVisible(bool(state.rows))
        self._state = state
        self._items = list(state.rows)
        self._selection_changed()
        if compact != self._compact_summary:
            self._compact_summary = compact
            self.summary_changed.emit(compact)

    def _selection_changed(self) -> None:
        item = self._list.currentItem()
        self._open_btn.setVisible(item is not None and item.isSelected())

    def open_current(self) -> None:
        item = self._list.currentItem()
        if item is None or not item.isSelected():
            return
        work = item.data(Qt.ItemDataRole.UserRole)
        if work.task_id is not None:
            target = NavigationTarget(PAGE_TASKS, task_id=work.task_id, engagement_id=work.engagement_id)
        else:
            target = NavigationTarget(PAGE_ENGAGEMENTS, engagement_id=work.engagement_id, request_id=work.request_id)
        # The shared navigation layer revalidates ownership and soft deletion.
        self.navigate_requested.emit(target)
