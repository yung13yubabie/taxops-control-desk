"""Edit engagement dialog — pre-populated form for updating engagement fields."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...repositories.engagements import EngagementRow
from ...services.engagements import (
    EngagementValidationError,
    EngagementsService,
    UpdateEngagementInput,
)
from ._shared import TAX_TYPE_CHOICES, date_edit_value, make_nullable_date_edit, set_date_edit_value


class EditEngagementDialog(QDialog):
    def __init__(
        self,
        engagements_service: EngagementsService,
        engagement: EngagementRow,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = engagements_service
        self._engagement_id = engagement.id
        self._current_status = engagement.status

        self.setWindowTitle("編輯案件")
        self.setModal(True)
        self.setMinimumWidth(460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name = QLineEdit()
        self._name.setMaxLength(200)
        self._name.setText(engagement.engagement_name)

        self._tax_type = QComboBox()
        for value, label in TAX_TYPE_CHOICES:
            self._tax_type.addItem(label, userData=value)
        self._tax_type.setCurrentIndex(
            max(0, self._tax_type.findData(engagement.tax_type))
        )

        self._period = QLineEdit()
        self._period.setMaxLength(50)
        self._period.setText(engagement.period_name)

        self._owner = QLineEdit()
        self._owner.setMaxLength(100)
        self._owner.setText(engagement.owner or "")

        self._due_date = make_nullable_date_edit()
        set_date_edit_value(self._due_date, engagement.due_date)

        self._notes = QTextEdit()
        self._notes.setFixedHeight(72)
        self._notes.setPlainText(engagement.notes or "")

        form.addRow(QLabel("案件名稱 *"), self._name)
        form.addRow(QLabel("稅種 *"), self._tax_type)
        form.addRow(QLabel("期間名稱 *"), self._period)
        form.addRow(QLabel("負責人"), self._owner)
        form.addRow(QLabel("到期日"), self._due_date)
        form.addRow(QLabel("備註"), self._notes)

        outer.addLayout(form)

        buttons = QDialogButtonBox()
        self._save_btn = buttons.addButton(
            "儲存編輯", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._save_btn.setDefault(True)
        outer.addWidget(buttons)

        self._save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.reject)

    def on_save(self) -> None:
        self._save_btn.setEnabled(False)
        try:
            payload = UpdateEngagementInput(
                engagement_name=self._name.text(),
                tax_type=self._tax_type.currentData(),
                period_name=self._period.text(),
                status=self._current_status,
                owner=self._owner.text() or None,
                due_date=date_edit_value(self._due_date),
                notes=self._notes.toPlainText() or None,
            )
            self._svc.update_engagement(self._engagement_id, payload)
        except EngagementValidationError as err:
            QMessageBox.warning(self, "輸入有誤", error_message(err.code))
            if err.code == "engagement.name.required":
                self._name.setFocus()
            elif err.code == "engagement.period_name.required":
                self._period.setFocus()
            self._save_btn.setEnabled(True)
            return
        except Exception:
            QMessageBox.warning(self, "儲存失敗", error_message("engagement.update.failed"))
            self._save_btn.setEnabled(True)
            return
        self.accept()
