"""Create/edit one client lease, including persisted-lease attachments."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...repositories.attachments import AttachmentRow
from ...repositories.client_leases import ClientLeaseRow
from ...services.client_leases import (
    ClientLeaseValidationError,
    LeaseInput,
    validate_lease_input,
)
from ..widgets.date_field import DateField

if TYPE_CHECKING:
    from ...services.container import ServiceContainer


def _plain(text: str = "") -> QPlainTextEdit:
    editor = QPlainTextEdit(text)
    editor.setMinimumHeight(72)
    editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    return editor


def _format_amount(value: int | None) -> str:
    return "" if value is None else f"{value:,}"


_LEASE_ERRORS = {
    "client_lease.name.required": "請輸入租約名稱。",
    "client_lease.date.invalid": "日期格式不正確，請使用西元年月日。",
    "client_lease.date_range.invalid": "租約迄日不可早於起日。",
    "client_lease.amount.invalid": "租金與押金必須是零以上的整數金額。",
    "client_lease.reminder_days.invalid": "提醒天數必須介於 0 到 3650 天。",
}


class ClientLeaseDialog(QDialog):
    def __init__(
        self,
        initial: LeaseInput | None = None,
        *,
        container: ServiceContainer | None = None,
        client_id: int | None = None,
        lease_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        initial = initial or LeaseInput("")
        self._container = container
        self._client_id = client_id
        self._lease_id = lease_id
        self.lease_input: LeaseInput | None = None
        self.setWindowTitle("編輯租約" if lease_id else "新增租約")
        self.setModal(True)
        self.resize(620, 650)

        outer = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.lease_name = QLineEdit(initial.lease_name)
        self.premises_address = _plain(initial.premises_address or "")
        self.landlord_name = QLineEdit(initial.landlord_name or "")
        self.start_date = DateField(required=False)
        self.start_date.set_value(initial.start_date)
        self.end_date = DateField(required=False)
        self.end_date.set_value(initial.end_date)
        self.monthly_rent = QLineEdit("" if initial.monthly_rent is None else str(initial.monthly_rent))
        self.deposit_amount = QLineEdit("" if initial.deposit_amount is None else str(initial.deposit_amount))
        self.monthly_rent.setPlaceholderText("可留空；僅輸入整數")
        self.deposit_amount.setPlaceholderText("可留空；僅輸入整數")
        self.reminder_days = QSpinBox()
        self.reminder_days.setRange(0, 3650)
        self.reminder_days.setValue(initial.reminder_days)
        self.status = QComboBox()
        for label, value in (("有效", "active"), ("已到期", "expired"), ("已終止", "terminated")):
            self.status.addItem(label, value)
        index = self.status.findData(initial.status)
        self.status.setCurrentIndex(max(0, index))
        self.notes = _plain(initial.notes or "")
        for label, widget in (
            ("租約名稱", self.lease_name),
            ("租賃處所地址", self.premises_address),
            ("房東／出租人", self.landlord_name),
            ("租約起日", self.start_date),
            ("租約迄日", self.end_date),
            ("每月租金", self.monthly_rent),
            ("押金", self.deposit_amount),
            ("到期前提醒天數", self.reminder_days),
            ("狀態", self.status),
            ("備註", self.notes),
        ):
            form.addRow(label, widget)
        content_layout.addLayout(form)

        attachment_row = QHBoxLayout()
        self.upload_attachment_button = QPushButton("上傳租約附件")
        self.view_attachments_button = QPushButton("查看附件")
        persisted = container is not None and client_id is not None and lease_id is not None
        self.upload_attachment_button.setEnabled(persisted)
        self.view_attachments_button.setEnabled(persisted)
        attachment_row.addWidget(self.upload_attachment_button)
        attachment_row.addWidget(self.view_attachments_button)
        attachment_row.addStretch(1)
        content_layout.addLayout(attachment_row)
        self.attachment_explanation = QLabel(
            "可上傳、查看已儲存租約的附件。" if persisted else "請先儲存客戶與租約，之後才能上傳附件。"
        )
        self.attachment_explanation.setWordWrap(True)
        content_layout.addWidget(self.attachment_explanation)
        content_layout.addStretch(1)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area, 1)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("套用租約", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        outer.addWidget(buttons)
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.reject)
        self.upload_attachment_button.clicked.connect(self._upload_attachment)
        self.view_attachments_button.clicked.connect(self._view_attachments)

    @staticmethod
    def _amount(editor: QLineEdit) -> int | None:
        raw = editor.text().strip().replace(",", "")
        if not raw:
            return None
        if not raw.isdecimal():
            raise ValueError
        return int(raw)

    def _save(self) -> None:
        self.save_button.setEnabled(False)
        try:
            payload = LeaseInput(
                lease_name=self.lease_name.text(),
                premises_address=self.premises_address.toPlainText(),
                landlord_name=self.landlord_name.text(),
                start_date=self.start_date.validated_value(),
                end_date=self.end_date.validated_value(),
                monthly_rent=self._amount(self.monthly_rent),
                deposit_amount=self._amount(self.deposit_amount),
                reminder_days=self.reminder_days.value(),
                notes=self.notes.toPlainText(),
                status=str(self.status.currentData()),
            )
            validate_lease_input(payload)
        except ValueError:
            QMessageBox.warning(self, "租約輸入有誤", "租金與押金必須是零以上的整數金額。")
        except DateField.InvalidInput:
            QMessageBox.warning(self, "租約輸入有誤", "日期格式不正確，請使用西元年月日。")
        except ClientLeaseValidationError as exc:
            QMessageBox.warning(
                self,
                "租約輸入有誤",
                _LEASE_ERRORS.get(exc.code, "租約資料不正確，請檢查輸入內容。"),
            )
        else:
            self.lease_input = payload
            self.accept()
            return
        finally:
            if self.result() != self.DialogCode.Accepted:
                self.save_button.setEnabled(True)

    def _upload_attachment(self) -> None:
        if self._container is None or self._client_id is None or self._lease_id is None:
            return
        filename, _selected_filter = QFileDialog.getOpenFileName(self, "選擇租約附件")
        if not filename:
            return
        try:
            self._container.attachments.upload_lease_attachment(
                self._client_id, self._lease_id, Path(filename)
            )
        except Exception:
            QMessageBox.warning(self, "附件上傳失敗", "附件未能上傳，請檢查檔案後再試。")
            return
        QMessageBox.information(self, "附件已上傳", "租約附件已安全儲存。")

    def _view_attachments(self) -> None:
        if (
            self._container is None
            or self._client_id is None
            or self._lease_id is None
        ):
            return
        try:
            rows = self._container.attachments.list_lease_history_attachments(
                self._client_id, self._lease_id
            )
        except Exception:
            QMessageBox.warning(self, "附件讀取失敗", "目前無法讀取租約附件。")
            return
        body = "\n".join(row.original_filename for row in rows) or "此租約尚無附件。"
        QMessageBox.information(self, "租約附件", body)


class ClientLeaseHistoryDialog(QDialog):
    """Read-only historical lease and attachment evidence."""

    def __init__(
        self,
        lease: ClientLeaseRow,
        attachments: list[AttachmentRow],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("租約歷史資料")
        self.setModal(True)
        self.resize(680, 560)
        outer = QVBoxLayout(self)
        notice = QLabel("此租約已封存，以下資料與附件僅供歷史查閱。")
        notice.setWordWrap(True)
        outer.addWidget(notice)

        status_label = {
            "active": "有效",
            "expired": "已到期",
            "terminated": "已終止",
        }.get(lease.status, "未知狀態")
        details = (
            f"租約名稱：{lease.lease_name}\n"
            f"租賃處所地址：\n{lease.premises_address or ''}\n"
            f"房東／出租人：{lease.landlord_name or ''}\n"
            f"租約起日：{lease.start_date or ''}\n"
            f"租約迄日：{lease.end_date or ''}\n"
            f"每月租金：{_format_amount(lease.monthly_rent)}\n"
            f"押金：{_format_amount(lease.deposit_amount)}\n"
            f"到期前提醒天數：{lease.reminder_days}\n"
            f"狀態：{status_label}\n"
            f"備註：\n{lease.notes or ''}\n"
            f"建立時間：{lease.created_at}\n"
            f"更新時間：{lease.updated_at}\n"
            f"封存時間：{lease.deleted_at or ''}"
        )
        self.details_text = _plain(details)
        self.details_text.setReadOnly(True)
        outer.addWidget(QLabel("完整租約資料"))
        outer.addWidget(self.details_text, 2)

        attachment_body = (
            "\n".join(row.original_filename for row in attachments)
            or "此租約沒有歷史附件。"
        )
        self.attachments_text = _plain(attachment_body)
        self.attachments_text.setReadOnly(True)
        outer.addWidget(QLabel("附件歷史"))
        outer.addWidget(self.attachments_text, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.close_button = QPushButton("關閉")
        actions.addWidget(self.close_button)
        outer.addLayout(actions)
        self.close_button.clicked.connect(self.accept)
