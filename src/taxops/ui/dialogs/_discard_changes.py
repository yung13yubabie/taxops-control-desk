"""Nonblocking discard confirmation used by the client-entry dialogs."""
from collections.abc import Callable

from PySide6.QtWidgets import QDialog, QMessageBox


def confirm_discard(dialog: QDialog, discard: Callable[[], None]) -> None:
    """Keep the form open until the user explicitly discards its pending edits."""
    existing = getattr(dialog, "_discard_confirmation", None)
    if existing is not None:
        existing.raise_()
        existing.activateWindow()
        return
    question = QMessageBox(dialog)
    question.setWindowTitle("放棄未儲存的變更？")
    question.setText("尚有未儲存的輸入。放棄後將不會儲存這些變更。")
    question.setIcon(QMessageBox.Icon.Warning)
    question.setStandardButtons(
        QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
    )
    question.button(QMessageBox.StandardButton.Discard).setText("放棄變更")
    question.button(QMessageBox.StandardButton.Cancel).setText("繼續編輯")
    question.setDefaultButton(QMessageBox.StandardButton.Cancel)
    dialog._discard_confirmation = question

    def finished(result: int) -> None:
        dialog._discard_confirmation = None
        question.deleteLater()
        if result == QMessageBox.StandardButton.Discard:
            discard()

    question.finished.connect(finished)
    question.open()
