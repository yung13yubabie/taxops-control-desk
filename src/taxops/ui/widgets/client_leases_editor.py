"""Staged multiple-lease editor; database writes happen only with profile save."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...repositories.client_leases import ClientLeaseRow
from ...services.client_leases import LeaseInput
from ...services.client_profiles import LeaseChange
from ..dialogs.client_lease_dialog import ClientLeaseDialog, ClientLeaseHistoryDialog

if TYPE_CHECKING:
    from ...services.container import ServiceContainer


@dataclass
class _Entry:
    lease_id: int | None
    payload: LeaseInput
    operation: str
    source_row: ClientLeaseRow | None = None


def lease_input_from_row(row: ClientLeaseRow) -> LeaseInput:
    return LeaseInput(
        lease_name=row.lease_name,
        premises_address=row.premises_address,
        landlord_name=row.landlord_name,
        start_date=row.start_date,
        end_date=row.end_date,
        monthly_rent=row.monthly_rent,
        deposit_amount=row.deposit_amount,
        reminder_days=row.reminder_days,
        notes=row.notes,
        status=row.status,
    )


class ClientLeasesEditor(QWidget):
    def __init__(
        self,
        container: ServiceContainer | None,
        *,
        client_id: int | None = None,
        leases: list[ClientLeaseRow] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._client_id = client_id
        self._history_dialog: ClientLeaseHistoryDialog | None = None
        self._entries = [
            _Entry(
                row.id,
                lease_input_from_row(row),
                "history" if row.deleted_at is not None else "unchanged",
                row,
            )
            for row in (leases or [])
        ]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.availability_label = QLabel(
            "可先新增多筆租約，儲存客戶時會一次寫入。"
            if container is not None
            else "此相容入口不支援多筆租約；請從客戶管理開啟完整表單。"
        )
        self.availability_label.setWordWrap(True)
        outer.addWidget(self.availability_label)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("新增租約")
        self.edit_button = QPushButton("編輯租約")
        self.archive_button = QPushButton("刪除／封存租約")
        self.view_button = QPushButton("查看租約／附件")
        self.edit_button.setEnabled(False)
        self.archive_button.setEnabled(False)
        self.view_button.setEnabled(False)
        self.add_button.setEnabled(container is not None)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.archive_button)
        buttons.addWidget(self.view_button)
        buttons.addStretch(1)
        outer.addLayout(buttons)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["租約名稱", "處所地址", "出租人", "起日", "迄日", "月租", "編輯狀態"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table)
        self.add_button.clicked.connect(self._open_add)
        self.edit_button.clicked.connect(self._open_edit)
        self.archive_button.clicked.connect(self._archive_selected)
        self.view_button.clicked.connect(self._open_view)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(lambda _index: self._open_selected())
        self.refresh()

    def _selection_changed(self) -> None:
        selected = self._selected_entry()
        editable = selected is not None and selected.operation not in {
            "archive",
            "history",
        }
        self.edit_button.setEnabled(editable and self._container is not None)
        self.archive_button.setEnabled(editable and self._container is not None)
        self.view_button.setEnabled(
            selected is not None
            and selected.operation == "history"
            and selected.source_row is not None
            and self._container is not None
        )

    def _selected_entry(self) -> _Entry | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        visible = self._entries
        return visible[row] if row < len(visible) else None

    def _open_add(self) -> None:
        if self._container is None:
            return
        dialog = ClientLeaseDialog(parent=self)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.lease_input is not None:
            self.add_payload(dialog.lease_input)

    def _open_edit(self) -> None:
        entry = self._selected_entry()
        if (
            entry is None
            or entry.operation in {"archive", "history"}
            or self._container is None
        ):
            return
        dialog = ClientLeaseDialog(
            entry.payload,
            container=self._container if entry.lease_id is not None else None,
            client_id=self._client_id,
            lease_id=entry.lease_id,
            parent=self,
        )
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.lease_input is not None:
            if entry.lease_id is None:
                entry.payload = dialog.lease_input
            else:
                self.stage_update(entry.lease_id, dialog.lease_input)
            self.refresh()

    def _open_selected(self) -> None:
        entry = self._selected_entry()
        if entry is not None and entry.operation == "history":
            self._open_view()
        else:
            self._open_edit()

    def _open_view(self) -> None:
        entry = self._selected_entry()
        if (
            entry is None
            or entry.operation != "history"
            or entry.source_row is None
            or entry.lease_id is None
            or self._client_id is None
            or self._container is None
        ):
            return
        try:
            attachments = (
                self._container.attachments.list_lease_history_attachments(
                    self._client_id, entry.lease_id
                )
            )
        except Exception:
            QMessageBox.warning(
                self,
                "歷史資料讀取失敗",
                "目前無法讀取這筆租約與附件歷史。",
            )
            return
        dialog = ClientLeaseHistoryDialog(
            entry.source_row, attachments, parent=self
        )
        self._history_dialog = dialog
        try:
            dialog.exec()
        finally:
            dialog.setParent(None)
            dialog.deleteLater()
            self._history_dialog = None

    def _archive_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None or entry.operation in {"archive", "history"}:
            return
        if QMessageBox.question(
            self,
            "確認移除租約",
            f"確定要移除「{entry.payload.lease_name}」？\n已儲存租約會保留歷史附件並標記封存。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        if entry.lease_id is None:
            self._entries.remove(entry)
        else:
            entry.operation = "archive"
        self.refresh()

    def add_payload(self, payload: LeaseInput) -> None:
        self._entries.append(_Entry(None, payload, "create"))
        self.refresh()

    def stage_update(self, lease_id: int, payload: LeaseInput) -> None:
        entry = next((item for item in self._entries if item.lease_id == lease_id), None)
        if entry is None:
            raise ValueError("lease not loaded")
        if entry.operation in {"archive", "history"}:
            raise ValueError("archived lease is read-only")
        entry.payload = payload
        entry.operation = "update"
        self.refresh()

    def stage_archive(self, lease_id: int) -> None:
        entry = next((item for item in self._entries if item.lease_id == lease_id), None)
        if entry is None:
            raise ValueError("lease not loaded")
        if entry.operation in {"archive", "history"}:
            raise ValueError("archived lease is read-only")
        entry.operation = "archive"
        self.refresh()

    def create_inputs(self) -> tuple[LeaseInput, ...]:
        return tuple(entry.payload for entry in self._entries if entry.operation == "create")

    def changes(self) -> tuple[LeaseChange, ...]:
        changes: list[LeaseChange] = []
        for entry in self._entries:
            if entry.operation == "create":
                changes.append(LeaseChange("create", payload=entry.payload))
            elif entry.operation == "update":
                changes.append(LeaseChange("update", lease_id=entry.lease_id, payload=entry.payload))
            elif entry.operation == "archive":
                changes.append(LeaseChange("archive", lease_id=entry.lease_id))
        return tuple(changes)

    def refresh(self) -> None:
        status_labels = {
            "unchanged": "已儲存",
            "create": "待新增",
            "update": "待更新",
            "archive": "待封存",
            "history": "已封存（歷史）",
        }
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            payload = entry.payload
            values = (
                payload.lease_name,
                payload.premises_address or "",
                payload.landlord_name or "",
                payload.start_date or "",
                payload.end_date or "",
                "" if payload.monthly_rent is None else f"{payload.monthly_rent:,}",
                status_labels[entry.operation],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value.replace("\n", " ／ "))
                item.setToolTip(value)
                if entry.operation in {"archive", "history"}:
                    item.setForeground(QColor(120, 120, 120))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self._selection_changed()
