"""Shared, fixed-order client profile form used by create and edit dialogs."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


_PROFILE_FIELD_MAX_WIDTH = 560


def _multiline(placeholder: str = "") -> QPlainTextEdit:
    editor = QPlainTextEdit()
    editor.setMinimumHeight(72)
    editor.setMaximumWidth(_PROFILE_FIELD_MAX_WIDTH)
    editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    editor.setPlaceholderText(placeholder)
    return editor


class ClientProfileForm(QWidget):
    """Business-ordered fields whose layout does not reflow by window width."""

    def __init__(self, client: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self.client_code = QLineEdit(getattr(client, "client_code", "") or "")
        self.client_code.setMaxLength(50)
        self.client_code.setPlaceholderText("必填，例如 C001")
        self.client_name = QLineEdit(getattr(client, "client_name", "") or "")
        self.client_name.setMaxLength(200)
        self.tax_id = QLineEdit(getattr(client, "tax_id", "") or "")
        self.tax_id.setMaxLength(8)
        self.short_name = QLineEdit(getattr(client, "short_name", "") or "")
        self.contact_name = QLineEdit(getattr(client, "contact_name", "") or "")
        self.contact_phone = QLineEdit(getattr(client, "contact_phone", "") or "")
        self.contact_email = QLineEdit(getattr(client, "contact_email", "") or "")
        self.registered_address = _multiline("工商／稅籍登記地址")
        self.registered_address.setPlainText(
            getattr(client, "registered_address", None)
            or getattr(client, "address", None)
            or ""
        )
        self.contact_same = QCheckBox("聯絡地址同登記地址")
        same = bool(getattr(client, "contact_address_same", True))
        self.contact_same.setChecked(same)
        self.contact_address = _multiline("收件、寄送或實際聯絡地址")
        self.contact_address.setPlainText(getattr(client, "contact_address", None) or "")
        self.note = _multiline("特殊要求、溝通偏好與內部提醒；換行會完整保留")
        self.note.setPlainText(getattr(client, "note", None) or "")

        for editor in (
            self.client_code,
            self.client_name,
            self.tax_id,
            self.short_name,
            self.contact_name,
            self.contact_phone,
            self.contact_email,
        ):
            editor.setMaximumWidth(_PROFILE_FIELD_MAX_WIDTH)

        rows = (
            ("客戶代號", self.client_code),
            ("客戶名稱", self.client_name),
            ("統一編號", self.tax_id),
            ("簡稱", self.short_name),
            ("聯絡人", self.contact_name),
            ("聯絡電話", self.contact_phone),
            ("聯絡信箱", self.contact_email),
            ("登記地址", self.registered_address),
            ("", self.contact_same),
            ("聯絡地址", self.contact_address),
            ("特殊要求／備註", self.note),
        )
        for label, widget in rows:
            form.addRow(QLabel(label), widget)
        outer.addLayout(form)

        self.field_widgets = tuple(widget for _label, widget in rows)
        self.contact_same.toggled.connect(self._on_same_toggled)
        self._on_same_toggled(same)

    def _on_same_toggled(self, checked: bool) -> None:
        # Do not rewrite the editor. A user may uncheck again and expects the
        # independently entered mailing address to still be there.
        self.contact_address.setEnabled(not checked)

    def values_for_save(self) -> dict[str, object]:
        registered = self.registered_address.toPlainText()
        same = self.contact_same.isChecked()
        return {
            "client_code": self.client_code.text(),
            "client_name": self.client_name.text(),
            "tax_id": self.tax_id.text(),
            "short_name": self.short_name.text(),
            "contact_name": self.contact_name.text(),
            "contact_phone": self.contact_phone.text(),
            "contact_email": self.contact_email.text(),
            "registered_address": registered,
            "contact_address": registered if same else self.contact_address.toPlainText(),
            "contact_address_same": same,
            "note": self.note.toPlainText(),
        }

    def focus_for_error(self, code: str) -> None:
        if code in {"client.client_code.required", "client.client_code.duplicate"}:
            self.client_code.setFocus()
        elif code == "client.client_name.required":
            self.client_name.setFocus()
        elif code == "client.tax_id.invalid":
            self.tax_id.setFocus()
