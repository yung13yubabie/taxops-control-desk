"""Bulk client import wizard — multi-step QDialog."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import DISABLED_TOOLTIP, error_message

_log = logging.getLogger(__name__)

_PASTE_TEMPLATE = (
    "客戶代號\t客戶名稱\t統一編號\t聯絡人\t聯絡電話\t地址\t備註\n"
    "A001\t測試公司甲\t12345678\t王小姐\t0912345678\t台北市中正區重慶南路一段\t第一筆\n"
    "A002\t測試公司乙\t87654321\t陳先生\t0922333444\t新北市板橋區文化路一段\t第二筆"
)
from ...repositories.clients import ClientsRepository
from ...services.clients import ClientsService
from ...services.clients_bulk import (
    BULK_FIELDS,
    BULK_FIELD_LABELS,
    BulkImportResult,
    BulkParseError,
    BulkValidationRow,
    DuplicatePolicy,
    RawRow,
    auto_detect_mapping,
    import_validated,
    parse_clipboard_text,
    parse_csv,
    parse_excel,
    validate_rows,
)

_STEP_TITLES = [
    "步驟 1：選擇匯入方式",
    "步驟 2：欄位對應",
    "步驟 3：資料驗證",
    "步驟 4：重複資料處理",
    "步驟 5：確認匯入",
    "步驟 6：匯入結果",
]

_UNMAPPED_LABEL = "（不匯入）"


class BulkImportWizard(QDialog):
    def __init__(
        self,
        clients_service: ClientsService,
        clients_repo: ClientsRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svc = clients_service
        self._repo = clients_repo
        self.setWindowTitle("批量匯入客戶名單")
        self.setModal(True)
        self.setMinimumSize(700, 600)
        self.resize(760, 640)

        self._headers: list[str] = []
        self._raw_rows: list[RawRow] = []
        self._mapping: dict[str, str] = {}
        self._validation: list[BulkValidationRow] = []
        self._dup_policy: DuplicatePolicy = "skip"
        self._result: BulkImportResult | None = None
        self._mapping_combos: dict[str, QComboBox] = {}
        self._step_history: list[int] = [0]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        self._title_label = QLabel(_STEP_TITLES[0])
        self._title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        outer.addWidget(self._title_label)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._stack.addWidget(self._build_step1())
        self._stack.addWidget(self._build_step2())
        self._stack.addWidget(self._build_step3())
        self._stack.addWidget(self._build_step4())
        self._stack.addWidget(self._build_step5())
        self._stack.addWidget(self._build_step6())

        nav = QHBoxLayout()
        self._back_btn = QPushButton("上一步")
        self._back_btn.setEnabled(False)
        self._next_btn = QPushButton("下一步")
        self._cancel_btn = QPushButton("取消")
        nav.addWidget(self._cancel_btn)
        nav.addStretch()
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)
        outer.addLayout(nav)

        self._back_btn.clicked.connect(self._go_back)
        self._next_btn.clicked.connect(self._go_next)
        self._cancel_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------
    # Step builders
    # ------------------------------------------------------------------

    def _build_step1(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(10)
        layout.setContentsMargins(4, 4, 4, 4)

        hint = QLabel(
            "每一列代表一位客戶。第一列必須是欄位名稱，第二列開始每列一筆客戶資料。\n\n"
            "必要欄位：客戶代號、客戶名稱\n"
            "可選欄位：統一編號、簡稱、聯絡人、聯絡電話、聯絡信箱、地址、備註"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 12px; padding: 4px 0;")
        layout.addWidget(hint)

        layout.addWidget(QLabel("請選擇資料來源："))

        self._rb_excel = QRadioButton("Excel 檔案 (.xlsx)")
        self._rb_csv = QRadioButton("CSV 檔案 (.csv)")
        self._rb_paste = QRadioButton("貼上表格文字（Tab 或逗號分隔）")
        self._rb_excel.setChecked(True)

        for rb in (self._rb_excel, self._rb_csv, self._rb_paste):
            layout.addWidget(rb)

        file_row = QHBoxLayout()
        self._file_path_label = QLabel("尚未選擇檔案")
        self._file_path_label.setWordWrap(True)
        browse_btn = QPushButton("選擇檔案…")
        browse_btn.clicked.connect(self._browse_file)
        file_row.addWidget(self._file_path_label, 1)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        layout.addWidget(QLabel("或貼上文字（選擇「貼上」時使用）："))
        self._paste_edit = QTextEdit()
        self._paste_edit.setFixedHeight(110)
        self._paste_edit.setPlaceholderText(
            "客戶代號\t客戶名稱\t統一編號\t聯絡人\t聯絡電話\t地址\t備註\n"
            "A001\t測試公司甲\t12345678\t王小姐\t0912345678\t台北市中正區...\t第一筆\n"
            "A002\t測試公司乙\t87654321\t陳先生\t0922333444\t新北市板橋區...\t第二筆"
        )
        layout.addWidget(self._paste_edit)

        tmpl_row = QHBoxLayout()
        self._copy_template_btn = QPushButton("複製貼上範本")
        self._copy_template_btn.clicked.connect(self._copy_paste_template)
        self._download_xlsx_btn = QPushButton("下載 Excel 範本")
        self._download_xlsx_btn.setEnabled(False)
        self._download_xlsx_btn.setToolTip(DISABLED_TOOLTIP)
        tmpl_row.addWidget(self._copy_template_btn)
        tmpl_row.addWidget(self._download_xlsx_btn)
        tmpl_row.addStretch()
        layout.addLayout(tmpl_row)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _copy_paste_template(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(_PASTE_TEMPLATE)
        QMessageBox.information(
            self,
            "已複製範本",
            "範本已複製到剪貼簿。\n\n"
            "請開啟試算表（Excel / Google Sheets）後貼上，\n"
            "填入實際資料，再複製回此欄位。",
        )

    def _build_step2(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("請確認或調整欄位對應（系統已自動偵測）："))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._mapping_form = QFormLayout(inner)
        self._mapping_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        return w

    def _build_step3(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("資料驗證結果（紅色為錯誤，橘色為警告）："))
        self._validation_table = QTableWidget()
        self._validation_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._validation_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._validation_table)
        self._validation_summary = QLabel()
        layout.addWidget(self._validation_summary)
        return w

    def _build_step4(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("偵測到重複的客戶代號，請選擇處理方式："))
        self._rb_skip = QRadioButton("略過重複資料（保留原有客戶資料）")
        self._rb_overwrite = QRadioButton("覆蓋重複資料（以匯入資料更新客戶）")
        self._rb_skip.setChecked(True)
        layout.addWidget(self._rb_skip)
        layout.addWidget(self._rb_overwrite)
        self._dup_detail = QLabel()
        self._dup_detail.setWordWrap(True)
        layout.addWidget(self._dup_detail)
        layout.addStretch()
        return w

    def _build_step5(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("確認後將開始寫入資料庫，請確認以下資訊："))
        self._confirm_label = QLabel()
        self._confirm_label.setWordWrap(True)
        layout.addWidget(self._confirm_label)
        layout.addStretch()
        return w

    def _build_step6(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("匯入完成！"))
        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._result_label)
        layout.addStretch()
        return w

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _current_step(self) -> int:
        return self._stack.currentIndex()

    def _go_next(self) -> None:
        step = self._current_step()

        if step == 0:
            if not self._load_data():
                return
            self._populate_mapping_form()
        elif step == 1:
            self._collect_mapping()
            self._run_validation()
            self._populate_validation_table()
        elif step == 2:
            dup_rows = [r for r in self._validation if r.is_duplicate_code]
            if not dup_rows:
                self._dup_policy = "skip"
                # jump past step 4
                self._jump_to(4)
                return
            self._populate_dup_step()
        elif step == 3:
            self._dup_policy = "overwrite" if self._rb_overwrite.isChecked() else "skip"
            self._populate_confirm()
        elif step == 4:
            self._run_import()
        elif step == 5:
            self.accept()
            return

        self._advance_to(step + 1)

    def _go_back(self) -> None:
        if len(self._step_history) <= 1:
            return
        self._step_history.pop()
        prev = self._step_history[-1]
        self._stack.setCurrentIndex(prev)
        self._title_label.setText(_STEP_TITLES[prev])
        self._back_btn.setEnabled(len(self._step_history) > 1)
        self._next_btn.setText("完成" if prev == 5 else "下一步")

    def _advance_to(self, idx: int) -> None:
        self._step_history.append(idx)
        self._stack.setCurrentIndex(idx)
        self._title_label.setText(_STEP_TITLES[idx])
        self._back_btn.setEnabled(len(self._step_history) > 1)
        self._next_btn.setText("完成" if idx == 5 else "下一步")

    def _jump_to(self, idx: int) -> None:
        self._populate_confirm()
        self._advance_to(idx)

    # ------------------------------------------------------------------
    # Step logic
    # ------------------------------------------------------------------

    def _browse_file(self) -> None:
        if self._rb_excel.isChecked():
            f, _ = QFileDialog.getOpenFileName(self, "選擇 Excel 檔案", "", "Excel (*.xlsx)")
        else:
            f, _ = QFileDialog.getOpenFileName(self, "選擇 CSV 檔案", "", "CSV (*.csv)")
        if f:
            self._file_path_label.setText(f)

    def _load_data(self) -> bool:
        try:
            if self._rb_paste.isChecked():
                text = self._paste_edit.toPlainText()
                self._headers, self._raw_rows = parse_clipboard_text(text)
            elif self._rb_excel.isChecked():
                path_str = self._file_path_label.text()
                if path_str == "尚未選擇檔案":
                    QMessageBox.warning(self, "未選擇檔案", "請先選擇 Excel 檔案。")
                    return False
                self._headers, self._raw_rows = parse_excel(Path(path_str))
            else:
                path_str = self._file_path_label.text()
                if path_str == "尚未選擇檔案":
                    QMessageBox.warning(self, "未選擇檔案", "請先選擇 CSV 檔案。")
                    return False
                self._headers, self._raw_rows = parse_csv(Path(path_str))
        except BulkParseError as exc:
            QMessageBox.warning(self, "讀取失敗", error_message(exc.code))
            return False
        return True

    def _populate_mapping_form(self) -> None:
        while self._mapping_form.rowCount():
            self._mapping_form.removeRow(0)
        self._mapping_combos.clear()

        detected = auto_detect_mapping(self._headers)
        options = [_UNMAPPED_LABEL] + [BULK_FIELD_LABELS[f] for f in BULK_FIELDS]

        for header in self._headers:
            combo = QComboBox()
            combo.addItems(options)
            canonical = detected.get(header)
            if canonical and canonical in BULK_FIELDS:
                combo.setCurrentIndex(BULK_FIELDS.index(canonical) + 1)
            self._mapping_form.addRow(QLabel(header), combo)
            self._mapping_combos[header] = combo

    def _collect_mapping(self) -> None:
        self._mapping = {}
        label_to_field = {v: k for k, v in BULK_FIELD_LABELS.items()}
        for header, combo in self._mapping_combos.items():
            label = combo.currentText()
            if label != _UNMAPPED_LABEL:
                canonical = label_to_field.get(label)
                if canonical:
                    self._mapping[header] = canonical

    def _run_validation(self) -> None:
        self._validation = validate_rows(self._raw_rows, self._mapping, self._repo)

    def _populate_validation_table(self) -> None:
        t = self._validation_table
        t.clear()
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels(["列號", "客戶代號", "客戶名稱", "狀態"])
        t.setRowCount(len(self._validation))

        valid_count = sum(
            1 for r in self._validation if r.is_valid and not r.is_duplicate_code
        )
        dup_count = sum(1 for r in self._validation if r.is_duplicate_code)
        error_count = sum(1 for r in self._validation if not r.is_valid)

        for i, vrow in enumerate(self._validation):
            t.setItem(i, 0, QTableWidgetItem(str(vrow.row_number)))
            t.setItem(i, 1, QTableWidgetItem(vrow.mapped.get("client_code", "")))
            t.setItem(i, 2, QTableWidgetItem(vrow.mapped.get("client_name", "")))

            if not vrow.is_valid:
                item = QTableWidgetItem("錯誤：" + "；".join(vrow.errors))
                item.setForeground(Qt.GlobalColor.red)
            elif vrow.is_duplicate_code or vrow.is_duplicate_tax_id:
                item = QTableWidgetItem("警告：" + "；".join(vrow.warnings))
                item.setForeground(Qt.GlobalColor.darkYellow)
            else:
                item = QTableWidgetItem("正常")
            t.setItem(i, 3, item)

        t.resizeColumnsToContents()
        self._validation_summary.setText(
            f"共 {len(self._validation)} 筆：正常 {valid_count} 筆，"
            f"重複 {dup_count} 筆，錯誤 {error_count} 筆"
        )

    def _populate_dup_step(self) -> None:
        dup_rows = [r for r in self._validation if r.is_duplicate_code]
        codes = "、".join(r.mapped.get("client_code", "?") for r in dup_rows[:10])
        if len(dup_rows) > 10:
            codes += f" 等共 {len(dup_rows)} 筆"
        self._dup_detail.setText(f"重複客戶代號：{codes}")

    def _populate_confirm(self) -> None:
        valid = [r for r in self._validation if r.is_valid]
        new_rows = [r for r in valid if not r.is_duplicate_code]
        dup_rows = [r for r in valid if r.is_duplicate_code]
        error_count = sum(1 for r in self._validation if not r.is_valid)

        dup_note = (
            f"重複 {len(dup_rows)} 筆將被覆蓋"
            if self._dup_policy == "overwrite"
            else f"重複 {len(dup_rows)} 筆將被略過"
        )
        self._confirm_label.setText(
            f"即將寫入：{len(new_rows)} 筆新客戶\n"
            f"{dup_note}\n"
            f"錯誤跳過：{error_count} 筆\n\n"
            "按「下一步」確認寫入資料庫。"
        )

    def _run_import(self) -> None:
        self._next_btn.setEnabled(False)
        try:
            self._result = import_validated(
                self._validation,
                self._svc,
                on_duplicate_code=self._dup_policy,
            )
        except BulkParseError as exc:
            _log.error("bulk import failed: code=%s detail=%s", exc.code, exc.detail)
            QMessageBox.critical(self, "匯入失敗", error_message(exc.code))
            self._next_btn.setEnabled(True)
            return
        except Exception as exc:
            _log.error("bulk import unexpected error: %s", exc, exc_info=True)
            QMessageBox.critical(self, "匯入失敗", error_message("system.unexpected"))
            self._next_btn.setEnabled(True)
            return
        finally:
            self._next_btn.setEnabled(True)

        r = self._result
        lines = [
            f"總計：{r.total} 筆",
            f"成功匯入：{r.imported} 筆",
            f"覆蓋更新：{r.overwritten} 筆",
            f"略過：{r.skipped} 筆",
        ]
        if r.errors:
            lines.append("\n寫入失敗的筆數：")
            for row_num, code in r.errors[:20]:
                lines.append(f"  第 {row_num} 列：{error_message(code)}")
        self._result_label.setText("\n".join(lines))
        self._cancel_btn.setText("關閉")
