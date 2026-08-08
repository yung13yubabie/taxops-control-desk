"""Contracts for `docs/no_silent_failure.md`.

The invariant under test: empty is a valid business state, error is a system state, and
the two must not share a representation. A corrupt stored value is an error, so it may
not arrive at the caller looking like "there is nothing here".

Each test names the consequence the silence had, not just the shape of the return value
— a test that only asserts "it raises" gets deleted the first time raising is
inconvenient.
"""

from __future__ import annotations

import json

import pytest

from taxops.i18n import error_message
from taxops.services.work_records import (
    WorkRecordValidationError,
    _load_context_snapshot,
)


# ── An absent snapshot is a valid state ─────────────────────────────


@pytest.mark.parametrize("absent", [None, "", "   "])
def test_absent_snapshot_is_an_empty_mapping_not_an_error(absent: str | None) -> None:
    """No snapshot stored is a real answer, and must stay cheap to ask for."""
    if absent == "   ":
        # A whitespace-only column is still JSON-invalid; only None and "" are absent.
        with pytest.raises(WorkRecordValidationError):
            _load_context_snapshot(absent)
        return
    assert _load_context_snapshot(absent) == {}


def test_valid_snapshot_round_trips() -> None:
    payload = {"image_path": "workflow/a.png", "image_width": 800}
    assert _load_context_snapshot(json.dumps(payload)) == payload


# ── A corrupt snapshot is an error, not an empty one ────────────────


def test_corrupt_json_raises_instead_of_returning_empty() -> None:
    """Returning {} here let a still-referenced image look unreferenced.

    `_image_paths` collects `image_path` from the snapshot alongside stage paths, and
    `_remove_asset_if_unreferenced` deletes any asset absent from that set. An empty
    mapping silently dropped the snapshot's own image from the referenced set.
    """
    with pytest.raises(WorkRecordValidationError) as caught:
        _load_context_snapshot("{not json at all")
    assert caught.value.args[0] == "work_record.context_snapshot.invalid"


@pytest.mark.parametrize("wrong_shape", ["[]", '"a string"', "42", "null", "true"])
def test_snapshot_of_the_wrong_type_raises(wrong_shape: str) -> None:
    """Schema mismatch is INVALID_DATA. Valid JSON of the wrong shape is still wrong."""
    with pytest.raises(WorkRecordValidationError):
        _load_context_snapshot(wrong_shape)


def test_the_error_code_has_a_human_message() -> None:
    """An error the user cannot read is still a silent failure."""
    message = error_message("work_record.context_snapshot.invalid")
    assert message
    assert "context_snapshot" not in message  # no raw identifiers
    assert message != error_message("unknown.code.that.does.not.exist")


def test_snapshot_and_stages_agree_on_corrupt_input() -> None:
    """Both parsers run side by side in `_image_paths`; disagreeing is the bug.

    Stages raised on corrupt JSON while the snapshot returned {}, so one code path
    abandoned a delete safely and the other proceeded on a partial path set.
    """
    from taxops.services.work_records import _loads_stages

    with pytest.raises(WorkRecordValidationError):
        _loads_stages("{not json")
    with pytest.raises(WorkRecordValidationError):
        _load_context_snapshot("{not json")


# ── The consequence: corrupt data must not delete a file ────────────


def test_corrupt_snapshot_does_not_orphan_a_referenced_image(container) -> None:
    """The behaviour the raise protects: a delete is abandoned, not guessed at.

    `_remove_asset_if_unreferenced` already caught WorkRecordValidationError and
    returned without deleting, citing the risk of removing an asset still in use. That
    guard never fired for a corrupt snapshot, because the snapshot loader swallowed the
    error. This asserts the guard now covers both.
    """
    service = container.work_records
    conn = service._conn

    # Build the path directly: _safe_workflow_asset_path refuses a path whose file does
    # not exist yet, so it cannot tell us where to create one.
    asset_rel = "workflow/still-in-use.png"
    asset_path = service.workflow_assets_dir / "workflow" / "still-in-use.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"not a real png, presence is what matters")
    assert asset_path.exists()

    # A row whose snapshot is corrupt but whose stages are valid: the only place the
    # image is recorded is unreadable.
    conn.execute(
        "INSERT INTO workflow_templates_v2"
        " (name, stages_json, context_snapshot, created_at, updated_at)"
        " VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        ("corrupt snapshot template", "[]", "{broken json"),
    )
    conn.commit()

    service._remove_asset_if_unreferenced(asset_rel)

    assert asset_path.exists(), (
        "a corrupt snapshot must abandon the delete, not treat the asset as an orphan"
    )
