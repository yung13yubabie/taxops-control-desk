from __future__ import annotations

from pathlib import Path

import pytest

from taxops.repositories.attachments import AttachmentsRepository
from taxops.services.attachments import (
    AttachmentValidationError,
    UploadAttachmentInput,
)


def _seed_owner(container, suffix: str) -> tuple[int, int, int]:
    now = "2026-01-01T00:00:00Z"
    client = container.conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at)"
        " VALUES (?, ?, ?, ?) RETURNING id",
        (f"ATT-{suffix}", f"Attachment owner {suffix}", now, now),
    ).fetchone()
    client_id = int(client["id"])
    engagement = container.conn.execute(
        "INSERT INTO engagements("
        " client_id, engagement_name, tax_type, period_name, status,"
        " created_at, updated_at"
        ") VALUES (?, ?, 'vat', '202601', 'draft', ?, ?) RETURNING id",
        (client_id, f"Engagement {suffix}", now, now),
    ).fetchone()
    engagement_id = int(engagement["id"])
    request = container.conn.execute(
        "INSERT INTO document_requests("
        " engagement_id, request_name, tax_type, period_name, status,"
        " created_at, updated_at"
        ") VALUES (?, ?, 'vat', '202601', 'not_requested', ?, ?) RETURNING id",
        (engagement_id, f"Request {suffix}", now, now),
    ).fetchone()
    request_id = int(request["id"])
    container.conn.commit()
    return client_id, engagement_id, request_id


def _insert_attachment(
    repo: AttachmentsRepository,
    *,
    engagement_id: int,
    request_id: int | None,
    index: int,
) -> int:
    row = repo.insert_with_version(
        engagement_id=engagement_id,
        request_id=request_id,
        original_filename=f"evidence-{index:03d}.pdf",
        stored_filename=f"2026/01/evidence-{index:03d}.pdf",
        file_hash_sha256=f"{index:064x}",
        file_size=index + 1,
        mime_type="application/pdf",
        extension=".pdf",
    )
    return row.id


def test_bounded_attachment_pages_reach_201_without_duplicates_and_count_exact(
    container,
) -> None:
    _client_a, engagement_a, request_a = _seed_owner(container, "A")
    _client_b, engagement_b, request_b = _seed_owner(container, "B")
    repo = container.attachments._repo
    with container.conn:
        request_a_ids = [
            _insert_attachment(
                repo,
                engagement_id=engagement_a,
                request_id=request_a,
                index=index,
            )
            for index in range(201)
        ]
        engagement_only_id = _insert_attachment(
            repo,
            engagement_id=engagement_a,
            request_id=None,
            index=500,
        )
        _insert_attachment(
            repo,
            engagement_id=engagement_b,
            request_id=request_b,
            index=600,
        )

    first = container.attachments.page_by_request(
        request_a, limit=200, offset=0
    )
    second = container.attachments.page_by_request(
        request_a, limit=200, offset=200
    )

    assert container.attachments.count_by_request(request_a) == 201
    assert len(first) == 200
    assert [row.id for row in second] == [request_a_ids[0]]
    assert not ({row.id for row in first} & {row.id for row in second})
    assert [row.id for row in first] == list(reversed(request_a_ids[1:]))

    engagement_page = container.attachments.page_by_engagement(
        engagement_a, limit=2, offset=200
    )
    assert container.attachments.count_by_engagement(engagement_a) == 202
    assert [row.id for row in engagement_page] == [
        request_a_ids[1],
        request_a_ids[0],
    ]
    assert engagement_only_id not in {row.id for row in engagement_page}

    all_first = container.attachments.page_all(limit=200, offset=0)
    all_second = container.attachments.page_all(limit=200, offset=200)
    assert container.attachments.count_all() == 203
    assert len(all_first) == 200
    assert len(all_second) == 3
    assert not ({row.id for row in all_first} & {row.id for row in all_second})


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("page_all", ()),
        ("page_by_engagement", (1,)),
        ("page_by_request", (1,)),
    ],
)
@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0, "offset": 0},
        {"limit": 201, "offset": 0},
        {"limit": True, "offset": 0},
        {"limit": 20, "offset": -1},
        {"limit": 20, "offset": 1_000_001},
        {"limit": 20, "offset": False},
    ],
)
def test_attachment_service_rejects_invalid_pagination(
    container, method_name: str, args: tuple[int, ...], kwargs: dict[str, object]
) -> None:
    method = getattr(container.attachments, method_name)

    with pytest.raises(AttachmentValidationError) as exc:
        method(*args, **kwargs)

    assert exc.value.code == "attachment.pagination.invalid"


def test_attachment_repository_rejects_direct_pagination_bypass(container) -> None:
    repo = container.attachments._repo

    with pytest.raises(ValueError, match="attachment.pagination.invalid"):
        repo.page_all(limit=201, offset=0)
    with pytest.raises(ValueError, match="attachment.pagination.invalid"):
        repo.page_by_engagement(1, limit=1, offset=1_000_001)
    with pytest.raises(ValueError, match="attachment.pagination.invalid"):
        repo.page_by_request(1, limit=False, offset=0)


def test_deleted_request_attachment_is_history_only_and_mutations_are_blocked(
    container, tmp_path: Path
) -> None:
    _client_id, engagement_id, request_id = _seed_owner(container, "HISTORY")
    source = tmp_path / "request-evidence.pdf"
    source.write_bytes(b"preserved request evidence")
    attachment = container.attachments.upload_attachment(
        UploadAttachmentInput(
            engagement_id=engagement_id,
            request_id=request_id,
            source_path=source,
        )
    )
    container.conn.execute(
        "UPDATE document_requests SET deleted_at = ? WHERE id = ?",
        ("2026-01-02T00:00:00Z", request_id),
    )
    container.conn.commit()

    assert container.attachments.get(attachment.id) is None
    assert container.attachments.list_all() == []
    assert container.attachments.list_by_engagement(engagement_id) == []
    assert container.attachments.list_by_request(request_id) == []
    assert container.attachments.count_all() == 0
    assert container.attachments.count_by_engagement(engagement_id) == 0
    assert container.attachments.count_by_request(request_id) == 0
    with pytest.raises(AttachmentValidationError) as active_path:
        container.attachments.resolve_file_path(attachment.id)
    assert active_path.value.code == "attachment.not_found"

    history = container.attachments.page_request_history_attachments(
        engagement_id,
        request_id,
        limit=20,
        offset=0,
    )
    assert history == [attachment]
    assert (
        container.attachments.count_request_history_attachments(
            engagement_id, request_id
        )
        == 1
    )
    assert (
        container.attachments.resolve_request_history_file_path(
            engagement_id, request_id, attachment.id
        ).read_bytes()
        == b"preserved request evidence"
    )
    assert container.conn.execute(
        "SELECT COUNT(*) FROM attachment_versions WHERE attachment_id = ?",
        (attachment.id,),
    ).fetchone()[0] == 1

    for mutation_name in (
        "accept_attachment",
        "reject_attachment",
        "delete_attachment",
    ):
        with pytest.raises(AttachmentValidationError) as mutation:
            getattr(container.attachments, mutation_name)(attachment.id)
        assert mutation.value.code == "attachment.not_found"

    stored = container.conn.execute(
        "SELECT status, stored_filename FROM attachments WHERE id = ?",
        (attachment.id,),
    ).fetchone()
    assert stored["status"] == "uploaded"
    assert stored["stored_filename"] == attachment.stored_filename
    assert container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs"
        " WHERE target_type = 'attachment' AND target_id = ?"
        " AND action IN ('attachment.accept', 'attachment.reject',"
        " 'attachment.delete')",
        (str(attachment.id),),
    ).fetchone()[0] == 0


def test_deleted_request_blocks_repository_status_bypass(container) -> None:
    _client_id, engagement_id, request_id = _seed_owner(container, "REPO")
    repo = container.attachments._repo
    with container.conn:
        attachment_id = _insert_attachment(
            repo,
            engagement_id=engagement_id,
            request_id=request_id,
            index=1,
        )
    container.conn.execute(
        "UPDATE document_requests SET deleted_at = ? WHERE id = ?",
        ("2026-01-02T00:00:00Z", request_id),
    )
    container.conn.commit()

    assert repo.update_status(attachment_id, "accepted") is None
    assert container.conn.execute(
        "SELECT status FROM attachments WHERE id = ?", (attachment_id,)
    ).fetchone()["status"] == "uploaded"


def test_archived_attachment_file_and_version_remain_in_request_history(
    container, tmp_path: Path
) -> None:
    _client_id, engagement_id, request_id = _seed_owner(container, "ARCHIVED")
    source = tmp_path / "archived-evidence.pdf"
    source.write_bytes(b"archived but preserved")
    attachment = container.attachments.upload_attachment(
        UploadAttachmentInput(
            engagement_id=engagement_id,
            request_id=request_id,
            source_path=source,
        )
    )
    archived = container.attachments.delete_attachment(attachment.id)
    container.conn.execute(
        "UPDATE document_requests SET deleted_at = ? WHERE id = ?",
        ("2026-01-02T00:00:00Z", request_id),
    )
    container.conn.commit()

    assert container.attachments.page_request_history_attachments(
        engagement_id, request_id, limit=20, offset=0
    ) == [archived]
    assert (
        container.attachments.resolve_request_history_file_path(
            engagement_id, request_id, attachment.id
        ).read_bytes()
        == b"archived but preserved"
    )
    assert container.conn.execute(
        "SELECT COUNT(*) FROM attachment_versions WHERE attachment_id = ?",
        (attachment.id,),
    ).fetchone()[0] == 1


def test_history_read_enforces_exact_request_engagement_and_active_owner(
    container, tmp_path: Path
) -> None:
    client_id, engagement_id, request_id = _seed_owner(container, "OWNER")
    _other_client, other_engagement, _other_request = _seed_owner(
        container, "OTHER"
    )
    source = tmp_path / "owner-evidence.pdf"
    source.write_bytes(b"owner evidence")
    attachment = container.attachments.upload_attachment(
        UploadAttachmentInput(
            engagement_id=engagement_id,
            request_id=request_id,
            source_path=source,
        )
    )
    container.conn.execute(
        "UPDATE document_requests SET deleted_at = ? WHERE id = ?",
        ("2026-01-02T00:00:00Z", request_id),
    )
    container.conn.commit()

    with pytest.raises(AttachmentValidationError) as mismatch:
        container.attachments.page_request_history_attachments(
            other_engagement, request_id, limit=20, offset=0
        )
    assert mismatch.value.code == "attachment.request_not_found"
    with pytest.raises(AttachmentValidationError) as file_mismatch:
        container.attachments.resolve_request_history_file_path(
            other_engagement, request_id, attachment.id
        )
    assert file_mismatch.value.code == "attachment.request_not_found"

    container.conn.execute(
        "UPDATE clients SET deleted_at = ? WHERE id = ?",
        ("2026-01-03T00:00:00Z", client_id),
    )
    container.conn.commit()

    with pytest.raises(AttachmentValidationError) as deleted_owner:
        container.attachments.page_request_history_attachments(
            engagement_id, request_id, limit=20, offset=0
        )
    assert deleted_owner.value.code == "attachment.request_not_found"


def test_upload_to_deleted_request_is_blocked_before_file_or_audit(
    container, tmp_path: Path
) -> None:
    _client_id, engagement_id, request_id = _seed_owner(container, "UPLOAD")
    container.conn.execute(
        "UPDATE document_requests SET deleted_at = ? WHERE id = ?",
        ("2026-01-02T00:00:00Z", request_id),
    )
    container.conn.commit()
    source = tmp_path / "blocked.pdf"
    source.write_bytes(b"must not copy")

    with pytest.raises(AttachmentValidationError) as exc:
        container.attachments.upload_attachment(
            UploadAttachmentInput(
                engagement_id=engagement_id,
                request_id=request_id,
                source_path=source,
            )
        )

    assert exc.value.code == "attachment.request_not_found"
    assert container.conn.execute(
        "SELECT COUNT(*) FROM attachments"
    ).fetchone()[0] == 0
    assert container.conn.execute(
        "SELECT COUNT(*) FROM attachment_versions"
    ).fetchone()[0] == 0
    assert container.conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'attachment.upload'"
    ).fetchone()[0] == 0
    assert [
        path
        for path in container.paths.attachments_dir.rglob("*")
        if path.is_file()
    ] == []
