"""Message templates service: validation, Jinja2 rendering, audit log."""

from __future__ import annotations

from dataclasses import dataclass

import jinja2.nodes as _jinja_nodes
from jinja2 import Environment, StrictUndefined, Template, TemplateSyntaxError, UndefinedError, meta as _jinja_meta

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
    "notes",
})

VARIABLE_LABELS: dict[str, str] = {
    "client_name": "客戶名稱",
    "period_name": "申報期間",
    "tax_type_name": "稅目",
    "missing_items": "缺少文件",
    "invalid_items": "格式錯誤文件",
    "incomplete_items": "內容不完整文件",
    "due_date": "截止日",
    "tax_id": "統一編號",
    "contact_person": "聯絡人",
    "engagement_name": "案件名稱",
    "notes": "備註",
}

_LABEL_TO_VARIABLE = {label: key for key, label in VARIABLE_LABELS.items()}

# AST node types permitted in templates: pure text + simple variable references only.
# Anything else (attribute access, expressions, control flow, filters, calls) is rejected.
_SAFE_NODE_TYPES = frozenset({
    _jinja_nodes.Template,
    _jinja_nodes.Output,
    _jinja_nodes.TemplateData,
    _jinja_nodes.Name,
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

    @staticmethod
    def body_for_edit(body: str) -> str:
        """Convert stored engineering placeholders to user-facing labels."""
        edited = body
        for key, label in VARIABLE_LABELS.items():
            edited = edited.replace(f"{{{{ {key} }}}}", f"【{label}】")
            edited = edited.replace(f"{{{{{key}}}}}", f"【{label}】")
        return edited

    @staticmethod
    def _compile_body(body: str) -> str:
        compiled = body
        for label, key in _LABEL_TO_VARIABLE.items():
            compiled = compiled.replace(f"【{label}】", f"{{{{ {key} }}}}")
        return compiled

    def _validate_body(self, body: str) -> Template:
        if not body.strip():
            raise TemplateValidationError("template.body.required")
        compiled_body = self._compile_body(body)
        try:
            ast = self._env.parse(compiled_body)
        except TemplateSyntaxError as err:
            raise TemplateValidationError("template.body.syntax_error") from err
        for node in ast.find_all(_jinja_nodes.Node):
            if type(node) not in _SAFE_NODE_TYPES:
                raise TemplateValidationError("template.body.unsafe_expression")
        unknown = _jinja_meta.find_undeclared_variables(ast) - ALLOWED_VARIABLES
        if unknown:
            raise TemplateValidationError("template.unknown_variable")
        return self._env.from_string(compiled_body)

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
        Re-validates the stored body before rendering so that rows inserted
        outside the service (direct SQL, old data, migrations) cannot bypass
        the AST whitelist.
        """
        row = self._repo.get(template_id)
        if row is None:
            raise TemplateValidationError("template.not_found")
        tmpl = self._validate_body(row.body)
        safe_vars = {k: v for k, v in variables.items() if k in ALLOWED_VARIABLES}
        try:
            return tmpl.render(**safe_vars)
        except UndefinedError as err:
            raise TemplateValidationError("template.variable.missing") from err
        except Exception as err:
            raise TemplateValidationError("template.render.failed") from err
