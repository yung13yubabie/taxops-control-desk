"""Message templates service: validation, Jinja2 rendering, audit log."""

from __future__ import annotations

from dataclasses import dataclass

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError, meta as _jinja_meta

from ..core.text import sanitize_user_text
from ..repositories.templates import TemplateRow, TemplatesRepository
from .audit import AuditService

VALID_TEMPLATE_TYPES = frozenset({
    "initial_request",
    "follow_up",
    "custom",
})

ALLOWED_VARIABLES = frozenset({
    "client_name",
    "period_name",
    "tax_type_name",
    "missing_items",
    "invalid_items",
    "incomplete_items",
    "due_date",
    "tax_id",
    "contact_person",
    "engagement_name",
    "payment_due_date",
    "office_owner",
    "reviewer",
    "last_followed_up_at",
    "notes",
})


class TemplateValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CreateTemplateInput:
    name: str
    template_type: str = "custom"
    body: str = ""


@dataclass(frozen=True)
class UpdateTemplateInput:
    name: str
    template_type: str
    body: str


class TemplatesService:
    def __init__(self, repo: TemplatesRepository, audit: AuditService) -> None:
        self._repo = repo
        self._audit = audit
        self._env = Environment(undefined=StrictUndefined)

    def _validate_body(self, body: str) -> None:
        if not body.strip():
            raise TemplateValidationError("template.body.required")
        try:
            ast = self._env.parse(body)
        except TemplateSyntaxError as err:
            raise TemplateValidationError("template.body.syntax_error") from err
        unknown = _jinja_meta.find_undeclared_variables(ast) - ALLOWED_VARIABLES
        if unknown:
            raise TemplateValidationError("template.unknown_variable")

    def create_template(self, payload: CreateTemplateInput) -> TemplateRow:
        name = sanitize_user_text(payload.name, max_length=200)
        if not name:
            raise TemplateValidationError("template.name.required")
        if payload.template_type not in VALID_TEMPLATE_TYPES:
            raise TemplateValidationError("template.type.invalid")
        body = sanitize_user_text(payload.body, max_length=10000)
        self._validate_body(body)

        row = self._repo.insert(name=name, template_type=payload.template_type, body=body)
        self._audit.record(
            action="template.create",
            target_type="template",
            target_id=str(row.id),
            detail={"name": row.name, "template_type": row.template_type},
        )
        return row

    def update_template(self, template_id: int, payload: UpdateTemplateInput) -> TemplateRow:
        existing = self._repo.get(template_id)
        if existing is None:
            raise TemplateValidationError("template.not_found")
        if existing.is_builtin:
            raise TemplateValidationError("template.builtin.readonly")

        name = sanitize_user_text(payload.name, max_length=200)
        if not name:
            raise TemplateValidationError("template.name.required")
        if payload.template_type not in VALID_TEMPLATE_TYPES:
            raise TemplateValidationError("template.type.invalid")
        body = sanitize_user_text(payload.body, max_length=10000)
        self._validate_body(body)

        row = self._repo.update(template_id, name=name, template_type=payload.template_type, body=body)
        if row is None:
            raise TemplateValidationError("template.not_found")
        self._audit.record(
            action="template.update",
            target_type="template",
            target_id=str(template_id),
            detail={"name": row.name},
        )
        return row

    def delete_template(self, template_id: int) -> None:
        existing = self._repo.get(template_id)
        if existing is None:
            raise TemplateValidationError("template.not_found")
        if existing.is_builtin:
            raise TemplateValidationError("template.builtin.readonly")
        self._repo.delete(template_id)
        self._audit.record(
            action="template.delete",
            target_type="template",
            target_id=str(template_id),
            detail={"name": existing.name},
        )

    def get_template(self, template_id: int) -> TemplateRow | None:
        return self._repo.get(template_id)

    def list_all(self) -> list[TemplateRow]:
        return self._repo.list_all()

    def render_template(self, template_id: int, variables: dict[str, str]) -> str:
        """Render a template with provided variables.

        Only keys in ALLOWED_VARIABLES are passed to Jinja2.
        Unknown variable names are rejected at create/update time.
        """
        row = self._repo.get(template_id)
        if row is None:
            raise TemplateValidationError("template.not_found")
        safe_vars = {k: v for k, v in variables.items() if k in ALLOWED_VARIABLES}
        try:
            tmpl = self._env.from_string(row.body)
            return tmpl.render(**safe_vars)
        except UndefinedError as err:
            raise TemplateValidationError("template.variable.missing") from err
        except Exception as err:
            raise TemplateValidationError("template.render.failed") from err
