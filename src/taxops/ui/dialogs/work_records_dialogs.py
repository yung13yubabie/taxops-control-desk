"""Dialogs for the Work Records page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...services.work_records import (
    CreateWorkflowTemplateInput,
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
    title: str | None = None
    steps: list[WorkflowStepInput] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("-", "*")):
            step = line[1:].strip()
            if step.startswith("[x]") or step.startswith("[ ]"):
                step = step[3:].strip()
            if step:
                steps.append(WorkflowStepInput(step))
            continue
        if title is not None:
            stages.append(WorkflowStageInput(title=title, steps=tuple(steps)))
        title = line
        steps = []
    if title is not None:
        stages.append(WorkflowStageInput(title=title, steps=tuple(steps)))
    return tuple(stages)


class WorkflowTemplateDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        name: str = "",
        stages_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
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
            "- 確認公司名稱\n"
            "- 確認負責人資料\n\n"
            "正式送件\n"
            "- 檢查附件\n"
            "- 送件並記錄收件號"
        )
        outer.addWidget(QLabel("階段與步驟：每個階段一行，步驟用 - 開頭"))
        outer.addWidget(self._stages, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        outer.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def payload(self) -> CreateWorkflowTemplateInput:
        return CreateWorkflowTemplateInput(
            name=self._name.text(),
            stages=_parse_stage_text(self._stages.toPlainText()),
        )
