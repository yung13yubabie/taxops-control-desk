"""Generated messages service: variable assembly, rendering, persistence, audit."""

from __future__ import annotations

from dataclasses import dataclass

from ..i18n.status_labels import status_to_label
from ..repositories.clients import ClientsRepository
from ..repositories.document_requests import DocumentRequestsRepository
from ..repositories.engagements import EngagementsRepository
from ..repositories.generated_messages import (
    GeneratedMessageRow,
    GeneratedMessagesRepository,
)
from .audit import AuditService
from .templates import TemplateValidationError, TemplatesService


class GeneratedMessageValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GenerateMessageInput:
    request_id: int
    template_id: int


class GeneratedMessagesService:
    def __init__(
        self,
        repo: GeneratedMessagesRepository,
        doc_requests_repo: DocumentRequestsRepository,
        engagements_repo: EngagementsRepository,
        clients_repo: ClientsRepository,
        templates_svc: TemplatesService,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._doc_requests_repo = doc_requests_repo
        self._engagements_repo = engagements_repo
        self._clients_repo = clients_repo
        self._templates_svc = templates_svc
        self._audit = audit

    def build_variables(self, request_id: int) -> dict[str, str]:
        """Assemble all ALLOWED_VARIABLES for a given document request."""
        request = self._doc_requests_repo.get_request(request_id)
        if request is None:
            raise GeneratedMessageValidationError("gen_message.request_not_found")

        engagement = self._engagements_repo.get(request.engagement_id)
        if engagement is None:
            raise GeneratedMessageValidationError("gen_message.engagement_not_found")

        client = self._clients_repo.get(engagement.client_id)
        if client is None:
            raise GeneratedMessageValidationError("gen_message.client_not_found")

        items = self._doc_requests_repo.list_items(request_id)
        missing = [i.item_name for i in items if i.item_status == "missing"]
        invalid = [i.item_name for i in items if i.item_status == "invalid"]
        incomplete = [i.item_name for i in items if i.item_status == "incomplete"]

        def _fmt(names: list[str]) -> str:
            return "\n".join(f"- {n}" for n in names)

        return {
            "client_name": client.client_name,
            "tax_id": client.tax_id or "",
            "contact_person": client.contact_name or "",
            "period_name": request.period_name,
            "tax_type_name": status_to_label(request.tax_type),
            "engagement_name": engagement.engagement_name,
            "missing_items": _fmt(missing),
            "invalid_items": _fmt(invalid),
            "incomplete_items": _fmt(incomplete),
            "due_date": request.due_date or "",
            "notes": request.notes or "",
        }

    def generate(self, payload: GenerateMessageInput) -> GeneratedMessageRow:
        """Render template with request variables and persist the result."""
        variables = self.build_variables(payload.request_id)
        try:
            body = self._templates_svc.render_template(payload.template_id, variables)
        except TemplateValidationError as err:
            raise GeneratedMessageValidationError(err.code) from err
        except Exception as err:
            raise GeneratedMessageValidationError("gen_message.render_failed") from err

        row = self._repo.insert(
            request_id=payload.request_id,
            template_id=payload.template_id,
            body=body,
        )
        self._audit.record(
            action="gen_message.create",
            target_type="generated_message",
            target_id=str(row.id),
            detail={
                "request_id": payload.request_id,
                "template_id": payload.template_id,
            },
        )
        return row

    def list_by_request(self, request_id: int) -> list[GeneratedMessageRow]:
        return self._repo.list_by_request(request_id)

    def get_message(self, message_id: int) -> GeneratedMessageRow | None:
        return self._repo.get(message_id)
