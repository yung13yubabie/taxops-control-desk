"""ExportService: produce XLSX exports from the document-requests data."""

from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from ..repositories.document_requests import DocumentRequestsRepository
from ..security.csv_guard import safe_spreadsheet_cell
from .audit import AuditService

_HEADERS = (
    "客戶代號",
    "客戶名稱",
    "統一編號",
    "案件名稱",
    "稅目",
    "期別",
    "缺件項目",
    "狀態",
    "負責人",
    "到期日",
    "上次催件日",
    "催件次數",
    "備註",
)

_ROW_FIELDS = (
    "client_code",
    "client_name",
    "tax_id",
    "engagement_name",
    "tax_type",
    "period_name",
    "item_name",
    "item_status",
    "owner",
    "due_date",
    "requested_at",
    "follow_up_count",
    "notes",
)


class ExportValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ExportService:
    def __init__(
        self,
        repo: DocumentRequestsRepository,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._audit = audit

    def export_missing_items_xlsx(
        self,
        output_path: Path,
        engagement_id: int | None = None,
    ) -> int:
        """Write a missing-items XLSX to *output_path*.

        Returns the number of data rows written.
        Raises ExportValidationError on error.
        """
        try:
            rows = self._repo.list_missing_items_for_export(engagement_id)
        except Exception as exc:
            raise ExportValidationError("export.query_failed") from exc

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "缺件清單"

        ws.append(list(_HEADERS))
        for cell in ws[1]:
            cell.font = Font(bold=True)

        for row in rows:
            ws.append([
                safe_spreadsheet_cell(str(row.get(field, "") or ""))
                for field in _ROW_FIELDS
            ])

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            wb.save(str(output_path))
        except Exception as exc:
            raise ExportValidationError("export.save_failed") from exc

        self._audit.record(
            action="export.missing_items",
            target_type="export",
            target_id=str(output_path.name),
            detail={"rows": len(rows), "engagement_id": engagement_id},
        )
        return len(rows)
