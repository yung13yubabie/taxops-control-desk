"""Attachment service: upload evidence files and manage their status."""

from __future__ import annotations

import logging
import mimetypes
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

from ..core.clock import now_iso
from ..repositories.attachments import AttachmentRow, AttachmentsRepository
from ..security.file_guard import (
    FileGuardError,
    check_extension,
    check_file_size,
    resolve_safe_path,
    sha256_file,
)
from .audit import AuditService


class AttachmentValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class UploadAttachmentInput:
    engagement_id: int
    request_id: int | None
    source_path: Path
    notes: str | None = None
    uploaded_by: str = "local_user"


class AttachmentsService:
    def __init__(
        self,
        repo: AttachmentsRepository,
        attachments_dir: Path,
        audit: AuditService,
    ) -> None:
        self._repo = repo
        self._attachments_dir = attachments_dir
        self._audit = audit

    def upload_attachment(self, inp: UploadAttachmentInput) -> AttachmentRow:
        source = Path(inp.source_path)
        ext = source.suffix.lower()

        try:
            check_extension(source.name)
        except FileGuardError as e:
            raise AttachmentValidationError(e.code) from e

        file_size = source.stat().st_size
        try:
            check_file_size(file_size)
        except FileGuardError as e:
            raise AttachmentValidationError(e.code) from e

        if not self._repo.engagement_exists(inp.engagement_id):
            raise AttachmentValidationError("attachment.engagement_not_found")

        if inp.request_id is not None and not self._repo.request_belongs_to_engagement(
            inp.request_id, inp.engagement_id
        ):
            raise AttachmentValidationError("attachment.request_not_found")

        file_hash = sha256_file(source)

        now = datetime.now(timezone.utc)
        rel_path = Path(f"{now.year:04d}") / f"{now.month:02d}" / f"{uuid.uuid4().hex}{ext}"

        try:
            dest = resolve_safe_path(self._attachments_dir, str(rel_path))
        except FileGuardError as e:
            raise AttachmentValidationError(e.code) from e

        mime_type, _ = mimetypes.guess_type(source.name)
        if mime_type is None:
            mime_type = "application/octet-stream"

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(dest))

        try:
            row = self._repo.insert_with_version(
                engagement_id=inp.engagement_id,
                request_id=inp.request_id,
                original_filename=source.name,
                stored_filename=str(rel_path),
                file_hash_sha256=file_hash,
                file_size=file_size,
                mime_type=mime_type,
                extension=ext,
                uploaded_by=inp.uploaded_by,
                source="manual",
                notes=inp.notes,
            )
            self._audit.record(
                action="attachment.upload",
                target_type="attachment",
                target_id=str(row.id),
                detail={
                    "original_filename": source.name,
                    "stored_filename": str(rel_path),
                    "file_size": file_size,
                    "engagement_id": inp.engagement_id,
                },
            )
        except Exception:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                _log.warning("upload_attachment: failed to clean up orphaned file %s", dest)
            raise

        return row

    def accept_attachment(
        self, attachment_id: int, accepted_by: str = "local_user"
    ) -> AttachmentRow:
        updated = self._update_status_or_raise(
            attachment_id,
            status="accepted",
            accepted_by=accepted_by,
            accepted_at=now_iso(),
        )
        self._audit.record(
            action="attachment.accept",
            target_type="attachment",
            target_id=str(attachment_id),
            detail={"accepted_by": accepted_by},
        )
        return updated

    def reject_attachment(self, attachment_id: int) -> AttachmentRow:
        updated = self._update_status_or_raise(attachment_id, status="rejected")
        self._audit.record(
            action="attachment.reject",
            target_type="attachment",
            target_id=str(attachment_id),
            detail=None,
        )
        return updated

    def delete_attachment(self, attachment_id: int) -> AttachmentRow:
        updated = self._update_status_or_raise(attachment_id, status="archived")
        self._audit.record(
            action="attachment.delete",
            target_type="attachment",
            target_id=str(attachment_id),
            detail={"status": "archived"},
        )
        return updated

    def get(self, attachment_id: int) -> AttachmentRow | None:
        return self._repo.get(attachment_id)

    def list_all(self) -> list[AttachmentRow]:
        return self._repo.list_all()

    def list_by_engagement(self, engagement_id: int) -> list[AttachmentRow]:
        return self._repo.list_by_engagement(engagement_id)

    def list_by_request(self, request_id: int) -> list[AttachmentRow]:
        return self._repo.list_by_request(request_id)

    def _update_status_or_raise(
        self, attachment_id: int, **kwargs
    ) -> AttachmentRow:
        if self._repo.get(attachment_id) is None:
            raise AttachmentValidationError("attachment.not_found")
        updated = self._repo.update_status(attachment_id=attachment_id, **kwargs)
        if updated is None:
            raise AttachmentValidationError("attachment.not_found")
        return updated
