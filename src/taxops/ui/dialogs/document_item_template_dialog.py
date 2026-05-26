"""Checklist dialog for picking which document items go into a new request.

Replaces the old ``use_vat_template=True`` magic that silently inserted all 9
VAT items. The dialog presents the VAT_ITEMS as checkboxes plus a custom-item
input box; the user's last selection is persisted per tax_type in
``app_settings`` so repeat work doesn't require clicking every item again.

First-time use defaults to "all VAT items checked" — preserving the old
behaviour as the path of least resistance — and the user can then untick
items they don't need for this particular request.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...services.container import ServiceContainer
from ...services.document_requests import VAT_ITEMS

_log = logging.getLogger(__name__)

_PRESET_KEY_PREFIX = "ui.doc_request_template."
_MAX_CUSTOM_LEN = 100


def _preset_key(tax_type: str) -> str:
    return f"{_PRESET_KEY_PREFIX}{tax_type}"


def _default_items_for(tax_type: str) -> tuple[str, ...]:
    if tax_type == "vat":
        return VAT_ITEMS
    return ()


class DocumentItemTemplateDialog(QDialog):
    """Pick template + custom items for a new document request batch."""

    def __init__(
        self,
        container: ServiceContainer,
        tax_type: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._tax_type = tax_type
        self._template_items = _default_items_for(tax_type)

        self.setWindowTitle("選擇文件項目")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setMinimumHeight(440)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        outer.addWidget(QLabel(
            "勾選本次要索件的項目；下次再開此對話會自動還原上次選擇。"
        ))

        self._checkboxes: dict[str, QCheckBox] = {}
        if self._template_items:
            cb_box = QVBoxLayout()
            cb_box.setSpacing(4)
            for name in self._template_items:
                cb = QCheckBox(name)
                self._checkboxes[name] = cb
                cb_box.addWidget(cb)
            outer.addLayout(cb_box)

            quick_row = QHBoxLayout()
            self._select_all_btn = QPushButton("全選")
            self._select_none_btn = QPushButton("全不選")
            self._select_all_btn.clicked.connect(self._on_select_all)
            self._select_none_btn.clicked.connect(self._on_select_none)
            quick_row.addWidget(self._select_all_btn)
            quick_row.addWidget(self._select_none_btn)
            quick_row.addStretch()
            outer.addLayout(quick_row)
        else:
            outer.addWidget(QLabel(
                f"此稅種（{tax_type}）尚未設定預設模板。請在下方新增自訂項目。"
            ))

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(divider)

        outer.addWidget(QLabel("自訂項目"))
        custom_row = QHBoxLayout()
        self._custom_input = QLineEdit()
        self._custom_input.setPlaceholderText("輸入自訂項目名稱後按「加入」")
        self._custom_input.setMaxLength(_MAX_CUSTOM_LEN)
        add_btn = QPushButton("加入")
        add_btn.clicked.connect(self._on_add_custom)
        custom_row.addWidget(self._custom_input, stretch=1)
        custom_row.addWidget(add_btn)
        outer.addLayout(custom_row)

        self._custom_list = QListWidget()
        self._custom_list.setMaximumHeight(100)
        outer.addWidget(self._custom_list)

        remove_btn = QPushButton("移除選取的自訂項目")
        remove_btn.clicked.connect(self._on_remove_custom)
        outer.addWidget(remove_btn)

        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton("確定", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        ok_btn.setDefault(True)
        outer.addWidget(buttons)

        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

        self._restore_preset()

    def selected_items(self) -> tuple[str, ...]:
        """Return checked template items + all custom items, preserving order."""
        checked_template = [
            name for name in self._template_items if self._checkboxes[name].isChecked()
        ]
        custom = [
            self._custom_list.item(i).text()
            for i in range(self._custom_list.count())
        ]
        return tuple(checked_template + custom)

    def _on_select_all(self) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(True)

    def _on_select_none(self) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(False)

    def _on_add_custom(self) -> None:
        text = self._custom_input.text().strip()
        if not text:
            return
        existing = {
            self._custom_list.item(i).text() for i in range(self._custom_list.count())
        }
        if text in existing or text in self._template_items:
            self._custom_input.clear()
            return
        self._custom_list.addItem(QListWidgetItem(text))
        self._custom_input.clear()

    def _on_remove_custom(self) -> None:
        for row_idx in sorted(
            (self._custom_list.row(it) for it in self._custom_list.selectedItems()),
            reverse=True,
        ):
            self._custom_list.takeItem(row_idx)

    def _restore_preset(self) -> None:
        raw = self._container.settings.get(_preset_key(self._tax_type)) or ""
        if not raw:
            for cb in self._checkboxes.values():
                cb.setChecked(True)
            return
        try:
            data = json.loads(raw)
            checked = set(data.get("checked", []))
            custom = list(data.get("custom", []))
        except (ValueError, TypeError):
            _log.warning(
                "document_item_template_dialog: invalid preset JSON, falling back",
                exc_info=True,
            )
            for cb in self._checkboxes.values():
                cb.setChecked(True)
            return
        for name, cb in self._checkboxes.items():
            cb.setChecked(name in checked)
        for name in custom:
            self._custom_list.addItem(QListWidgetItem(name))

    def _persist(self) -> None:
        if not self._template_items:
            # No preset key registered for this tax_type — Slice 21A scope is
            # VAT only; other tax types' selections are not persisted.
            return
        checked = [
            name for name in self._template_items if self._checkboxes[name].isChecked()
        ]
        custom = [
            self._custom_list.item(i).text()
            for i in range(self._custom_list.count())
        ]
        data = json.dumps({"checked": checked, "custom": custom}, ensure_ascii=False)
        try:
            self._container.settings.set_setting(
                _preset_key(self._tax_type), data
            )
        except Exception:
            _log.warning(
                "document_item_template_dialog: failed to persist preset",
                exc_info=True,
            )

    def accept(self) -> None:  # override
        self._persist()
        super().accept()
