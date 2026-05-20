"""Settings page.

Slice 2 enables five tax-cache offline workflow buttons:
  - 從 ZIP 匯入稅籍資料
  - 匯入稅籍快取包
  - 匯出稅籍快取包
  - 驗證快取
  - 重新產生客戶對照結果

HTTP download (下載財政部稅籍資料) and GCIS query remain disabled (Slice 3).

Threading note: _RegistryWorker opens its own SQLite connection in the
background thread rather than reusing the UI container's connection.  SQLite
connections may not cross thread boundaries (ProgrammingError if attempted).
Each worker opens → apply_migrations → build_container → closes on finish.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Any

_log = logging.getLogger(__name__)

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.paths import AppPaths
from ...db.connection import open_connection
from ...db.migrate import apply_migrations
from ...i18n import BUTTON_LABELS, DISABLED_TOOLTIP, NAV_LABELS, error_message
from ...repositories.app_settings import VALID_QUERY_MODES
from ...security.domains import is_allowed_official_url
from ...services.container import ServiceContainer, build_container
from ...services.registry.bundle import BundleError, suggested_bundle_filename
from ...services.registry.importer import TaxRegistryImportError
from ...services.registry.status import get_cache_status, verify_cache
from ...services.registry_download import DownloadError, download_registry_zip
from ...services.backup import BackupError
from ...services.settings import SettingsValidationError
from ..dialogs.mismatch_review_dialog import MismatchItem, MismatchReviewDialog
from ..action_registry import PAGE_SETTINGS, actions_for_page

_QUERY_MODE_LABELS = {
    "local_only": "僅使用本機快取",
    "allow_online": "允許線上下載更新",
}


def _middle_elide(text: str, max_chars: int = 60) -> str:
    if len(text) <= max_chars:
        return text
    half = (max_chars - 3) // 2
    return text[:half] + "..." + text[-half:]


class _RegistryWorker(QThread):
    """Background thread for potentially slow registry operations.

    Opens a *fresh* SQLite connection in the worker thread so it never
    touches the UI thread's connection.  The container (and connection) is
    closed when the thread finishes.
    """

    finished = Signal(object)
    errored = Signal(str)

    def __init__(
        self,
        paths: AppPaths,
        task_fn: Callable[[ServiceContainer], Any],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self._task_fn = task_fn

    def run(self) -> None:
        conn = None
        container: ServiceContainer | None = None
        try:
            conn = open_connection(self._paths.db_path)
            apply_migrations(conn)
            container = build_container(self._paths, conn)
            conn = None  # container now owns the connection
            result = self._task_fn(container)
            self.finished.emit(result)
        except (TaxRegistryImportError, BundleError, DownloadError) as exc:
            self.errored.emit(exc.code)
        except Exception:
            self.errored.emit("system.unexpected")
        finally:
            if container is not None:
                container.close()
            elif conn is not None:
                conn.close()


class SettingsPage(QWidget):
    def __init__(
        self,
        container: ServiceContainer,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._active_worker: _RegistryWorker | None = None
        self._slice2_buttons: list[QPushButton] = []
        self._download_btn: QPushButton | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel(NAV_LABELS["settings"])
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, stretch=1)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(16)

        body_layout.addWidget(self._build_paths_group())
        body_layout.addWidget(self._build_user_group())
        body_layout.addWidget(self._build_tax_cache_group())
        body_layout.addWidget(self._build_backup_group())
        body_layout.addStretch(1)

        scroll.setWidget(body)

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def _build_paths_group(self) -> QGroupBox:
        paths = self._container.paths
        group = QGroupBox("資料路徑")
        form = QFormLayout(group)

        form.addRow(
            QLabel("資料庫路徑"),
            self._path_row(
                paths.db_path,
                BUTTON_LABELS["settings.open_data_folder"],
                BUTTON_LABELS["settings.copy_db_path"],
                self.on_open_data_folder,
                self.on_copy_db_path,
            ),
        )
        form.addRow(
            QLabel("附件資料夾"),
            self._path_row(
                paths.attachments_dir,
                BUTTON_LABELS["settings.open_attachments_folder"],
                BUTTON_LABELS["settings.copy_attachments_path"],
                self.on_open_attachments_folder,
                self.on_copy_attachments_path,
            ),
        )
        form.addRow(QLabel("備份資料夾"), self._readonly_path(paths.backups_dir))
        return group

    def _build_user_group(self) -> QGroupBox:
        group = QGroupBox("操作者")
        form = QFormLayout(group)

        self._display_name = QLineEdit(
            self._container.settings.get("display.local_user_name") or "local_user"
        )
        self._display_name.setMaxLength(100)
        save_btn = QPushButton(BUTTON_LABELS["settings.save_display_name"])
        save_btn.clicked.connect(self.on_save_display_name)

        row = QHBoxLayout()
        row.addWidget(self._display_name, stretch=1)
        row.addWidget(save_btn)
        wrapper = QWidget()
        wrapper.setLayout(row)
        form.addRow(QLabel("顯示名稱"), wrapper)
        return group

    def _build_tax_cache_group(self) -> QGroupBox:
        group = QGroupBox("稅籍快取管理")
        layout = QVBoxLayout(group)
        layout.setSpacing(12)

        # --- Query mode + URL settings ---
        form = QFormLayout()

        self._query_mode = QComboBox()
        for mode in VALID_QUERY_MODES:
            self._query_mode.addItem(_QUERY_MODE_LABELS[mode], userData=mode)
        current_mode = (
            self._container.settings.get("tax_cache.query_mode") or "local_only"
        )
        idx = self._query_mode.findData(current_mode)
        if idx >= 0:
            self._query_mode.setCurrentIndex(idx)
        save_mode_btn = QPushButton(BUTTON_LABELS["settings.save_query_mode"])
        save_mode_btn.clicked.connect(self.on_save_query_mode)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self._query_mode, stretch=1)
        mode_row.addWidget(save_mode_btn)
        mode_wrap = QWidget()
        mode_wrap.setLayout(mode_row)
        form.addRow(QLabel("查詢模式"), mode_wrap)

        for label, key in (
            ("財政部資料集頁 URL", "tax_cache.dataset_url"),
            ("財政部下載 URL", "tax_cache.download_url"),
            ("GCIS Swagger URL", "tax_cache.gcis_swagger_url"),
        ):
            value_label = QLabel(self._container.settings.get(key) or "")
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            form.addRow(QLabel(label), value_label)

        layout.addLayout(form)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep1)

        # --- Cache status display ---
        self._cache_status_label = QLabel()
        self._cache_status_label.setStyleSheet("color: #444; font-size: 13px;")
        self._cache_status_label.setWordWrap(True)
        layout.addWidget(self._cache_status_label)
        self._refresh_cache_status()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        # --- Enabled offline action buttons (slice 2 + slice 3 download) ---
        enabled_specs = [
            (BUTTON_LABELS["tax_cache.import_zip"], self.on_import_zip),
            (BUTTON_LABELS["tax_cache.import_bundle"], self.on_import_bundle),
            (BUTTON_LABELS["tax_cache.export_bundle"], self.on_export_bundle),
            (BUTTON_LABELS["tax_cache.verify"], self.on_verify_cache),
            (BUTTON_LABELS["tax_cache.regenerate_matches"], self.on_regenerate_matches),
        ]

        enabled_row = QHBoxLayout()
        enabled_row.setSpacing(8)
        for btn_label, handler in enabled_specs:
            btn = QPushButton(btn_label)
            btn.clicked.connect(handler)
            enabled_row.addWidget(btn)
            self._slice2_buttons.append(btn)
        enabled_row.addStretch(1)
        layout.addLayout(enabled_row)

        # Download button on its own row (slice 3)
        download_row = QHBoxLayout()
        download_row.setSpacing(8)
        self._download_btn = QPushButton("下載財政部稅籍資料")
        self._download_btn.clicked.connect(self.on_download_registry)
        download_row.addWidget(self._download_btn)
        download_row.addStretch(1)
        layout.addLayout(download_row)

        # --- Disabled buttons (future slices) ---
        disabled_rows = [a for a in actions_for_page(PAGE_SETTINGS) if not a.enabled]
        if disabled_rows:
            sep3 = QFrame()
            sep3.setFrameShape(QFrame.Shape.HLine)
            layout.addWidget(sep3)

            disabled_notice = QLabel("下列動作尚未開放：")
            disabled_notice.setStyleSheet("color: #555;")
            layout.addWidget(disabled_notice)

            disabled_row = QHBoxLayout()
            disabled_row.setSpacing(8)
            for action in disabled_rows:
                btn = QPushButton(action.button_label)
                btn.setEnabled(False)
                btn.setToolTip(DISABLED_TOOLTIP)
                disabled_row.addWidget(btn)
            disabled_row.addStretch(1)
            layout.addLayout(disabled_row)

        return group

    def _refresh_cache_status(self) -> None:
        try:
            status = get_cache_status(
                self._container.tax_registry_repo,
                self._container.tax_cache_metadata_repo,
            )
            if status.has_cache:
                text = (
                    f"快取版本：{status.cache_version or '未知'}  │  "
                    f"筆數：{status.row_count:,}  │  "
                    f"資料日期：{status.data_freshness_iso or '未知'}  │  "
                    f"來源：{status.last_import_source or '未知'}"
                )
            else:
                text = "尚無快取資料，請先匯入財政部 ZIP 或快取包。"
        except Exception:
            _log.warning("_refresh_cache_status: failed to read cache status", exc_info=True)
            text = "無法取得快取狀態。"
        self._cache_status_label.setText(text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _path_row(
        self,
        path: Path,
        open_label: str,
        copy_label: str,
        open_handler,
        copy_handler,
    ) -> QWidget:
        text = str(path)
        elided = _middle_elide(text)
        label = QLabel(elided)
        label.setToolTip(text)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        open_btn = QPushButton(open_label)
        open_btn.clicked.connect(open_handler)
        copy_btn = QPushButton(copy_label)
        copy_btn.clicked.connect(copy_handler)
        row = QHBoxLayout()
        row.addWidget(label, stretch=1)
        row.addWidget(open_btn)
        row.addWidget(copy_btn)
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    def _readonly_path(self, path: Path) -> QWidget:
        label = QLabel(_middle_elide(str(path)))
        label.setToolTip(str(path))
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        return label

    def _set_slice2_buttons_enabled(self, enabled: bool) -> None:
        for btn in self._slice2_buttons:
            btn.setEnabled(enabled)
        if self._download_btn is not None:
            self._download_btn.setEnabled(enabled)

    def _run_async(
        self,
        task_fn: Callable[[ServiceContainer], Any],
        title: str,
        on_success: Callable[[Any], None],
    ) -> None:
        """Run *task_fn(container)* in a background thread.

        The worker opens its own connection so there is no cross-thread SQLite
        access.  Slice-2 buttons are disabled for the duration.
        """
        if self._active_worker is not None and self._active_worker.isRunning():
            QMessageBox.warning(self, "操作進行中", "請等待目前操作完成後再試")
            return

        self._set_slice2_buttons_enabled(False)

        progress = QProgressDialog(title, None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(300)
        progress.show()

        worker = _RegistryWorker(self._container.paths, task_fn, parent=self)
        self._active_worker = worker

        def _on_finished(result: Any) -> None:
            progress.close()
            self._active_worker = None
            self._set_slice2_buttons_enabled(True)
            self._refresh_cache_status()
            on_success(result)
            worker.deleteLater()

        def _on_errored(code: str) -> None:
            progress.close()
            self._active_worker = None
            self._set_slice2_buttons_enabled(True)
            QMessageBox.warning(self, "操作失敗", error_message(code))

            worker.deleteLater()

        worker.finished.connect(_on_finished)
        worker.errored.connect(_on_errored)
        worker.start()

    # ------------------------------------------------------------------
    # Tax cache slice 2 actions
    # ------------------------------------------------------------------
    def on_import_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇財政部稅籍資料", "", "ZIP 檔案 (*.zip)"
        )
        if not path:
            return
        reply = QMessageBox.question(
            self,
            "確認匯入",
            f"確定要匯入以下稅籍資料？\n\n{path}\n\n匯入將覆蓋現有快取，此操作無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        zip_path = Path(path)

        def _do(container: ServiceContainer):
            return container.tax_cache_importer.import_zip(zip_path)

        self._run_async(
            _do,
            "匯入稅籍資料中，請稍候...",
            on_success=lambda r: QMessageBox.information(
                self,
                "匯入完成",
                f"已成功匯入 {r.row_count:,} 筆稅籍資料。\n"
                f"版本：{r.cache_version}\n"
                f"資料日期：{r.data_freshness_iso or '未知'}",
            ),
        )

    def on_import_bundle(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇稅籍快取包",
            "",
            "稅籍快取包 (*.taxops-cache.zip *.zip)",
        )
        if not path:
            return
        reply = QMessageBox.question(
            self,
            "確認匯入",
            f"確定要匯入快取包？\n\n{path}\n\n匯入成功後將覆蓋現有快取。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        bundle_path = Path(path)

        def _do(container: ServiceContainer):
            return container.tax_cache_bundle.import_bundle(bundle_path)

        self._run_async(
            _do,
            "匯入快取包中，請稍候...",
            on_success=lambda r: QMessageBox.information(
                self,
                "匯入完成",
                f"已成功匯入 {r.row_count:,} 筆稅籍資料。\n"
                f"版本：{r.cache_version}\n"
                f"資料日期：{r.data_freshness_iso or '未知'}",
            ),
        )

    def on_export_bundle(self) -> None:
        meta = self._container.tax_cache_metadata_repo.get_all()
        default_name = suggested_bundle_filename(meta.get("cache_version"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            "匯出稅籍快取包",
            str(self._container.paths.data_root / default_name),
            "稅籍快取包 (*.taxops-cache.zip)",
        )
        if not path:
            return

        dest_path = Path(path)

        def _do(container: ServiceContainer):
            return container.tax_cache_bundle.export_bundle(dest_path)

        self._run_async(
            _do,
            "匯出快取包中，請稍候...",
            on_success=lambda r: QMessageBox.information(
                self,
                "匯出完成",
                f"已成功匯出 {r.row_count:,} 筆稅籍資料。\n路徑：{r.bundle_path}",
            ),
        )

    def on_verify_cache(self) -> None:
        try:
            result = verify_cache(
                self._container.tax_registry_repo,
                self._container.tax_cache_metadata_repo,
                self._container.audit,
            )
        except Exception as exc:
            self._container.system_log.error("verify cache failed", exc=exc)
            QMessageBox.warning(self, "驗證失敗", error_message("system.unexpected"))
            return

        status_text = (
            "✓ 快取完整"
            if result.row_count_matches
            else "⚠ 快取筆數與紀錄不符，建議重新匯入"
        )
        QMessageBox.information(
            self,
            "驗證快取結果",
            f"{status_text}\n\n"
            f"版本：{result.cache_version or '無'}\n"
            f"記錄筆數：{result.metadata_row_count if result.metadata_row_count is not None else '無'}\n"
            f"實際筆數：{result.actual_row_count:,}\n"
            f"資料日期：{result.data_freshness_iso or '未知'}\n"
            f"來源：{result.last_import_source or '未知'}",
        )

    def on_regenerate_matches(self) -> None:
        reply = QMessageBox.question(
            self,
            "確認重新產生",
            "確定要重新產生客戶對照結果？\n\n將清除並重算所有客戶的統一編號比對結果，並寫入稽核紀錄。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def _do(container: ServiceContainer):
            return container.tax_cache_matcher.regenerate_mof()

        def _show_result(summary) -> None:
            hist = summary.histogram
            mismatch_count = hist.get("mismatch", 0)
            QMessageBox.information(
                self,
                "重新產生完成",
                f"已處理 {summary.client_count} 位客戶。\n\n"
                f"完全比對：{hist.get('matched', 0)}\n"
                f"名稱不符：{mismatch_count}\n"
                f"快取查無：{hist.get('not_found', 0)}\n"
                f"需人工確認：{hist.get('needs_manual_review', 0)}",
            )
            if mismatch_count > 0:
                reply = QMessageBox.question(
                    self,
                    "發現名稱不符",
                    f"有 {mismatch_count} 筆客戶名稱與財政部稅籍資料不符。\n"
                    "要開啟衝突審查視窗，選擇是否採用財政部資料嗎？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    pairs = self._container.tax_cache_matcher.list_mismatches()
                    items = [MismatchItem(match_row=m, client=c) for m, c in pairs]
                    if items:
                        dlg = MismatchReviewDialog(items, self._container.clients, parent=self)
                        dlg.exec()

        self._run_async(
            _do,
            "重新產生客戶對照結果中，請稍候...",
            on_success=_show_result,
        )

    def on_download_registry(self) -> None:
        url = self._container.settings.get("tax_cache.download_url") or ""

        # Pre-flight: URL must pass the official-domain allowlist
        if not is_allowed_official_url(url):
            QMessageBox.warning(
                self,
                "下載失敗",
                error_message("registry.download.not_allowed"),
            )
            return

        # Step 1: Confirm the download source URL
        reply1 = QMessageBox.question(
            self,
            "確認下載來源",
            f"即將從以下官方網址下載財政部稅籍資料：\n\n{url}\n\n"
            "請確認此為正確的官方財政部網址，然後按「是」繼續。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply1 != QMessageBox.StandardButton.Yes:
            return

        # Step 2: Confirm cache overwrite
        reply2 = QMessageBox.question(
            self,
            "確認覆蓋快取",
            "下載完成後將自動匯入並覆蓋現有快取。\n\n此操作無法復原，確定繼續嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return

        tmp_path = self._container.paths.data_root / "_registry_download_tmp.zip"

        def _do(container: ServiceContainer):
            try:
                download_registry_zip(url, tmp_path)
                result = container.tax_cache_importer.import_zip(tmp_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            container.audit.record(
                action="tax_cache.download",
                target_type="tax_cache",
                detail={
                    "source_url": url,
                    "row_count": result.row_count,
                    "cache_version": result.cache_version,
                },
            )
            return result

        self._run_async(
            _do,
            "下載並匯入財政部稅籍資料中，請稍候...",
            on_success=lambda r: QMessageBox.information(
                self,
                "下載完成",
                f"已成功下載並匯入 {r.row_count:,} 筆稅籍資料。\n"
                f"版本：{r.cache_version}\n"
                f"資料日期：{r.data_freshness_iso or '未知'}",
            ),
        )

    # ------------------------------------------------------------------
    # Settings actions
    # ------------------------------------------------------------------
    def on_open_data_folder(self) -> None:
        self._open_folder(self._container.paths.data_root)

    def on_open_attachments_folder(self) -> None:
        self._open_folder(self._container.paths.attachments_dir)

    def on_copy_db_path(self) -> None:
        self._copy(str(self._container.paths.db_path))

    def on_copy_attachments_path(self) -> None:
        self._copy(str(self._container.paths.attachments_dir))

    def on_save_display_name(self) -> None:
        try:
            cleaned = self._container.settings.set_setting(
                "display.local_user_name", self._display_name.text()
            )
        except SettingsValidationError as err:
            QMessageBox.warning(self, "儲存失敗", error_message(err.code))
            return
        except Exception as err:
            self._container.system_log.error("settings save failed", exc=err)
            QMessageBox.warning(
                self, "儲存失敗", error_message("settings.save.failed")
            )
            return
        self._container.audit.set_actor(cleaned)
        self._display_name.setText(cleaned)
        QMessageBox.information(self, "已儲存", "設定已儲存")

    def on_save_query_mode(self) -> None:
        mode = self._query_mode.currentData()
        try:
            self._container.settings.set_setting("tax_cache.query_mode", str(mode))
        except SettingsValidationError as err:
            QMessageBox.warning(self, "儲存失敗", error_message(err.code))
            return
        except Exception as err:
            self._container.system_log.error("settings save failed", exc=err)
            QMessageBox.warning(
                self, "儲存失敗", error_message("settings.save.failed")
            )
            return
        QMessageBox.information(self, "已儲存", "查詢模式已更新")

    # ------------------------------------------------------------------
    # OS helpers
    # ------------------------------------------------------------------
    def _open_folder(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as err:
            self._container.system_log.error("open folder failed", exc=err)
            QMessageBox.warning(
                self, "開啟失敗", error_message("settings.path.open_failed")
            )

    def _copy(self, text: str) -> None:
        try:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text)
        except Exception as err:
            self._container.system_log.error("copy path failed", exc=err)
            QMessageBox.warning(
                self, "複製失敗", error_message("settings.path.copy_failed")
            )
            return
        QMessageBox.information(self, "已複製", "已複製路徑至剪貼簿")

    # ------------------------------------------------------------------
    # Backup / restore section (slice 11)
    # ------------------------------------------------------------------

    def _build_backup_group(self) -> QGroupBox:
        group = QGroupBox("備份與還原")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        info = QLabel(
            f"備份資料夾：{_middle_elide(str(self._container.paths.backups_dir))}"
        )
        info.setToolTip(str(self._container.paths.backups_dir))
        info.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        backup_btn = QPushButton("立即備份")
        backup_btn.clicked.connect(self.on_backup)
        btn_row.addWidget(backup_btn)

        restore_btn = QPushButton("還原備份")
        restore_btn.clicked.connect(self.on_restore)
        btn_row.addWidget(restore_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        return group

    def on_backup(self) -> None:
        try:
            row = self._container.backup.create_backup(self._container.paths)
        except BackupError as err:
            QMessageBox.critical(self, "備份失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "備份失敗", error_message("backup.create.failed"))
            return
        QMessageBox.information(
            self,
            "備份完成",
            f"已備份至：\n{row.backup_path}\n\n檔案大小：{row.file_size:,} bytes",
        )

    def on_restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇備份檔", "", "SQLite 備份 (*.sqlite)"
        )
        if not path:
            return

        reply1 = QMessageBox.question(
            self,
            "確認還原",
            f"確定要從以下備份還原？\n\n{path}\n\n"
            "還原前會自動建立目前資料的備份快照。\n"
            "還原後現有資料將被取代。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply1 != QMessageBox.StandardButton.Yes:
            return

        reply2 = QMessageBox.question(
            self,
            "再次確認",
            "再次確認：此操作將覆蓋目前所有資料。確定繼續嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return

        try:
            self._container.backup.restore_backup(
                Path(path), self._container.paths
            )
        except BackupError as err:
            QMessageBox.critical(self, "還原失敗", error_message(err.code))
            return
        except Exception:
            QMessageBox.critical(self, "還原失敗", error_message("backup.restore.failed"))
            return

        QMessageBox.information(
            self,
            "還原完成",
            "資料已還原。建議重新啟動應用程式以確保狀態一致。",
        )
