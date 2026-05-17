"""Edit client dialog — pre-populated form for updating an existing client."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

from ...i18n import BUTTON_LABELS, error_message
from ...repositories.clients import ClientRow
from ...services.clients import (
    ClientValidationError,
    ClientsService,
    UpdateClientInput,
)


class EditClientDialog(QDialog):
    def __init__(
        self,
        clients_service: ClientsService,
        client: ClientRow,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._clients = clients_service
        self._client_id = client.id
        self.setWindowTitle("編輯客戶")
        self.setModal(True)
        self.setMinimumWidth(420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._client_code = QLineEdit(client.client_code)
        self._client_code.setMaxLength(50)
        self._client_name = QLineEdit(client.client_name)
        self._client_name.setMaxLength(200)
        self._tax_id = QLineEdit(client.tax_id or "")
        self._tax_id.setMaxLength(8)
        self._short_name = QLineEdit(client.short_name or "")
        self._contact_name = QLineEdit(client.contact_name or "")
        self._contact_phone = QLineEdit(client.contact_phone or "")
        self._contact_email = QLineEdit(client.contact_email or "")
        self._address = QLineEdit(client.address or "")
        self._note = QTextEdit(client.note or "")
        self._note.setFixedHeight(80)

        form.addRow(QLabel("客戶代號"), self._client_code)
        form.addRow(QLabel("客戶名稱"), self._client_name)
        form.addRow(QLabel("統一編號"), self._tax_id)
        form.addRow(QLabel("簡稱"), self._short_name)
        form.addRow(QLabel("聯絡人"), self._contact_name)
        form.addRow(QLabel("聯絡電話"), self._contact_phone)
        form.addRow(QLabel("聯絡信箱"), self._contact_email)
        form.addRow(QLabel("地址"), self._address)
        form.addRow(QLabel("備註"), self._note)

        outer.addLayout(form)

        self._buttons = QDialogButtonBox()
        save_btn = self._buttons.addButton("儲存變更", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = self._buttons.addButton(
            BUTTON_LABELS["client_dialog.cancel"],
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        save_btn.setDefault(True)
        outer.addWidget(self._buttons)

        save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.on_cancel)

    def on_save(self) -> None:
        payload = UpdateClientInput(
            client_code=self._client_code.text(),
            client_name=self._client_name.text(),
            tax_id=self._tax_id.text(),
            short_name=self._short_name.text(),
            contact_name=self._contact_name.text(),
            contact_phone=self._contact_phone.text(),
            contact_email=self._contact_email.text(),
            address=self._address.text(),
            note=self._note.toPlainText(),
        )
        try:
            self._clients.update_client(self._client_id, payload)
        except ClientValidationError as err:
            QMessageBox.warning(self, "輸入有誤", error_message(err.code))
            self._focus_first_invalid(err.code)
            return
        except Exception:
            QMessageBox.warning(self, "更新失敗", error_message("client.update.failed"))
            return
        self.accept()

    def on_cancel(self) -> None:
        self.reject()

    def _focus_first_invalid(self, code: str) -> None:
        if code in ("client.client_code.required", "client.client_code.duplicate"):
            self._client_code.setFocus()
        elif code == "client.client_name.required":
            self._client_name.setFocus()
        elif code == "client.tax_id.invalid":
            self._tax_id.setFocus()
