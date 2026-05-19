"""Review notes page: per-engagement review comments with status transitions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import error_message
from ...i18n.status_labels import REVIEW_NOTE_STATUS_LABELS, SEVERITY_LABELS
from ...services.container import ServiceContainer
from ...services.review_notes import (
    CreateReviewNoteInput,
    ReviewNoteValidationError,
    UpdateReviewNoteStatusInput,
)
from ..action_registry import FilterKey
from ..style import DANGER_COLOR, toolbar_icon

_COLUMN_ORDER = ("id", "severity", "status", "comment", "assigned_to", "updated_at")
_TABLE_HEADERS = {
    "id": "編號",
    "severity": "嚴重性",
    "status": "狀態",
    "comment": "意見內容",
    "assigned_to": "負責人",
    "updated_at": "更新時間",
}
_ALL_ENGAGEMENTS = -1


class _NewNoteDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增覆核意見")
        self.setMinimumWidth(460)

        form = QFormLayout(self)
        form.setSpacing(10)

        self._severity_combo = QComboBox()
        for key, label in SEVERITY_LABELS.items():
            self._severity_combo.addItem(label, key)
        form.addRow("嚴重性：", self._severity_combo)

        self._comment_edit = QTextEdit()
        self._comment_edit.setFixedHeight(100)
        self._comment_edit.setPlaceholderText("請輸入覆核意見…")
        form.addRow("意見：", self._comment_edit)

        self._assigned_edit = QLineEdit()
        self._assigned_edit.setPlaceholderText("留空表示未指定")
        form.addRow("負責人：", self._assigned_edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def severity(self) -> str:
        return self._severity_combo.currentData()

    def comment(self) -> str:
        return self._comment_edit.toPlainText().strip()

    def assigned_to(self) -> str | None:
        val = self._assigned_edit.text().strip()
        return val if val else None


class _RespondDialog(QDialog):
    def __init__(self, action: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(action)
        self.setMinimumWidth(420)

        form = QFormLayout(self)
        form.setSpacing(10)

        self._text_edit = QTextEdit()
        self._text_edit.setFixedHeight(80)
        self._text_edit.setPlaceholderText("請輸入說明…")
        form.addRow("說明：", self._text_edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def text(self) -> str:
        return self._text_edit.toPlainText().strip()


class ReviewNotesPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._notes: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title = QLabel("覆核意見")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("案件："))
        self._eng_combo = QComboBox()
        self._eng_combo.setMinimumWidth(220)
        filter_row.addWidget(self._eng_combo)
        filter_row.addStretch()

        self._refresh_btn = QPushButton("重新整理")
        self._refresh_btn.setIcon(toolbar_icon("refresh"))
        self._refresh_btn.clicked.connect(self._load)
        filter_row.addWidget(self._refresh_btn)

        self._new_btn = QPushButton("新增覆核意見")
        self._new_btn.setIcon(toolbar_icon("new"))
        self._new_btn.clicked.connect(self._on_new)
        filter_row.addWidget(self._new_btn)

        outer.addLayout(filter_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        action_row.addStretch()

        self._respond_btn = QPushButton("回覆")
        self._respond_btn.setIcon(toolbar_icon("trial"))
        self._respond_btn.clicked.connect(self._on_respond)
        action_row.addWidget(self._respond_btn)

        self._resolve_btn = QPushButton("解決")
        self._resolve_btn.setIcon(toolbar_icon("complete"))
        self._resolve_btn.clicked.connect(self._on_resolve)
        action_row.addWidget(self._resolve_btn)

        self._waive_btn = QPushButton("豁免")
        self._waive_btn.setIcon(toolbar_icon("save"))
        self._waive_btn.clicked.connect(self._on_waive)
        action_row.addWidget(self._waive_btn)

        self._reopen_btn = QPushButton("重新開啟")
        self._reopen_btn.setIcon(toolbar_icon("refresh"))
        self._reopen_btn.clicked.connect(self._on_reopen)
        action_row.addWidget(self._reopen_btn)

        outer.addLayout(action_row)

        self._table = QTableWidget(0, len(_COLUMN_ORDER))
        self._table.setHorizontalHeaderLabels(
            [_TABLE_HEADERS[c] for c in _COLUMN_ORDER]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        outer.addWidget(self._table)

        self._error_label = QLabel("載入覆核意見失敗，請重新整理或重新啟動程式")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setObjectName("ErrorState")
        self._error_label.setStyleSheet(f"color: {DANGER_COLOR};")
        self._error_label.hide()
        outer.addWidget(self._error_label)

        self._filter_key: str = ""
        self._eng_combo.currentIndexChanged.connect(self._load)
        self._load_engagements()

    # ------------------------------------------------------------------
    # Public filter API (called by MainWindow on dashboard navigation)

    def set_filter(self, filter_key: str) -> None:
        self._filter_key = filter_key
        self._load()

    # ------------------------------------------------------------------

    def _load_engagements(self) -> None:
        self._eng_combo.blockSignals(True)
        self._eng_combo.clear()
        self._eng_combo.addItem("（全部案件）", _ALL_ENGAGEMENTS)
        try:
            for eng in self._container.engagements.list_all():
                self._eng_combo.addItem(eng.engagement_name, eng.id)
        except Exception as exc:
            self._container.system_log.warn(
                "review_notes_page: failed to load engagements",
                detail={"exc": type(exc).__name__, "msg": str(exc)},
            )
            self._eng_combo.addItem("（載入案件失敗）", _ALL_ENGAGEMENTS)
        self._eng_combo.blockSignals(False)
        self._load()

    def _load(self) -> None:
        self._notes = []
        load_error = False
        try:
            if self._filter_key == FilterKey.OPEN:
                self._notes = self._container.review_notes.list_open_all()
            elif self._filter_key == FilterKey.HIGH_RISK:
                self._notes = self._container.review_notes.list_high_risk_all()
            else:
                eng_id = self._eng_combo.currentData()
                if eng_id == _ALL_ENGAGEMENTS:
                    for eng in self._container.engagements.list_all():
                        self._notes.extend(
                            self._container.review_notes.list_by_engagement(eng.id)
                        )
                else:
                    self._notes = self._container.review_notes.list_by_engagement(eng_id)
        except Exception as exc:
            self._container.system_log.warn(
                "review_notes_page: failed to load notes",
                detail={"exc": type(exc).__name__, "msg": str(exc)},
            )
            load_error = True
        self._error_label.setVisible(load_error)
        self._render_table()

    def _render_table(self) -> None:
        self._table.setRowCount(0)
        for note in self._notes:
            row = self._table.rowCount()
            self._table.insertRow(row)
            vals = {
                "id": str(note.id),
                "severity": SEVERITY_LABELS.get(note.severity, note.severity),
                "status": REVIEW_NOTE_STATUS_LABELS.get(note.status, note.status),
                "comment": note.comment,
                "assigned_to": note.assigned_to or "",
                "updated_at": note.updated_at,
            }
            for col, key in enumerate(_COLUMN_ORDER):
                self._table.setItem(row, col, QTableWidgetItem(vals[key]))

    def _selected_note(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._notes):
            return None
        return self._notes[row]

    def _on_new(self) -> None:
        eng_id = self._eng_combo.currentData()
        if eng_id == _ALL_ENGAGEMENTS:
            QMessageBox.warning(self, "提示", "請先選擇一個案件再新增覆核意見")
            return
        dlg = _NewNoteDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._container.review_notes.create(
                CreateReviewNoteInput(
                    engagement_id=eng_id,
                    severity=dlg.severity(),
                    comment=dlg.comment(),
                    assigned_to=dlg.assigned_to(),
                )
            )
        except ReviewNoteValidationError as err:
            QMessageBox.critical(self, "新增失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "新增失敗", error_message("review_note.create.failed"))
            return
        self._load()

    def _transition(self, new_status: str, action_label: str) -> None:
        note = self._selected_note()
        if note is None:
            QMessageBox.warning(self, "提示", "請先選擇一筆覆核意見")
            return
        dlg = _RespondDialog(action_label, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.text()
        try:
            self._container.review_notes.update_status(
                UpdateReviewNoteStatusInput(
                    note_id=note.id,
                    new_status=new_status,
                    response=text if new_status not in ("waived", "reopened") else None,
                    waive_reason=text if new_status == "waived" else None,
                )
            )
        except ReviewNoteValidationError as err:
            QMessageBox.critical(self, "操作失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "操作失敗", error_message("review_note.update.failed"))
            return
        self._load()

    def _on_respond(self) -> None:
        self._transition("responded", "回覆覆核意見")

    def _on_resolve(self) -> None:
        self._transition("resolved", "標記已解決")

    def _on_waive(self) -> None:
        self._transition("waived", "豁免覆核意見")

    def _on_reopen(self) -> None:
        self._transition("reopened", "重新開啟覆核意見")
