"""Create the same engagement for multiple selected clients atomically."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...services.engagements import (
    BulkCreateEngagementInput,
    EngagementValidationError,
    EngagementsService,
)
from ..widgets.date_field import DateField
from ._shared import TAX_TYPE_CHOICES


class BulkNewEngagementDialog(QDialog):
    def __init__(
        self,
        engagements_service: EngagementsService,
        clients: list[object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = engagements_service
        self.setWindowTitle("多客戶同時新增案件")
        self.setModal(True)
        self.resize(660, 600)
        self.setMinimumSize(560, 500)

        outer = QVBoxLayout(self)
        help_label = QLabel(
            "勾選多位客戶後，系統會用相同案件內容一次建立。"
            "任一客戶或欄位驗證失敗時，整批都不會寫入。"
        )
        help_label.setWordWrap(True)
        outer.addWidget(help_label)
        outer.addWidget(QLabel("客戶（可複選）"))
        self.clients_list = QListWidget()
        self.clients_list.setMinimumHeight(170)
        for client in clients:
            item = QListWidgetItem(
                f"{getattr(client, 'client_code', '')}  {getattr(client, 'client_name', '')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, getattr(client, "id", None))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.clients_list.addItem(item)
        outer.addWidget(self.clients_list)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(200)
        self.tax_type_combo = QComboBox()
        for value, label in TAX_TYPE_CHOICES:
            self.tax_type_combo.addItem(label, value)
        self.period_input = QLineEdit()
        self.period_input.setMaxLength(50)
        self.owner_input = QLineEdit()
        self.owner_input.setMaxLength(100)
        self.due_date_input = DateField(required=False)
        self.notes_input = QTextEdit()
        self.notes_input.setFixedHeight(72)
        form.addRow("案件名稱 *", self.name_input)
        form.addRow("稅種 *", self.tax_type_combo)
        form.addRow("期間名稱 *", self.period_input)
        form.addRow("負責人", self.owner_input)
        form.addRow("到期日", self.due_date_input)
        form.addRow("備註", self.notes_input)
        outer.addLayout(form)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton(
            "建立所選案件", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel_button = buttons.addButton(
            "取消", QDialogButtonBox.ButtonRole.RejectRole
        )
        outer.addWidget(buttons)
        self.save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)

    def _selected_client_ids(self) -> tuple[int, ...]:
        return tuple(
            int(item.data(Qt.ItemDataRole.UserRole))
            for row in range(self.clients_list.count())
            if (item := self.clients_list.item(row)).checkState()
            == Qt.CheckState.Checked
        )

    def _save(self) -> None:
        client_ids = self._selected_client_ids()
        if not client_ids:
            QMessageBox.warning(self, "尚未選擇", "請至少勾選一位客戶。")
            return
        try:
            due_date = self.due_date_input.validated_value()
        except DateField.InvalidInput:
            return
        self.save_button.setEnabled(False)
        try:
            self._svc.create_for_clients(
                BulkCreateEngagementInput(
                    client_ids=client_ids,
                    engagement_name=self.name_input.text(),
                    tax_type=str(self.tax_type_combo.currentData()),
                    period_name=self.period_input.text(),
                    owner=self.owner_input.text() or None,
                    due_date=due_date,
                    notes=self.notes_input.toPlainText() or None,
                )
            )
        except EngagementValidationError as err:
            QMessageBox.warning(self, "輸入有誤", error_message(err.code))
            self.save_button.setEnabled(True)
            return
        except Exception:
            QMessageBox.warning(
                self, "新增失敗", "整批案件均未建立，請稍後再試。"
            )
            self.save_button.setEnabled(True)
            return
        self.accept()
