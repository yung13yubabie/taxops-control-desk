from __future__ import annotations

import pytest

from taxops.services.client_leases import (
    ClientLeaseValidationError,
    LeaseInput,
    validate_lease_input,
)
from taxops.services.clients import CreateClientInput


def _client(container, code: str = "L001"):
    return container.clients.create_client(
        CreateClientInput(client_code=code, client_name="中文租約客戶")
    )


def _lease(**overrides) -> LeaseInput:
    values = {
        "lease_name": "台北辦公室",
        "premises_address": "台北市中山區一號",
        "landlord_name": "王房東",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "monthly_rent": 30000,
        "deposit_amount": 60000,
        "reminder_days": 60,
        "status": "active",
        "notes": "第一行\n第二行：保留中文",
    }
    values.update(overrides)
    return LeaseInput(**values)


def test_create_and_list_lease_maps_all_fields(container):
    client = _client(container)

    created = container.client_leases.create_lease(client.id, _lease())

    assert created.client_id == client.id
    assert created.lease_name == "台北辦公室"
    assert created.notes == "第一行\n第二行：保留中文"
    assert created.deleted_at is None
    assert container.client_leases.list_for_client(client.id) == [created]


def test_plan_public_create_accepts_positional_notes_with_default_status(container):
    client = _client(container)
    row = container.client_leases.create(
        client.id,
        LeaseInput(
            "分公司",
            "台中市一號",
            "李房東",
            "2026-01-01",
            "2027-12-31",
            22000,
            44000,
            90,
            "中文備註",
        ),
    )
    assert row.status == "active"
    assert row.notes == "中文備註"


def test_lease_validation_has_stable_error_code(container):
    client = _client(container)

    with pytest.raises(ClientLeaseValidationError) as exc:
        container.client_leases.create_lease(
            client.id, _lease(end_date="2025-12-31")
        )

    assert exc.value.code == "client_lease.date_range.invalid"


def test_edit_overlap_sort_and_archive_history(container):
    client = _client(container)
    later = container.client_leases.create_lease(
        client.id, _lease(lease_name="後建立", start_date="2026-06-01")
    )
    earlier = container.client_leases.create_lease(
        client.id,
        _lease(lease_name="重疊租約", start_date="2026-01-01", end_date="2026-09-30"),
    )

    assert [row.id for row in container.client_leases.list_for_client(client.id)] == [
        earlier.id,
        later.id,
    ]
    edited = container.client_leases.update_lease(
        later.id, _lease(lease_name="已編輯", start_date="2026-06-01")
    )
    assert edited.lease_name == "已編輯"

    archived = container.client_leases.archive_lease(earlier.id)
    assert archived.deleted_at is not None
    assert container.client_leases.list_for_client(client.id) == [edited]
    assert [row.id for row in container.client_leases.list_for_client(
        client.id, include_deleted=True
    )] == [earlier.id, later.id]


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"lease_name": " \t "}, "client_lease.name.required"),
        ({"start_date": "2026-02-30"}, "client_lease.date.invalid"),
        ({"monthly_rent": -1}, "client_lease.amount.invalid"),
        ({"deposit_amount": -1}, "client_lease.amount.invalid"),
        ({"reminder_days": -1}, "client_lease.reminder_days.invalid"),
        ({"reminder_days": 3651}, "client_lease.reminder_days.invalid"),
        ({"status": "unknown"}, "client_lease.status.invalid"),
    ],
)
def test_lease_input_boundaries(container, changes, code):
    client = _client(container)
    with pytest.raises(ClientLeaseValidationError) as exc:
        container.client_leases.create_lease(client.id, _lease(**changes))
    assert exc.value.code == code


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"lease_name": "名" * 201}, "client_lease.name.too_long"),
        ({"premises_address": "址" * 501}, "client_lease.address.too_long"),
        ({"landlord_name": "房" * 201}, "client_lease.landlord.too_long"),
        ({"notes": "註" * 2001}, "client_lease.notes.too_long"),
        ({"status": "active" + "x" * 15}, "client_lease.status.too_long"),
        ({"start_date": "2026-01-01garbage"}, "client_lease.date.too_long"),
        ({"end_date": "2026-12-31garbage"}, "client_lease.date.too_long"),
    ],
)
def test_lease_text_fields_reject_overlong_input_without_mutation(
    container, operation, changes, code
):
    client = _client(container)
    existing = None
    if operation == "update":
        existing = container.client_leases.create_lease(client.id, _lease())

    with pytest.raises(ClientLeaseValidationError) as exc:
        if operation == "create":
            container.client_leases.create_lease(client.id, _lease(**changes))
        else:
            container.client_leases.update_lease(existing.id, _lease(**changes))

    assert exc.value.code == code
    if operation == "create":
        assert container.client_leases.list_for_client(client.id) == []
    else:
        assert container.client_leases.get_lease(existing.id) == existing


def test_lease_boundary_values_are_allowed(container):
    client = _client(container)
    zero = container.client_leases.create_lease(
        client.id,
        _lease(monthly_rent=0, deposit_amount=0, reminder_days=0),
    )
    max_reminder = container.client_leases.create_lease(
        client.id, _lease(lease_name="上限", reminder_days=3650)
    )
    assert (zero.monthly_rent, zero.deposit_amount, zero.reminder_days) == (0, 0, 0)
    assert max_reminder.reminder_days == 3650


def test_missing_or_deleted_client_cannot_mutate_leases(container):
    with pytest.raises(ClientLeaseValidationError) as missing:
        container.client_leases.create_lease(999999, _lease())
    assert missing.value.code == "client_lease.client_not_found"

    client = _client(container)
    lease = container.client_leases.create_lease(client.id, _lease())
    container.clients.delete_client(client.id)

    with pytest.raises(ClientLeaseValidationError) as deleted:
        container.client_leases.update_lease(lease.id, _lease(lease_name="不可改"))
    assert deleted.value.code == "client_lease.client_not_found"


def test_create_rolls_back_when_audit_fails(container, monkeypatch):
    client = _client(container)
    monkeypatch.setattr(
        container.client_leases._audit,
        "record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        container.client_leases.create_lease(client.id, _lease())

    assert container.client_leases.list_for_client(client.id) == []


def test_repository_archive_reports_zero_row_mutation_as_not_found(container):
    client = _client(container)
    lease = container.client_leases.create_lease(client.id, _lease())
    container.client_leases.archive_lease(lease.id)

    assert container.client_leases._repo.archive(lease.id) is None


def test_repository_owner_guard_blocks_foreign_update_and_archive(container):
    owner = _client(container, "OWNER-GUARD-A")
    foreign = _client(container, "OWNER-GUARD-B")
    lease = container.client_leases.create_lease(owner.id, _lease())
    values = validate_lease_input(_lease(lease_name="不可越權更新"))

    assert (
        container.client_leases._repo.update_for_client(
            lease.id, foreign.id, **values
        )
        is None
    )
    assert (
        container.client_leases._repo.archive_for_client(lease.id, foreign.id)
        is None
    )
    assert container.client_leases.get_lease(lease.id) == lease
