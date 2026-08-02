"""Create or edit the annual compliance profile required by annual work."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.compliance import (
    SUPPORTED_FREQUENCIES,
    WORK_TYPE_LABELS,
    WORK_TYPE_ORDER,
)
from ...services.compliance_profiles import (
    ComplianceProfileItemInput,
    ComplianceProfileValidationError,
)
from ...services.container import ServiceContainer


_FREQUENCY_LABELS = {
    "monthly": "每月",
    "bimonthly": "每兩月",
    "annual": "每年",
}
_DEFAULT_FREQUENCY = {
    work_type: (
        "bimonthly"
        if work_type == "vat"
        else sorted(frequencies)[0]
    )
    for work_type, frequencies in SUPPORTED_FREQUENCIES.items()
}
_DEFAULT_ENABLED = frozenset(
    work_type
    for work_type, frequency in _DEFAULT_FREQUENCY.items()
    if frequency == "annual"
)


class ComplianceProfileDialog(QDialog):
    """Visible entry point for the profile AnnualWorkService already requires."""

    def __init__(
        self,
        container: ServiceContainer,
        preselected_client_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self.setWindowTitle("年度法遵設定檔")
        self.setModal(True)
        self.resize(780, 560)
        self.setMinimumSize(680, 460)

        outer = QVBoxLayout(self)
        intro = QLabel(
            "這裡決定建立年度工作時要自動帶入哪些法遵項目。"
            "設定只影響之後建立的年度工作，不會改寫既有歷史紀錄。"
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        selector = QHBoxLayout()
        selector.addWidget(QLabel("客戶"))
        self.client_combo = QComboBox()
        self.client_combo.setMinimumWidth(300)
        selector.addWidget(self.client_combo, 1)
        selector.addWidget(QLabel("會計年度起始月"))
        self.fiscal_month_spin = QSpinBox()
        self.fiscal_month_spin.setRange(1, 12)
        self.fiscal_month_spin.setValue(1)
        selector.addWidget(self.fiscal_month_spin)
        outer.addLayout(selector)

        self.items_table = QTableWidget(0, 4)
        self.items_table.setHorizontalHeaderLabels(
            ["啟用", "年度工作類型", "頻率", "設定說明"]
        )
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.items_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.items_table.setColumnWidth(0, 56)
        self.items_table.setColumnWidth(2, 110)
        outer.addWidget(self.items_table, 1)

        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        outer.addWidget(self.feedback_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = QPushButton("取消")
        self.save_button = QPushButton("儲存設定檔")
        self.save_button.setDefault(True)
        actions.addWidget(cancel_button)
        actions.addWidget(self.save_button)
        outer.addLayout(actions)

        self._load_clients(preselected_client_id)
        self.client_combo.currentIndexChanged.connect(self._load_profile)
        self.save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)
        self._load_profile()

    def _load_clients(self, preselected_client_id: int | None) -> None:
        self.client_combo.clear()
        try:
            clients = self._container.clients.search_clients("", limit=500)
        except Exception:
            clients = []
        for client in clients:
            self.client_combo.addItem(
                f"{client.client_code}  {client.client_name}", client.id
            )
        if preselected_client_id is not None:
            index = self.client_combo.findData(preselected_client_id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)
        self.save_button.setEnabled(self.client_combo.currentData() is not None)

    def _load_profile(self, _index: int = -1) -> None:
        client_id = self.client_combo.currentData()
        existing = None
        if isinstance(client_id, int):
            try:
                existing = self._container.compliance_profiles.get_for_client(client_id)
            except Exception:
                self.feedback_label.setText("載入設定檔失敗，請重新整理後再試。")
        if existing is not None:
            self.fiscal_month_spin.setValue(
                existing.profile.fiscal_year_start_month
            )
            existing_by_type = {item.work_type: item for item in existing.items}
        else:
            self.fiscal_month_spin.setValue(1)
            existing_by_type = {}

        self.items_table.setRowCount(len(WORK_TYPE_ORDER))
        for row, work_type in enumerate(WORK_TYPE_ORDER):
            stored = existing_by_type.get(work_type)
            enabled = stored.enabled if stored is not None else work_type in _DEFAULT_ENABLED
            frequency = (
                stored.frequency if stored is not None else _DEFAULT_FREQUENCY[work_type]
            )
            enabled_box = QCheckBox()
            enabled_box.setChecked(enabled)
            enabled_box.setProperty("work_type", work_type)
            self.items_table.setCellWidget(row, 0, enabled_box)
            label_item = QTableWidgetItem(WORK_TYPE_LABELS[work_type])
            label_item.setData(Qt.ItemDataRole.UserRole, work_type)
            self.items_table.setItem(row, 1, label_item)
            frequency_combo = QComboBox()
            for value in sorted(SUPPORTED_FREQUENCIES[work_type]):
                frequency_combo.addItem(_FREQUENCY_LABELS[value], value)
            frequency_combo.setCurrentIndex(frequency_combo.findData(frequency))
            self.items_table.setCellWidget(row, 2, frequency_combo)
            self.items_table.setItem(
                row,
                3,
                QTableWidgetItem(stored.notes if stored and stored.notes else ""),
            )

    def _save(self) -> None:
        client_id = self.client_combo.currentData()
        if not isinstance(client_id, int):
            self.feedback_label.setText("請先選擇客戶。")
            return
        items: list[ComplianceProfileItemInput] = []
        for row in range(self.items_table.rowCount()):
            label_item = self.items_table.item(row, 1)
            enabled_box = self.items_table.cellWidget(row, 0)
            frequency_combo = self.items_table.cellWidget(row, 2)
            note_item = self.items_table.item(row, 3)
            if not (
                label_item is not None
                and isinstance(enabled_box, QCheckBox)
                and isinstance(frequency_combo, QComboBox)
            ):
                continue
            items.append(
                ComplianceProfileItemInput(
                    work_type=str(label_item.data(Qt.ItemDataRole.UserRole)),
                    frequency=str(frequency_combo.currentData()),
                    enabled=enabled_box.isChecked(),
                    notes=note_item.text() if note_item else None,
                )
            )
        if not any(item.enabled for item in items):
            self.feedback_label.setText("至少啟用一項年度工作，否則無法建立年度工作。")
            return
        self.save_button.setEnabled(False)
        try:
            self._container.compliance_profiles.upsert_profile(
                client_id,
                self.fiscal_month_spin.value(),
                items,
            )
        except ComplianceProfileValidationError:
            self.feedback_label.setText("設定內容驗證失敗，請檢查後再試。")
            self.save_button.setEnabled(True)
            return
        except Exception:
            QMessageBox.warning(self, "儲存失敗", "年度法遵設定檔未儲存，請稍後再試。")
            self.save_button.setEnabled(True)
            return
        self.accept()
