"""Annual-work request workflow backed by the existing request tables."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ...i18n.errors import ERROR_MESSAGES, error_message
from ...i18n.labels import BUTTON_LABELS
from ...repositories.annual_work import AnnualWorkItemRow
from ...services.annual_work import (
    AnnualLinkedOverview,
    AnnualWorkError,
    AnnualWorkValidationError,
    LinkedDocumentRequestResult,
)
from ...services.container import ServiceContainer
from ..pages.document_requests_page import DocumentRequestsPage


def _error_code(exc: BaseException, fallback: str) -> str:
    candidate = getattr(exc, "code", "")
    return (
        candidate
        if isinstance(candidate, str)
        and (
            candidate in ERROR_MESSAGES
            or candidate.startswith("annual_work.")
            or candidate.startswith("doc_request.")
            or candidate.startswith("doc_request_item.")
        )
        else fallback
    )


def _safe_log(
    system_log: object | None,
    message: str,
    *,
    operation: str,
    code: str,
    item_id: int,
    request_id: int | None = None,
    engagement_id: int | None = None,
) -> None:
    """Persist identifier-only diagnostics without committing caller work."""
    if system_log is None:
        return
    try:
        connection = getattr(system_log, "connection", None)
        if connection is not None and bool(connection.in_transaction):
            return
    except Exception:
        return
    detail: dict[str, object] = {
        "operation": operation,
        "code": code,
        "item_id": item_id,
    }
    if type(request_id) is int:
        detail["request_id"] = request_id
    if type(engagement_id) is int:
        detail["engagement_id"] = engagement_id
    try:
        system_log.error(message, detail=detail)
    except Exception:
        return


def _schedule_focus(owner: QWidget, target: QWidget) -> None:
    def focus_if_alive() -> None:
        if isValid(owner) and isValid(target):
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    QTimer.singleShot(0, owner, focus_if_alive)


def _contains_bad_control(value: str) -> bool:
    return any(
        unicodedata.category(char).startswith("C")
        for char in value
        if char not in {"\n", "\t"}
    )


@dataclass(frozen=True)
class AnnualRequestCommitEvidence:
    operation: str
    item: AnnualWorkItemRow
    engagement_id: int
    request_result: LinkedDocumentRequestResult | None = None


@dataclass(frozen=True)
class AnnualRequestCommitAck:
    evidence_taken: bool
    readback_succeeded: bool


AnnualRequestCommitHandler = Callable[
    [AnnualRequestCommitEvidence], AnnualRequestCommitAck
]


def _deliver_commit_evidence(
    handler: AnnualRequestCommitHandler,
    evidence: AnnualRequestCommitEvidence,
) -> AnnualRequestCommitAck:
    try:
        ack = handler(evidence)
    except Exception:
        return AnnualRequestCommitAck(False, False)
    if (
        not isinstance(ack, AnnualRequestCommitAck)
        or type(ack.evidence_taken) is not bool
        or type(ack.readback_succeeded) is not bool
        or (ack.readback_succeeded and not ack.evidence_taken)
    ):
        return AnnualRequestCommitAck(False, False)
    return ack


class CreateLinkedRequestDialog(QDialog):
    """Create the first linked request, preserving failed form input exactly."""

    def __init__(
        self,
        container: ServiceContainer,
        item_id: int,
        *,
        commit_handler: AnnualRequestCommitHandler,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self.item_id = item_id
        self._commit_handler = commit_handler
        self._busy = False
        self.committed_request_id: int | None = None
        self.committed_evidence: AnnualRequestCommitEvidence | None = None
        self.evidence_handed_off = False
        self.setObjectName("CreateLinkedRequestDialog")
        self.setWindowTitle("建立第一筆索件")
        self.setMinimumSize(560, 500)
        self.resize(640, 560)
        font = self.font()
        font.setPointSize(11)
        self.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        title = QLabel("建立第一筆索件")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.request_name_input = QLineEdit()
        self.request_name_input.setPlaceholderText("例如：115 年度營所稅結算索件")
        self.due_date_input = QLineEdit()
        self.due_date_input.setPlaceholderText("YYYY-MM-DD（可留空）")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("索件說明（保留換行）")
        self.notes_input.setMinimumHeight(90)
        self.items_input = QPlainTextEdit()
        self.items_input.setPlaceholderText("每行一個文件項目，至少一行")
        self.items_input.setMinimumHeight(120)
        form.addRow("索件名稱", self.request_name_input)
        form.addRow("截止日", self.due_date_input)
        form.addRow("說明", self.notes_input)
        form.addRow("文件項目", self.items_input)
        layout.addLayout(form, 1)

        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.feedback_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText(BUTTON_LABELS["annual.request.create"])
        self.cancel_button = self.buttons.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        self.cancel_button.setText(
            BUTTON_LABELS["annual.request.create_cancel"]
        )
        layout.addWidget(self.buttons)
        self.save_button.clicked.connect(self.save)
        self.cancel_button.clicked.connect(self.reject)

    def _invalid(
        self, message: str, target: QWidget
    ) -> tuple[None, None, None, None]:
        self.feedback_label.setText(message)
        _schedule_focus(self, target)
        return None, None, None, None

    def _values(
        self,
    ) -> tuple[str | None, str | None, str | None, tuple[str, ...] | None]:
        request_name = self.request_name_input.text()
        due_date = self.due_date_input.text()
        notes = self.notes_input.toPlainText()
        raw_items = self.items_input.toPlainText()
        if (
            not request_name.strip()
            or len(request_name) > 120
            or _contains_bad_control(request_name)
        ):
            return self._invalid(
                "索件名稱為必填，且不得超過 120 個字。", self.request_name_input
            )
        if due_date:
            try:
                date.fromisoformat(due_date)
            except (TypeError, ValueError):
                return self._invalid(
                    error_message("doc_request.due_date.invalid"),
                    self.due_date_input,
                )
        if len(notes) > 2000 or _contains_bad_control(notes):
            return self._invalid(
                "索件說明不得超過 2,000 個字，且不可包含控制字元。",
                self.notes_input,
            )
        item_names = tuple(line.strip() for line in raw_items.splitlines())
        if not item_names or any(not value for value in item_names):
            return self._invalid("請輸入至少一個文件項目，每行一個。", self.items_input)
        if any(len(value) > 200 or _contains_bad_control(value) for value in item_names):
            return self._invalid(
                "每個文件項目不得超過 200 個字，且不可包含控制字元。",
                self.items_input,
            )
        return (
            request_name,
            due_date or None,
            notes or None,
            item_names,
        )

    def save(self) -> None:
        if self._busy or self.committed_request_id is not None:
            return
        request_name, due_date, notes, item_names = self._values()
        if request_name is None or item_names is None:
            return
        self._busy = True
        self.save_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        try:
            result = self._container.annual_work.create_linked_request(
                self.item_id,
                request_name=request_name,
                item_names=item_names,
                due_date=due_date,
                notes=notes,
            )
        except (AnnualWorkValidationError, AnnualWorkError) as exc:
            self._busy = False
            self.save_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            code = _error_code(exc, "system.unexpected")
            if not isinstance(exc, AnnualWorkValidationError):
                _safe_log(
                    getattr(self._container, "system_log", None),
                    "annual request create failed",
                    operation="create",
                    code=code,
                    item_id=self.item_id,
                )
            self.feedback_label.setText(error_message(code))
            focus_by_code = {
                "doc_request.name.required": self.request_name_input,
                "doc_request.name.invalid": self.request_name_input,
                "doc_request.due_date.invalid": self.due_date_input,
                "doc_request.notes.invalid": self.notes_input,
                "doc_request.items.invalid": self.items_input,
                "doc_request_item.name.invalid": self.items_input,
                "doc_request_item.name.required": self.items_input,
            }
            _schedule_focus(self, focus_by_code.get(code, self.request_name_input))
            return
        except Exception as exc:
            self._busy = False
            self.save_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            _safe_log(
                getattr(self._container, "system_log", None),
                "annual request create failed",
                operation="create",
                code=_error_code(exc, "system.unexpected"),
                item_id=self.item_id,
            )
            self.feedback_label.setText(error_message("system.unexpected"))
            return

        self.committed_request_id = result.request.id
        evidence = AnnualRequestCommitEvidence(
            operation="create",
            item=result.item,
            engagement_id=result.engagement.id,
            request_result=result,
        )
        self.committed_evidence = evidence
        ack = _deliver_commit_evidence(self._commit_handler, evidence)
        self.evidence_handed_off = ack.evidence_taken
        self._busy = False
        if ack.evidence_taken:
            self.accept()
            return
        self.feedback_label.setText(
            "索件已建立，但交接核對失敗；請關閉視窗後重新讀取，請勿再次送出。"
        )

    def reject(self) -> None:
        if self._busy:
            self.feedback_label.setText("資料處理中，請等待完成。")
            return
        super().reject()


class LinkExistingEngagementDialog(QDialog):
    """Select one active engagement owned by the annual item's client."""

    def __init__(
        self,
        container: ServiceContainer,
        item_id: int,
        *,
        client_id: int,
        commit_handler: AnnualRequestCommitHandler,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self.item_id = item_id
        self.client_id = client_id
        self._commit_handler = commit_handler
        self._busy = False
        self.committed_engagement_id: int | None = None
        self.committed_evidence: AnnualRequestCommitEvidence | None = None
        self.evidence_handed_off = False
        self.setObjectName("LinkExistingEngagementDialog")
        self.setWindowTitle("連結既有案件")
        self.setMinimumSize(520, 240)
        self.resize(620, 280)
        font = self.font()
        font.setPointSize(11)
        self.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        title = QLabel("連結同一客戶的既有案件")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)
        hint = QLabel("只顯示此年度工作所屬客戶的有效案件。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.engagement_combo = QComboBox()
        self.engagement_combo.setMinimumWidth(380)
        form.addRow("既有案件", self.engagement_combo)
        layout.addLayout(form)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.feedback_label)
        layout.addStretch(1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.link_button = self.buttons.button(
            QDialogButtonBox.StandardButton.Save
        )
        self.link_button.setText(BUTTON_LABELS["annual.request.link"])
        self.cancel_button = self.buttons.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        self.cancel_button.setText(
            BUTTON_LABELS["annual.request.link_cancel"]
        )
        layout.addWidget(self.buttons)
        self.link_button.clicked.connect(self.link)
        self.cancel_button.clicked.connect(self.reject)
        self._load_options()

    def _load_options(self) -> None:
        try:
            engagements = self._container.engagements.list_by_client(
                self.client_id,
                order_by="updated_at",
                order_dir="DESC",
                limit=200,
                offset=0,
            )
        except Exception as exc:
            _safe_log(
                getattr(self._container, "system_log", None),
                "annual request link options failed",
                operation="link_options",
                code=_error_code(exc, "system.unexpected"),
                item_id=self.item_id,
            )
            self.feedback_label.setText("既有案件讀取失敗，請關閉後再試。")
            self.link_button.setEnabled(False)
            return
        for engagement in engagements:
            self.engagement_combo.addItem(
                f"{engagement.engagement_name}｜{engagement.period_name}",
                userData=engagement.id,
            )
        if not engagements:
            self.feedback_label.setText("此客戶目前沒有可連結的既有案件。")
            self.link_button.setEnabled(False)

    def link(self) -> None:
        if self._busy or self.committed_engagement_id is not None:
            return
        engagement_id = self.engagement_combo.currentData()
        if type(engagement_id) is not int or engagement_id <= 0:
            self.feedback_label.setText("請選擇要連結的既有案件。")
            _schedule_focus(self, self.engagement_combo)
            return
        self._busy = True
        self.link_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        try:
            item = self._container.annual_work.link_existing_engagement(
                self.item_id, engagement_id
            )
        except (AnnualWorkValidationError, AnnualWorkError) as exc:
            self._busy = False
            self.link_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            code = _error_code(exc, "system.unexpected")
            if not isinstance(exc, AnnualWorkValidationError):
                _safe_log(
                    getattr(self._container, "system_log", None),
                    "annual request link failed",
                    operation="link",
                    code=code,
                    item_id=self.item_id,
                    engagement_id=engagement_id,
                )
            if code == "annual_work.engagement.client_mismatch":
                message = "所選案件不屬於此年度工作的客戶，未進行連結。"
            elif code == "annual_work.engagement.relink_has_history":
                message = "目前案件已有歷史資料，不能改連至其他案件。"
            elif code == "annual_work.item_details.stale":
                message = error_message(code)
            else:
                message = error_message(code)
            self.feedback_label.setText(message)
            _schedule_focus(self, self.engagement_combo)
            return
        except Exception as exc:
            self._busy = False
            self.link_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            _safe_log(
                getattr(self._container, "system_log", None),
                "annual request link failed",
                operation="link",
                code=_error_code(exc, "system.unexpected"),
                item_id=self.item_id,
                engagement_id=engagement_id,
            )
            self.feedback_label.setText(error_message("system.unexpected"))
            return
        self.committed_engagement_id = engagement_id
        evidence = AnnualRequestCommitEvidence(
            operation="link",
            item=item,
            engagement_id=engagement_id,
        )
        self.committed_evidence = evidence
        ack = _deliver_commit_evidence(self._commit_handler, evidence)
        self.evidence_handed_off = ack.evidence_taken
        self._busy = False
        if ack.evidence_taken:
            self.accept()
            return
        self.feedback_label.setText(
            "案件已連結，但交接核對失敗；請關閉後重新讀取，請勿再次送出。"
        )

    def reject(self) -> None:
        if self._busy:
            self.feedback_label.setText("資料處理中，請等待完成。")
            return
        super().reject()


class AnnualWorkflowDialog(QDialog):
    """Fixed-desktop request management for one annual work item."""

    def __init__(
        self,
        container: ServiceContainer,
        item_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self.item_id = item_id
        self.has_committed_change = False
        self._pending_evidence: AnnualRequestCommitEvidence | None = None
        self._pending_mutation_reload = False
        self.setObjectName("AnnualWorkflowDialog")
        self.setWindowTitle("年度工作索件管理")
        self.setMinimumSize(900, 540)
        self.resize(1100, 680)
        font = self.font()
        font.setPointSize(11)
        self.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("年度工作索件管理")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        self.create_button = QPushButton(
            BUTTON_LABELS["annual.request.create_first"]
        )
        self.link_button = QPushButton(
            BUTTON_LABELS["annual.request.link_existing"]
        )
        self.refresh_button = QPushButton(
            BUTTON_LABELS["annual.request.refresh"]
        )
        self.retry_button = QPushButton(
            BUTTON_LABELS["annual.request.retry"]
        )
        self.retry_button.hide()
        header.addWidget(self.create_button)
        header.addWidget(self.link_button)
        header.addWidget(self.refresh_button)
        header.addWidget(self.retry_button)
        layout.addLayout(header)

        context_frame = QFrame()
        context_frame.setFrameShape(QFrame.Shape.StyledPanel)
        context = QGridLayout(context_frame)
        self.client_label = QLabel("—")
        self.work_label = QLabel("—")
        self.operation_year_label = QLabel("—")
        self.engagement_id_label = QLabel("—")
        self.engagement_name_label = QLabel("—")
        self.state_label = QLabel("載入中")
        self.summary_request_count = QLabel("0")
        self.summary_item_counts = QLabel("文件項目 0")
        fields = (
            ("客戶", self.client_label),
            ("年度工作", self.work_label),
            ("作業年度", self.operation_year_label),
            ("案件 ID", self.engagement_id_label),
            ("案件名稱", self.engagement_name_label),
            ("連結狀態", self.state_label),
            ("索件批次", self.summary_request_count),
            ("項目狀態", self.summary_item_counts),
        )
        for index, (caption, value) in enumerate(fields):
            row, column_group = divmod(index, 4)
            column = column_group * 2
            label = QLabel(caption)
            label.setStyleSheet("color: #475569; font-size: 14px;")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setStyleSheet("font-size: 14px; font-weight: 600;")
            context.addWidget(label, row, column)
            context.addWidget(value, row, column + 1)
        layout.addWidget(context_frame)

        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.feedback_label)

        self.request_page = DocumentRequestsPage(
            container, embedded=True, view_mode="full", parent=self
        )
        self.request_page.set_external_mutation_reload(True)
        self.request_page.setEnabled(False)
        layout.addWidget(self.request_page, 1)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_button = QPushButton(
            BUTTON_LABELS["annual.request.close"]
        )
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)

        self.create_button.clicked.connect(self._open_create)
        self.link_button.clicked.connect(self._open_link)
        self.refresh_button.clicked.connect(self.reload)
        self.retry_button.clicked.connect(self.reload)
        self.close_button.clicked.connect(self.accept)
        self.request_page.data_changed.connect(
            self._on_embedded_data_changed
        )
        self.reload(operation="load")

    def _set_failed(
        self,
        *,
        operation: str,
        exc: BaseException,
        request_id: int | None = None,
        engagement_id: int | None = None,
        committed: bool = False,
    ) -> None:
        code = _error_code(exc, "system.unexpected")
        _safe_log(
            getattr(self._container, "system_log", None),
            "annual request workflow read failed",
            operation=operation,
            code=code,
            item_id=self.item_id,
            request_id=request_id,
            engagement_id=engagement_id,
        )
        self.request_page.setEnabled(False)
        self.create_button.setEnabled(False)
        self.link_button.setEnabled(False)
        self.retry_button.show()
        self.state_label.setText("索件資料不可用")
        self.feedback_label.setText(
            "資料已寫入，但重新核對失敗；請按「重新讀取索件」，請勿再次送出。"
            if committed
            else "索件資料讀取失敗，請按「重新讀取索件」再試。"
        )

    def _read_models(
        self,
    ) -> tuple[object, object, AnnualLinkedOverview, object]:
        context = self._container.annual_work.get_item_context(self.item_id)
        client = self._container.clients.get_client(context.client_id)
        if client is None:
            raise AnnualWorkValidationError("client.not_found")
        overview = self._container.annual_work.linked_overview(
            self.item_id, limit=200, offset=0
        )
        linked_engagement_id = context.item.engagement_id
        if linked_engagement_id is not None:
            if overview.engagement is None:
                raise AnnualWorkValidationError(
                    "annual_work.engagement_not_found"
                )
            if (
                overview.engagement.id != linked_engagement_id
                or overview.engagement.client_id != context.client_id
            ):
                raise AnnualWorkValidationError(
                    "annual_work.engagement.client_mismatch"
                )
        summary = self._container.annual_work.document_summary(self.item_id)
        return context, client, overview, summary

    def _render_models(
        self, context: object, client: object, overview: AnnualLinkedOverview, summary: object
    ) -> None:
        self.client_label.setText(client.client_name)
        self.work_label.setText(context.item.title)
        self.operation_year_label.setText(str(context.operation_year))
        self.summary_request_count.setText(str(summary.request_count))
        self.summary_item_counts.setText(
            "、".join(
                (
                    f"缺件 {summary.missing}",
                    f"已收 {summary.received}",
                    f"不完整 {summary.incomplete}",
                    f"無效 {summary.invalid}",
                    f"已確認 {summary.accepted}",
                    f"待確認 {summary.pending_confirm}",
                    f"不適用 {summary.not_applicable}",
                    f"客戶表示無此文件 {summary.client_said_none}",
                )
            )
        )
        engagement = overview.engagement
        if engagement is None:
            self.engagement_id_label.setText("—")
            self.engagement_name_label.setText("—")
            self.state_label.setText("尚未連結案件")
            self.request_page.setEnabled(False)
            self.create_button.setEnabled(True)
            self.link_button.setEnabled(True)
            return
        self.engagement_id_label.setText(str(engagement.id))
        self.engagement_name_label.setText(engagement.engagement_name)
        self.state_label.setText("已連結案件")
        if not self.request_page.load_engagement(engagement.id):
            raise AnnualWorkError("annual_work.workflow.page_read_failed")
        self.request_page.setEnabled(True)
        self.create_button.setEnabled(False)
        self.link_button.setEnabled(False)

    def reload(self, *, operation: str = "reload") -> bool:
        evidence = self._pending_evidence
        try:
            context, client, overview, summary = self._read_models()
            if evidence is not None:
                self._verify_evidence(evidence, context, overview)
            self._render_models(context, client, overview, summary)
            if evidence is not None and evidence.request_result is not None:
                request_id = evidence.request_result.request.id
                expected_item_ids = tuple(
                    row.id for row in evidence.request_result.items
                )
                if (
                    not self.request_page.select_request_id(request_id)
                    or self.request_page.item_ids() != expected_item_ids
                ):
                    raise AnnualWorkError(
                        "annual_work.workflow.page_readback_mismatch"
                    )
        except Exception as exc:
            self._set_failed(
                operation=operation,
                exc=exc,
                request_id=(
                    evidence.request_result.request.id
                    if evidence is not None and evidence.request_result is not None
                    else None
                ),
                engagement_id=(
                    evidence.engagement_id if evidence is not None else None
                ),
                committed=(
                    evidence is not None or self._pending_mutation_reload
                ),
            )
            return False
        self._pending_evidence = None
        self._pending_mutation_reload = False
        self.retry_button.hide()
        if operation == "reload":
            self.feedback_label.setText("索件資料已重新讀取。")
        return True

    def _verify_evidence(
        self,
        evidence: AnnualRequestCommitEvidence,
        context: object,
        overview: AnnualLinkedOverview,
    ) -> None:
        if (
            context.item.id != evidence.item.id
            or context.item.engagement_id != evidence.engagement_id
            or overview.engagement is None
            or overview.engagement.id != evidence.engagement_id
        ):
            raise AnnualWorkError("annual_work.workflow.readback_mismatch")
        if evidence.request_result is None:
            return
        expected = evidence.request_result
        request = self._container.doc_requests.get_request(expected.request.id)
        if request != expected.request:
            raise AnnualWorkError("annual_work.workflow.readback_mismatch")
        items = tuple(self._container.doc_requests.list_items(request.id))
        if items != expected.items:
            raise AnnualWorkError("annual_work.workflow.readback_mismatch")
        if request.id not in {row.id for row in overview.requests}:
            raise AnnualWorkError("annual_work.workflow.readback_mismatch")

    def _take_commit_evidence(
        self, evidence: AnnualRequestCommitEvidence
    ) -> AnnualRequestCommitAck:
        self.has_committed_change = True
        self._pending_evidence = evidence
        readback_succeeded = self.reload(operation=evidence.operation)
        if readback_succeeded:
            self.feedback_label.setText(
                "第一筆索件已建立並完成資料核對。"
                if evidence.operation == "create"
                else "既有案件已連結並完成資料核對。"
            )
        return AnnualRequestCommitAck(True, readback_succeeded)

    def _on_embedded_data_changed(self) -> None:
        self.has_committed_change = True
        self._pending_mutation_reload = True
        if self.reload(operation="embedded_mutation"):
            self.feedback_label.setText("索件資料已更新並重新核對。")

    def _open_create(self) -> None:
        if self._pending_evidence is not None:
            return
        dialog = CreateLinkedRequestDialog(
            self._container,
            self.item_id,
            commit_handler=self._take_commit_evidence,
            parent=self,
        )
        dialog.exec()
        if (
            dialog.committed_evidence is not None
            and not dialog.evidence_handed_off
        ):
            self._take_commit_evidence(dialog.committed_evidence)

    def _open_link(self) -> None:
        if self._pending_evidence is not None:
            return
        try:
            context = self._container.annual_work.get_item_context(self.item_id)
        except Exception as exc:
            self._set_failed(operation="link_load", exc=exc)
            return
        dialog = LinkExistingEngagementDialog(
            self._container,
            self.item_id,
            client_id=context.client_id,
            commit_handler=self._take_commit_evidence,
            parent=self,
        )
        dialog.exec()
        if (
            dialog.committed_evidence is not None
            and not dialog.evidence_handed_off
        ):
            self._take_commit_evidence(dialog.committed_evidence)
