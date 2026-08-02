"""Scrollable atomic client-profile update dialog."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...i18n import BUTTON_LABELS, error_message
from ...repositories.clients import ClientRow
from ...services.client_leases import LeaseInput
from ...services.client_profiles import ClientProfileValidationError
from ...services.clients import ClientValidationError, ClientsService, UpdateClientInput
from ..widgets.client_leases_editor import ClientLeasesEditor
from ..widgets.client_profile_form import ClientProfileForm
from ..widgets.date_field import DateField

_log = logging.getLogger(__name__)


class EditClientDialog(QDialog):
    def __init__(
        self,
        services: object,
        client: ClientRow,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = services if hasattr(services, "client_profiles") else None
        self._clients: ClientsService = (
            services.clients if self._container is not None else services
        )  # type: ignore[assignment]
        self._client_id = client.id
        self.setWindowTitle("編輯客戶")
        self.setModal(True)
        self.resize(760, 720)
        self.setMinimumSize(620, 420)

        leases = []
        lease_load_failed = False
        if self._container is not None:
            try:
                leases = self._container.client_leases.list_for_client(
                    client.id, include_deleted=True
                )
            except Exception:
                lease_load_failed = True
                _log.error("client leases load failed", exc_info=True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        outer.setSpacing(12)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(14)

        profile_group = QGroupBox("客戶基本與聯絡資料")
        profile_layout = QVBoxLayout(profile_group)
        self.profile_form = ClientProfileForm(client)
        profile_layout.addWidget(self.profile_form)
        content_layout.addWidget(profile_group)

        lease_group = QGroupBox("租約明細")
        lease_layout = QVBoxLayout(lease_group)
        self.leases_editor = ClientLeasesEditor(
            None if lease_load_failed else self._container,
            client_id=client.id,
            leases=leases,
        )
        if lease_load_failed:
            self.leases_editor.availability_label.setText(
                "租約資料載入失敗，為避免覆蓋既有資料，本次無法編輯租約。"
            )
        lease_layout.addWidget(self.leases_editor)
        content_layout.addWidget(lease_group)
        content_layout.addStretch(1)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton(BUTTON_LABELS["client_dialog.cancel"])
        self.save_button = QPushButton("儲存變更")
        self.save_button.setDefault(True)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        outer.addLayout(actions)
        self.save_button.clicked.connect(self.on_save)
        self.cancel_button.clicked.connect(self.reject)

        form = self.profile_form
        self._client_code = form.client_code
        self._client_name = form.client_name
        self._tax_id = form.tax_id
        self._short_name = form.short_name
        self._contact_name = form.contact_name
        self._contact_phone = form.contact_phone
        self._contact_email = form.contact_email
        self._address = form.registered_address
        self._note = form.note
        self._save_btn = self.save_button
        self.lease_table = self.leases_editor.table
        self.add_lease_button = self.leases_editor.add_button
        self.lease_availability_label = self.leases_editor.availability_label
        self._lease_start = DateField(required=False, parent=content)
        self._lease_start.set_value(client.lease_start)
        self._lease_end = DateField(required=False, parent=content)
        self._lease_end.set_value(client.lease_end)
        self._lease_start.hide()
        self._lease_end.hide()

    def add_staged_lease(self, payload: LeaseInput) -> None:
        if self._container is None:
            raise RuntimeError("multiple leases require ServiceContainer")
        self.leases_editor.add_payload(payload)

    def stage_lease_update(self, lease_id: int, payload: LeaseInput) -> None:
        self.leases_editor.stage_update(lease_id, payload)

    def stage_lease_archive(self, lease_id: int) -> None:
        self.leases_editor.stage_archive(lease_id)

    def _payload(self) -> UpdateClientInput:
        values = self.profile_form.values_for_save()
        return UpdateClientInput(
            **values,
            lease_start=self._lease_start.validated_value() if self._container is None else None,
            lease_end=self._lease_end.validated_value() if self._container is None else None,
        )

    def on_save(self) -> None:
        if not self.save_button.isEnabled():
            return
        self.save_button.setEnabled(False)
        try:
            payload = self._payload()
            if self._container is None:
                self._clients.update_client(self._client_id, payload)
            else:
                self._container.client_profiles.update_client_with_lease_changes(
                    self._client_id, payload, self.leases_editor.changes()
                )
        except DateField.InvalidInput:
            return self._save_failed(None)
        except (ClientValidationError, ClientProfileValidationError) as exc:
            self.profile_form.focus_for_error(exc.code)
            return self._save_failed(error_message(exc.code))
        except Exception:
            _log.error("client profile update failed", exc_info=True)
            return self._save_failed("客戶與租約未更新，請檢查資料後再試。")
        self.accept()

    def _save_failed(self, message: str | None) -> None:
        if message:
            QMessageBox.warning(self, "更新失敗", message)
        self.save_button.setEnabled(True)

    def on_cancel(self) -> None:
        self.reject()

    def _focus_first_invalid(self, code: str) -> None:
        self.profile_form.focus_for_error(code)
