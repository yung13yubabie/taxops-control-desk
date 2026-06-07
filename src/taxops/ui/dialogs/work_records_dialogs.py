"""Dialogs for the Work Records page."""

from __future__ import annotations

from collections.abc import Callable

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

from ...i18n import error_message
from ...services.work_records import (
    CreateWorkflowTemplateInput,
    WorkRecordValidationError,
    WorkflowStageInput,
    WorkflowStepInput,
)


def format_stages_for_editor(stages: list[dict]) -> str:
    lines: list[str] = []
    for stage in stages:
        lines.append(str(stage.get("title") or "未命名階段"))
        for item in stage.get("items", []):
            prefix = "- [x]" if item.get("done") else "-"
            lines.append(f"{prefix} {item.get('text') or ''}".rstrip())
        lines.append("")
    return "\n".join(lines).strip()


def _parse_stage_text(text: str) -> tuple[WorkflowStageInput, ...]:
    stages: list[WorkflowStageInput] = []
    block: list[str] = []
    block_has_marker_steps = False

    def flush_block(lines: list[str]) -> None:
        if not lines:
            return
        title = _clean_stage_line(lines[0]) or "未命名階段"
        steps = [
            WorkflowStepInput(step)
            for step in (_clean_step_line(line) for line in lines[1:])
            if step
        ]
        stages.append(WorkflowStageInput(title=title, steps=tuple(steps)))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_block(block)
            block = []
            block_has_marker_steps = False
            continue
        if block and block_has_marker_steps and not _looks_like_marker_step(line):
            flush_block(block)
            block = [line]
            block_has_marker_steps = False
            continue
        block.append(line)
        if _looks_like_marker_step(line):
            block_has_marker_steps = True
    flush_block(block)
    return tuple(stages)


def _looks_like_marker_step(line: str) -> bool:
    step = line.strip()
    return (
        step.startswith(("-", "*", "[x]", "[X]", "[ ]"))
        or (len(step) > 2 and step[0].isdigit() and step[1] in (".", "、"))
    )


def _clean_stage_line(line: str) -> str:
    return line.strip().rstrip(":：").strip()


def _clean_step_line(line: str) -> str:
    step = line.strip()
    if step.startswith(("-", "*")):
        step = step[1:].strip()
    if step.startswith("[x]") or step.startswith("[X]") or step.startswith("[ ]"):
        step = step[3:].strip()
    if len(step) > 2 and step[0].isdigit() and step[1] in (".", "、"):
        step = step[2:].strip()
    return step


class WorkflowTemplateDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        name: str = "",
        stages_text: str = "",
        on_submit: Callable[[CreateWorkflowTemplateInput], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_submit = on_submit
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(680)
        self.setMinimumHeight(520)

        outer = QVBoxLayout(self)
        form = QFormLayout()
        self._name = QLineEdit(name)
        self._name.setMaxLength(200)
        form.addRow("流程名稱", self._name)
        outer.addLayout(form)

        self._stages = QTextEdit()
        self._stages.setPlainText(stages_text)
        self._stages.setPlaceholderText(
            "前期準備\n"
            "確認公司名稱\n"
            "確認負責人資料\n\n"
            "正式送件\n"
            "檢查附件\n"
            "送件並記錄收件號"
        )
        outer.addWidget(QLabel("流程格式：空行分階段；每段第一行是階段名稱，後面每行是一個步驟。"))
        outer.addWidget(self._stages, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        _ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        _ok.setDefault(True)
        outer.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.setTabOrder(self._name, self._stages)
        self.setTabOrder(self._stages, _ok)

    def accept(self) -> None:
        payload = self.payload()
        try:
            if self._on_submit is not None:
                self._on_submit(payload)
            else:
                self._validate_payload(payload)
        except WorkRecordValidationError as err:
            QMessageBox.warning(self, "儲存失敗", error_message(err.code))
            self._focus_validation_error(err.code)
            return
        super().accept()

    @staticmethod
    def _validate_payload(payload: CreateWorkflowTemplateInput) -> None:
        if not payload.name.strip():
            raise WorkRecordValidationError("work_record.template.name.required")
        if not payload.stages:
            raise WorkRecordValidationError("work_record.stage.required")

    def _focus_validation_error(self, code: str) -> None:
        if code == "work_record.template.name.required":
            self._name.setFocus()
        else:
            self._stages.setFocus()

    def payload(self) -> CreateWorkflowTemplateInput:
        return CreateWorkflowTemplateInput(
            name=self._name.text(),
            stages=_parse_stage_text(self._stages.toPlainText()),
        )
