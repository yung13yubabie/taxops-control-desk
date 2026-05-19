"""New client dialog.

Collects the minimum fields for slice 1 client creation, validates via
``ClientsService``, and surfaces Chinese error messages — never raw
exceptions.

Optional ``tax_registry_repo`` enables a lookup panel that lets the user
search by tax ID or company name and auto-fill form fields from the result.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import BUTTON_LABELS, error_message
from ...repositories.tax_registry import TaxRegistryRepository
from ...services.clients import (
    ClientValidationError,
    ClientsService,
    CreateClientInput,
)

_log = logging.getLogger(__name__)


class NewClientDialog(QDialog):
    def __init__(
        self,
        clients_service: ClientsService,
        parent: QWidget | None = None,
        tax_registry_repo: TaxRegistryRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self._clients = clients_service
        self._registry_repo = tax_registry_repo
        self._registry_results: list = []
        self._registry_prefill: dict | None = None

        self.setWindowTitle("新增客戶")
        self.setModal(True)
        self.setMinimumWidth(460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # ---------------------------------------------------------------
        # Registry lookup panel (shown only when cache is available)
        # ---------------------------------------------------------------
        if self._registry_repo is not None:
            lookup_box = QGroupBox("從稅籍資料庫查詢（輸入統編或公司名稱）")
            lookup_layout = QVBoxLayout(lookup_box)
            lookup_layout.setSpacing(6)

            search_row = QHBoxLayout()
            self._search_input = QLineEdit()
            self._search_input.setPlaceholderText("統一編號（8位數字）或公司名稱關鍵字")
            self._search_btn = QPushButton("查詢")
            self._search_btn.setFixedWidth(60)
            search_row.addWidget(self._search_input, 1)
            search_row.addWidget(self._search_btn)
            lookup_layout.addLayout(search_row)

            result_row = QHBoxLayout()
            self._result_combo = QComboBox()
            self._result_combo.setPlaceholderText("查詢後選擇結果")
            self._result_combo.setEnabled(False)
            self._fill_btn = QPushButton("帶入欄位")
            self._fill_btn.setEnabled(False)
            result_row.addWidget(self._result_combo, 1)
            result_row.addWidget(self._fill_btn)
            lookup_layout.addLayout(result_row)

            outer.addWidget(lookup_box)

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFrameShadow(QFrame.Shadow.Sunken)
            outer.addWidget(sep)

            self._search_btn.clicked.connect(self._on_search)
            self._fill_btn.clicked.connect(self._on_fill)
            self._search_input.returnPressed.connect(self._on_search)

        # ---------------------------------------------------------------
        # Client form
        # ---------------------------------------------------------------
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._client_code = QLineEdit()
        self._client_code.setMaxLength(50)
        self._client_code.setPlaceholderText("必填，例如 C001")
        self._client_name = QLineEdit()
        self._client_name.setMaxLength(200)
        self._tax_id = QLineEdit()
        self._tax_id.setMaxLength(8)
        self._short_name = QLineEdit()
        self._contact_name = QLineEdit()
        self._contact_phone = QLineEdit()
        self._contact_email = QLineEdit()
        self._address = QLineEdit()
        self._note = QTextEdit()
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
        save_btn = self._buttons.addButton(
            BUTTON_LABELS["client_dialog.save"],
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        cancel_btn = self._buttons.addButton(
            BUTTON_LABELS["client_dialog.cancel"],
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self._save_btn = save_btn
        self._save_btn.setDefault(True)
        outer.addWidget(self._buttons)

        self._save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.on_cancel)

    # ------------------------------------------------------------------
    # Registry lookup
    # ------------------------------------------------------------------

    def _on_search(self) -> None:
        assert self._registry_repo is not None
        # Clear previous results first — prevents stale A results showing after B fails
        self._registry_results = []
        self._registry_prefill = None
        self._result_combo.clear()
        self._result_combo.setEnabled(False)
        self._fill_btn.setEnabled(False)

        query = self._search_input.text().strip()
        if not query:
            return
        try:
            results = self._registry_repo.search(query, limit=20)
        except Exception:
            _log.error("tax_registry.search failed", exc_info=True)
            QMessageBox.warning(
                self,
                "查詢失敗",
                "稅籍資料庫查詢發生錯誤，請直接手動輸入欄位資料。",
            )
            return
        self._registry_results = list(results)
        self._result_combo.clear()
        self._result_combo.setEnabled(bool(results))
        self._fill_btn.setEnabled(bool(results))
        if results:
            for i, row in enumerate(results):
                label = f"{row['tax_id']}  {row['business_name']}"
                self._result_combo.addItem(label)
                addr = row["business_address"] or ""
                self._result_combo.setItemData(i, addr, Qt.ItemDataRole.ToolTipRole)
        else:
            QMessageBox.information(self, "查無結果", "找不到符合的公司，請確認統編或名稱後再試。")

    def _on_fill(self) -> None:
        idx = self._result_combo.currentIndex()
        if idx < 0 or idx >= len(self._registry_results):
            return
        row = self._registry_results[idx]
        self._client_name.setText(row["business_name"] or "")
        self._tax_id.setText(row["tax_id"] or "")
        self._address.setText(row["business_address"] or "")
        self._registry_prefill = {
            "source_tax_id": row["tax_id"] or "",
            "cache_version": row["cache_version"] if "cache_version" in row.keys() else "",
            "prefill_time_note": "values recorded at fill time; user may have edited fields before saving",
        }
        self._client_code.setFocus()

    # ------------------------------------------------------------------
    # Save / cancel
    # ------------------------------------------------------------------

    def on_save(self) -> None:
        self._save_btn.setEnabled(False)
        try:
            payload = CreateClientInput(
                client_code=self._client_code.text(),
                client_name=self._client_name.text(),
                tax_id=self._tax_id.text(),
                short_name=self._short_name.text(),
                contact_name=self._contact_name.text(),
                contact_phone=self._contact_phone.text(),
                contact_email=self._contact_email.text(),
                address=self._address.text(),
                note=self._note.toPlainText(),
                registry_source_tax_id=(
                    self._registry_prefill.get("source_tax_id") if self._registry_prefill else None
                ),
                registry_cache_version=(
                    self._registry_prefill.get("cache_version") if self._registry_prefill else None
                ),
            )
            self._clients.create_client(payload)
        except ClientValidationError as err:
            self._show_error(error_message(err.code))
            self._focus_first_invalid(err.code)
            self._save_btn.setEnabled(True)
            return
        except Exception:
            self._show_error(error_message("client.create.failed"))
            self._save_btn.setEnabled(True)
            return
        self.accept()

    def on_cancel(self) -> None:
        self.reject()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "輸入有誤", message)

    def _focus_first_invalid(self, code: str) -> None:
        if code in ("client.client_code.required", "client.client_code.duplicate"):
            self._client_code.setFocus()
        elif code == "client.client_name.required":
            self._client_name.setFocus()
        elif code == "client.tax_id.invalid":
            self._tax_id.setFocus()
