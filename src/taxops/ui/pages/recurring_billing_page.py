"""Recurring billing page: two-level accordion (client > plan > occurrences)."""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.clock import today_iso as project_today_iso
from ...i18n import error_message
from ...repositories.recurring_billing import LineRow, OccurrenceRow, PlanRow
from ...services.container import ServiceContainer
from ...services.recurring_billing import RecurringBillingError
from ..dialogs.recurring_billing_dialogs import (
    ConfirmOccurrenceDialog,
    LineDialog,
    PlanDialog,
    SkipOccurrenceDialog,
)
from ..style import (
    BTN_DANGER_SM,
    BTN_PRIMARY_SM,
    BTN_SECONDARY_SM,
    STATUS_ARCHIVED_FG,
    STATUS_CONFIRMED_FG,
    STATUS_PENDING_FG,
    STATUS_SKIPPED_FG,
    TEXT_MUTED,
)
from ..widgets.flow_layout import FlowLayout

_log = logging.getLogger(__name__)

_FREQ_LABELS: dict[str, str] = {
    "monthly":       "月開",
    "quarterly":     "季開",
    "semiannual":    "半年開",
    "annual":        "年開",
    "custom_months": "自訂",
}

_ALL_CLIENTS = -1
_WINDOW_DAYS = 90

# Per-row toolbar buttons use the centralised design tokens so the label is
# always legible against the row background (was the source of the SLOP report
# about 編輯方案 / 新增明細 blending in).
_SMALL_BTN = BTN_PRIMARY_SM
_SKIP_BTN = BTN_SECONDARY_SM
_DANGER_BTN = BTN_DANGER_SM
_STATUS_COLORS: dict[str, str] = {
    "pending":   STATUS_PENDING_FG,
    "confirmed": STATUS_CONFIRMED_FG,
    "skipped":   STATUS_SKIPPED_FG,
    "cancelled": STATUS_ARCHIVED_FG,
}

_PLAN_TOGGLE = (
    "QPushButton { text-align: left; border: none; background: transparent; "
    "font-size: 13px; font-weight: 600; padding: 4px 8px; color: #0F172A; }"
    "QPushButton:hover { color: #2563EB; }"
)
_CLIENT_TOGGLE = (
    "QPushButton { text-align: left; border: none; background: transparent; "
    "font-size: 14px; font-weight: 600; padding: 2px 4px; color: #F8FAFC; }"
    "QPushButton:hover { color: #93C5FD; }"
)


def _fmt(cents: int) -> str:
    return f"NT${cents:,}"


# ── occurrence row ────────────────────────────────────────────────────────────

class _OccRow(QWidget):
    def __init__(
        self,
        occ: OccurrenceRow,
        line: LineRow,
        svc,
        page: "RecurringBillingPage",
        alt: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._occ = occ
        self._line = line
        self._svc = svc
        self._page = page

        if alt:
            self.setAutoFillBackground(True)
            self.setStyleSheet("background-color: #F8FAFC;")

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 4, 12, 4)
        row.setSpacing(12)

        date_lbl = QLabel(occ.expected_issue_date)
        date_lbl.setTextFormat(Qt.TextFormat.PlainText)
        date_lbl.setFixedWidth(92)
        row.addWidget(date_lbl)

        bill_lbl = QLabel(line.bill_to_name)
        bill_lbl.setTextFormat(Qt.TextFormat.PlainText)
        bill_lbl.setMinimumWidth(120)
        row.addWidget(bill_lbl)

        display_amount = occ.confirmed_amount or line.amount
        row.addWidget(QLabel(_fmt(display_amount)))
        row.addStretch()

        color = _STATUS_COLORS.get(occ.status, STATUS_SKIPPED_FG)

        if occ.status == "pending":
            s = QLabel("● 待確認")
            s.setStyleSheet(f"color: {color}; font-weight: 600;")
            row.addWidget(s)
            confirm_btn = QPushButton("確認")
            confirm_btn.setStyleSheet(_SMALL_BTN)
            skip_btn = QPushButton("跳過")
            skip_btn.setStyleSheet(_SKIP_BTN)
            confirm_btn.clicked.connect(self._on_confirm)
            skip_btn.clicked.connect(self._on_skip)
            row.addWidget(confirm_btn)
            row.addWidget(skip_btn)
        elif occ.status == "confirmed":
            s = QLabel("✓ 已確認")
            s.setStyleSheet(f"color: {color}; font-weight: 600;")
            row.addWidget(s)
            if occ.confirmed_invoice_no:
                inv = QLabel(occ.confirmed_invoice_no)
                inv.setTextFormat(Qt.TextFormat.PlainText)
                inv.setStyleSheet(f"color: {color}; font-size: 12px;")
                row.addWidget(inv)
        else:
            icon = "✗" if occ.status == "skipped" else "—"
            label = {"skipped": "已跳過", "cancelled": "已取消"}.get(occ.status, occ.status)
            s = QLabel(f"{icon} {label}")
            s.setStyleSheet(f"color: {color};")
            row.addWidget(s)
            if occ.skipped_reason:
                r = QLabel(occ.skipped_reason)
                r.setTextFormat(Qt.TextFormat.PlainText)
                r.setStyleSheet(f"color: {color}; font-size: 12px;")
                row.addWidget(r)

    def _on_confirm(self) -> None:
        dlg = ConfirmOccurrenceDialog(self._svc, self._occ, self._line, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._page._refresh()

    def _on_skip(self) -> None:
        dlg = SkipOccurrenceDialog(self._svc, self._occ, self._line, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._page._refresh()


# ── plan section ──────────────────────────────────────────────────────────────

class _PlanSection(QFrame):
    def __init__(
        self,
        plan: PlanRow,
        line_by_id: dict[int, LineRow],
        window_occs: list[OccurrenceRow],
        pending_count: int,
        next_date: str | None,
        svc,
        page: "RecurringBillingPage",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plan = plan
        self._line_by_id = line_by_id
        self._svc = svc
        self._page = page
        self.pending_count = pending_count

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setContentsMargins(0, 0, 0, 0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet("QWidget { background-color: #F1F5F9; }")
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(8, 6, 8, 6)
        h_row.setSpacing(8)

        self._toggle_btn = QPushButton(f"▶  {plan.plan_name}")
        self._toggle_btn.setStyleSheet(_PLAN_TOGGLE)
        self._toggle_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h_row.addWidget(self._toggle_btn)

        freq_label = _FREQ_LABELS.get(plan.frequency, plan.frequency)
        freq_lbl = QLabel(f"[{freq_label}]")
        freq_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        h_row.addWidget(freq_lbl)

        if plan.status == "archived":
            arch = QLabel("[已封存]")
            arch.setStyleSheet(f"color: {STATUS_ARCHIVED_FG}; font-size: 12px;")
            h_row.addWidget(arch)

        if next_date:
            next_lbl = QLabel(f"下次：{next_date}")
            next_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
            h_row.addWidget(next_lbl)

        if pending_count > 0:
            p_lbl = QLabel(f"● {pending_count} 筆待確認")
            p_lbl.setStyleSheet(f"color: {STATUS_PENDING_FG}; font-weight: 600; font-size: 12px;")
            h_row.addWidget(p_lbl)

        h_row.addStretch()

        self._action_btns: list[QWidget] = []
        if plan.status != "archived":
            edit_btn = QPushButton("編輯方案")
            edit_btn.setStyleSheet(_SMALL_BTN)
            add_line_btn = QPushButton("新增明細")
            add_line_btn.setStyleSheet(_SMALL_BTN)
            archive_btn = QPushButton("封存")
            archive_btn.setStyleSheet(_DANGER_BTN)
            h_row.addWidget(edit_btn)
            h_row.addWidget(add_line_btn)
            h_row.addWidget(archive_btn)
            edit_btn.setVisible(False)
            add_line_btn.setVisible(False)
            archive_btn.setVisible(False)
            self._action_btns = [edit_btn, add_line_btn, archive_btn]
            edit_btn.clicked.connect(self._on_edit)
            add_line_btn.clicked.connect(self._on_add_line)
            archive_btn.clicked.connect(self._on_archive)

        outer.addWidget(header)

        # Body
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        if window_occs:
            for i, occ in enumerate(window_occs):
                line = line_by_id.get(occ.line_id)
                if line is None:
                    continue
                body_layout.addWidget(
                    _OccRow(occ, line, svc, page, alt=(i % 2 == 1), parent=self._body)
                )
        else:
            empty = QLabel("此期間內無開立紀錄")
            empty.setStyleSheet("color: #9CA3AF; padding: 8px 16px;")
            body_layout.addWidget(empty)

        self._body.setVisible(False)
        outer.addWidget(self._body)
        self._expanded = False

        self._toggle_btn.clicked.connect(self._toggle)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        for btn in self._action_btns:
            btn.setVisible(self._expanded)
        icon = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{icon}  {self._plan.plan_name}")

    def expand(self) -> None:
        if not self._expanded:
            self._toggle()

    def _on_edit(self) -> None:
        dlg = PlanDialog(self._svc, self._plan.client_id, plan=self._plan, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._page._refresh()

    def _on_add_line(self) -> None:
        dlg = LineDialog(self._svc, self._plan.id, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._page._generate_for_client(self._plan.client_id)
            self._page._refresh()

    def _on_archive(self) -> None:
        pending_warning = (
            f"\n\n⚠ 此方案目前有 {self.pending_count} 筆待確認紀錄尚未處理，"
            "建議先確認或跳過後再封存。"
            if self.pending_count > 0 else ""
        )
        reply = QMessageBox.question(
            self, "確認封存",
            f"確定要封存方案「{self._plan.plan_name}」嗎？\n"
            f"封存後不再產生新的開立紀錄。{pending_warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._svc.archive_plan(self._plan.id)
        except RecurringBillingError as err:
            QMessageBox.warning(self, "封存失敗", error_message(err.code))
            return
        except Exception:
            _log.exception("archive_plan failed")
            QMessageBox.warning(self, "封存失敗", error_message("system.unexpected"))
            return
        self._page._refresh()


# ── client group ──────────────────────────────────────────────────────────────

class _ClientGroup(QFrame):
    def __init__(
        self,
        client_name: str,
        client_id: int,
        total_pending: int,
        svc,
        page: "RecurringBillingPage",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client_id = client_id
        self._client_name = client_name
        self._svc = svc
        self._page = page

        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet(
            "QFrame { border: 1px solid #E2E8F0; border-radius: 6px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setStyleSheet(
            "QWidget { background-color: #1E293B; border-radius: 5px; }"
        )
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(12, 8, 12, 8)
        h_row.setSpacing(10)

        self._toggle_btn = QPushButton(f"▶  {client_name}")
        self._toggle_btn.setStyleSheet(_CLIENT_TOGGLE)
        self._toggle_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        h_row.addWidget(self._toggle_btn)

        if total_pending > 0:
            badge = QLabel(f"● {total_pending} 筆待確認")
            badge.setStyleSheet("color: #FCD34D; font-weight: 600; font-size: 12px;")
            h_row.addWidget(badge)

        self._new_plan_btn = QPushButton("+ 新增方案")
        self._new_plan_btn.setStyleSheet(_SMALL_BTN)
        self._new_plan_btn.setVisible(False)
        h_row.addWidget(self._new_plan_btn)

        outer.addWidget(header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 8, 8, 8)
        self._body_layout.setSpacing(6)
        self._body.setVisible(False)
        outer.addWidget(self._body)

        self._expanded = False
        self._toggle_btn.clicked.connect(self._toggle)
        self._new_plan_btn.clicked.connect(self._on_new_plan)

    def add_plan(self, section: _PlanSection) -> None:
        self._body_layout.addWidget(section)

    def expand(self) -> None:
        if not self._expanded:
            self._toggle()

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._new_plan_btn.setVisible(self._expanded)
        icon = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{icon}  {self._client_name}")

    def _on_new_plan(self) -> None:
        dlg = PlanDialog(self._svc, self._client_id, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._page._generate_for_client(self._client_id)
            self._page._refresh()


# ── page ──────────────────────────────────────────────────────────────────────

class RecurringBillingPage(QWidget):
    def __init__(
        self, container: ServiceContainer, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._rb = container.recurring_billing
        self._clients_map: dict[int, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title = QLabel("固定開立")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        # Filter / action row — FlowLayout so the row wraps onto a second
        # line on narrow windows instead of clipping the rightmost buttons.
        filter_widget = QWidget()
        filter_row = FlowLayout(filter_widget, h_spacing=8, v_spacing=6)
        filter_row.addWidget(QLabel("客戶："))
        self._client_combo = QComboBox()
        self._client_combo.setMinimumWidth(240)
        filter_row.addWidget(self._client_combo)
        self._archived_check = QCheckBox("包含已封存")
        filter_row.addWidget(self._archived_check)
        self._add_plan_btn = QPushButton("+ 新增方案")
        filter_row.addWidget(self._add_plan_btn)
        self._gen_btn = QPushButton("產生待開立紀錄")
        self._gen_btn.setToolTip("根據所有有效方案及明細產生本期預期開立紀錄")
        filter_row.addWidget(self._gen_btn)
        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet("color: #16A34A; font-size: 12px;")
        filter_row.addWidget(self._status_lbl)
        outer.addWidget(filter_widget)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)
        self._content_layout.addStretch()
        scroll.setWidget(self._content)
        outer.addWidget(scroll, stretch=1)

        self._client_combo.currentIndexChanged.connect(lambda _: self._rebuild_accordion())
        self._archived_check.stateChanged.connect(lambda _: self._rebuild_accordion())
        self._add_plan_btn.clicked.connect(self._on_add_plan_global)
        self._gen_btn.clicked.connect(self._on_generate_occurrences)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._refresh()

    def refresh_context(self) -> None:
        """Reload data when global state changes (e.g. client deleted)."""
        self._refresh()

    def clear_filter(self) -> None:
        self._client_combo.blockSignals(True)
        self._client_combo.setCurrentIndex(0)
        self._client_combo.blockSignals(False)
        self._archived_check.setChecked(False)

    def _refresh(self) -> None:
        self._repopulate_client_combo()
        self._rebuild_accordion()

    def _generate_for_client(self, client_id: int) -> bool:
        """Generate occurrences for all active plans of a client (idempotent).

        Called after plan/line creation from both the toolbar button and per-client
        group headers, so the accordion shows pending rows immediately.
        """
        try:
            plans = self._rb.list_plans(client_id=client_id, include_archived=False)
        except Exception as err:
            _log.warning("generate_for_client: list_plans failed cid=%d", client_id, exc_info=True)
            self._container.system_log.error(
                "recurring billing auto-generation failed",
                exc=err,
                detail={"client_id": client_id, "stage": "list_plans"},
            )
            QMessageBox.warning(self, "紀錄產生失敗", error_message("system.unexpected"))
            return False
        errors: list[str] = []
        for plan in plans:
            try:
                self._rb.generate_occurrences(plan.id)
            except RecurringBillingError as err:
                _log.warning("generate_for_client: plan %d failed", plan.id, exc_info=True)
                self._container.system_log.error(
                    "recurring billing auto-generation failed",
                    exc=err,
                    detail={"client_id": client_id, "plan_id": plan.id, "code": err.code},
                )
                errors.append(f"{plan.plan_name}: {error_message(err.code)}")
            except Exception as err:
                _log.warning("generate_for_client: plan %d failed", plan.id, exc_info=True)
                self._container.system_log.error(
                    "recurring billing auto-generation failed",
                    exc=err,
                    detail={"client_id": client_id, "plan_id": plan.id},
                )
                errors.append(f"{plan.plan_name}: {error_message('system.unexpected')}")
        if errors:
            QMessageBox.warning(self, "方案已儲存，但紀錄產生失敗", "\n".join(errors))
            return False
        return True

    def _show_status(self, text: str, duration_ms: int = 4000) -> None:
        """Display a transient status message that auto-clears after duration_ms."""
        self._status_lbl.setText(text)
        try:
            self._status_timer.stop()
        except AttributeError:
            pass
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._status_lbl.clear)
        self._status_timer.start(duration_ms)

    def _on_add_plan_global(self) -> None:
        client_id = self._client_combo.currentData()
        if client_id == _ALL_CLIENTS or client_id is None:
            return
        dlg = PlanDialog(self._rb, client_id, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._generate_for_client(client_id)
            self._refresh()

    def _on_generate_occurrences(self) -> None:
        self._gen_btn.setEnabled(False)
        self._status_lbl.clear()
        try:
            plans = self._rb.list_plans(include_archived=False)
        except Exception as err:
            _log.exception("list_plans failed in generate")
            self._container.system_log.error(
                "recurring billing generation failed",
                exc=err,
                detail={"stage": "list_plans"},
            )
            QMessageBox.warning(self, "錯誤", error_message("system.unexpected"))
            self._gen_btn.setEnabled(True)
            return

        errors: list[str] = []
        added_count = 0
        for plan in plans:
            try:
                before_ids = {
                    row.id for row in self._rb.list_occurrences(plan_id=plan.id)
                }
                generated = self._rb.generate_occurrences(plan.id)
                added_count += sum(row.id not in before_ids for row in generated)
            except RecurringBillingError as err:
                self._container.system_log.error(
                    "recurring billing generation failed",
                    exc=err,
                    detail={"plan_id": plan.id, "code": err.code},
                )
                errors.append(f"{plan.plan_name}: {error_message(err.code)}")
            except Exception as err:
                _log.exception("generate_occurrences failed plan=%d", plan.id)
                self._container.system_log.error(
                    "recurring billing generation failed",
                    exc=err,
                    detail={"plan_id": plan.id},
                )
                errors.append(f"{plan.plan_name}: 未預期錯誤")

        self._gen_btn.setEnabled(True)
        if errors:
            QMessageBox.warning(self, "部分方案產生失敗", "\n".join(errors))
        elif added_count > 0:
            self._show_status(f"✓ 已新增 {added_count} 筆待確認", 4000)
        else:
            self._show_status("✓ 所有方案已是最新", 3000)
        self._rebuild_accordion()

    def _repopulate_client_combo(self) -> None:
        prev_id = self._client_combo.currentData()
        self._clients_map.clear()

        self._client_combo.blockSignals(True)
        self._client_combo.clear()
        self._client_combo.addItem("全部客戶", userData=_ALL_CLIENTS)
        try:
            for c in self._container.clients.list_clients(limit=1000):
                self._client_combo.addItem(
                    f"{c.client_code} {c.client_name}", userData=c.id
                )
                self._clients_map[c.id] = c.client_name
        except Exception as err:
            _log.warning("list_clients failed", exc_info=True)
            self._container.system_log.error(
                "recurring billing clients load failed",
                exc=err,
            )
            self._status_lbl.setText("客戶資料載入失敗，請按「重新整理」再試。")
        self._client_combo.blockSignals(False)

        if prev_id is not None:
            idx = self._client_combo.findData(prev_id)
            if idx >= 0:
                self._client_combo.setCurrentIndex(idx)

    def _rebuild_accordion(self) -> None:
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        selected_client = self._client_combo.currentData()
        is_all_clients = (selected_client == _ALL_CLIENTS or selected_client is None)
        self._add_plan_btn.setEnabled(not is_all_clients)
        self._add_plan_btn.setToolTip(
            "" if not is_all_clients else "請先在左側選擇特定客戶"
        )
        include_archived = self._archived_check.isChecked()
        client_id_filter = None if selected_client == _ALL_CLIENTS else selected_client

        today = datetime.date.fromisoformat(project_today_iso())
        past_cutoff = (today - datetime.timedelta(days=_WINDOW_DAYS)).isoformat()
        future_cutoff = (today + datetime.timedelta(days=_WINDOW_DAYS)).isoformat()
        today_iso = today.isoformat()

        try:
            plans = self._rb.list_plans(
                client_id=client_id_filter,
                include_archived=include_archived,
            )
        except Exception as err:
            _log.warning("list_plans failed", exc_info=True)
            self._container.system_log.error(
                "recurring billing plans load failed",
                exc=err,
            )
            self._status_lbl.setText("固定開立方案載入失敗，請按「重新整理」再試。")
            return

        if not plans:
            empty = QLabel("目前沒有固定開立方案。請先在上方選擇客戶，再點「+ 新增方案」。")
            empty.setStyleSheet("color: #9CA3AF; padding: 20px;")
            self._content_layout.insertWidget(0, empty)
            return

        by_client: dict[int, list[PlanRow]] = defaultdict(list)
        for plan in plans:
            by_client[plan.client_id].append(plan)

        insert_pos = 0
        for client_id, client_plans in by_client.items():
            client_name = self._clients_map.get(client_id, f"客戶 #{client_id}")

            total_pending = 0
            plan_data = []
            for plan in client_plans:
                try:
                    lines = self._rb.list_lines(plan.id)
                    all_occs = self._rb.list_occurrences(
                        plan_id=plan.id, before_date=future_cutoff
                    )
                except Exception as err:
                    _log.warning("load plan data failed plan=%d", plan.id, exc_info=True)
                    self._container.system_log.error(
                        "recurring billing plan detail load failed",
                        exc=err,
                        detail={"plan_id": plan.id},
                    )
                    self._status_lbl.setText(
                        f"方案「{plan.plan_name}」明細載入失敗，請重新整理。"
                    )
                    lines, all_occs = [], []

                # all_occs is already sorted ASC by expected_issue_date (repo ORDER BY)
                window_occs = [o for o in reversed(all_occs) if o.expected_issue_date >= past_cutoff]
                pending_count = sum(1 for o in window_occs if o.status == "pending")
                next_date = next(
                    (
                        o.expected_issue_date
                        for o in all_occs
                        if o.status == "pending" and o.expected_issue_date >= today_iso
                    ),
                    None,
                )
                total_pending += pending_count
                plan_data.append(
                    (plan, {l.id: l for l in lines}, window_occs, pending_count, next_date)
                )

            group = _ClientGroup(
                client_name=client_name,
                client_id=client_id,
                total_pending=total_pending,
                svc=self._rb,
                page=self,
            )

            any_pending = False
            for plan, line_by_id, window_occs, pending_count, next_date in plan_data:
                section = _PlanSection(
                    plan=plan,
                    line_by_id=line_by_id,
                    window_occs=window_occs,
                    pending_count=pending_count,
                    next_date=next_date,
                    svc=self._rb,
                    page=self,
                )
                group.add_plan(section)
                if pending_count > 0:
                    section.expand()
                    any_pending = True

            if any_pending:
                group.expand()

            self._content_layout.insertWidget(insert_pos, group)
            insert_pos += 1
