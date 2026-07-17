from __future__ import annotations

import sqlite3

import pytest

from taxops.db.connection import open_connection
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.client_leases import ClientLeasesRepository
from taxops.repositories.clients import ClientsRepository
from taxops.repositories.search import SearchRepository
from taxops.services.audit import AuditService
from taxops.services.client_leases import ClientLeaseValidationError, LeaseInput
from taxops.services.client_profiles import (
    ClientProfilesService,
    ClientProfileValidationError,
    LeaseChange,
    _immediate_transaction,
)
from taxops.services.clients import CreateClientInput, UpdateClientInput


def _lease(name: str, *, start: str, end: str) -> LeaseInput:
    return LeaseInput(
        lease_name=name,
        premises_address="臺北市中正區測試路 1 號",
        start_date=start,
        end_date=end,
        monthly_rent=30_000,
    )


def test_profile_service_rejects_repositories_from_another_connection(
    container, tmp_path
) -> None:
    other_conn = open_connection(tmp_path / "miswired.sqlite")
    try:
        with pytest.raises(ValueError, match="client_profile.connection.mismatch"):
            ClientProfilesService(
                container.conn,
                ClientsRepository(other_conn),
                ClientLeasesRepository(other_conn),
                AuditService(AuditLogRepository(other_conn)),
                SearchRepository(other_conn),
            )
    finally:
        other_conn.close()


@pytest.mark.parametrize(
    "invalid_leases", ["lease", b"lease", object(), [object()]]
)
def test_create_profile_rejects_invalid_lease_input_collection(
    container, invalid_leases
) -> None:
    with pytest.raises(ClientProfileValidationError) as exc:
        container.client_profiles.create_client_with_leases(
            CreateClientInput(
                client_code="PROFILE-BAD-LEASES", client_name="租約集合錯型"
            ),
            invalid_leases,
        )

    assert exc.value.code == "client_profile.lease_inputs.invalid"
    assert container.clients.find_by_code("PROFILE-BAD-LEASES") is None


@pytest.mark.parametrize(
    "invalid_changes", ["change", b"change", object(), [object()]]
)
def test_update_profile_rejects_invalid_lease_change_collection(
    container, invalid_changes
) -> None:
    profile = container.client_profiles.create_client_with_leases(
        CreateClientInput(client_code="PROFILE-BAD-CHANGES", client_name="變更集合錯型"),
        [],
    )
    before_audit_count = container.audit._repo.count()

    with pytest.raises(ClientProfileValidationError) as exc:
        container.client_profiles.update_client_with_lease_changes(
            profile.client.id,
            UpdateClientInput(
                client_code=profile.client.client_code,
                client_name="不應更新的名稱",
            ),
            invalid_changes,
        )

    assert exc.value.code == "client_profile.lease_changes.invalid"
    assert container.clients.get_client(profile.client.id) == profile.client
    assert container.audit._repo.count() == before_audit_count


def test_begin_immediate_writer_lock_maps_to_stable_busy_error(tmp_path) -> None:
    db_path = tmp_path / "busy.sqlite"
    writer = open_connection(db_path)
    contender = open_connection(db_path)
    writer.execute("PRAGMA busy_timeout = 0")
    contender.execute("PRAGMA busy_timeout = 0")
    writer.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ClientProfileValidationError) as exc:
            with _immediate_transaction(contender):
                pytest.fail("busy transaction must not enter the body")
    finally:
        writer.rollback()
        contender.close()
        writer.close()

    assert exc.value.code == "client_profile.transaction.busy"


def test_begin_immediate_non_busy_operational_error_is_not_remapped() -> None:
    class NonBusyBeginFailure(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                raise sqlite3.OperationalError("synthetic begin failure")
            return super().execute(sql, parameters)

    conn = sqlite3.connect(":memory:", factory=NonBusyBeginFailure)
    try:
        with pytest.raises(sqlite3.OperationalError, match="synthetic begin failure"):
            with _immediate_transaction(conn):
                pytest.fail("failed transaction must not enter the body")
    finally:
        conn.close()


def test_create_client_profile_saves_two_overlapping_leases(container) -> None:
    result = container.client_profiles.create_client_with_leases(
        CreateClientInput(client_code="PROFILE-001", client_name="原子客戶股份有限公司"),
        [
            _lease("總公司", start="2026-01-01", end="2026-12-31"),
            _lease("分公司", start="2026-06-01", end="2027-05-31"),
        ],
    )

    assert result.client.client_code == "PROFILE-001"
    assert [lease.lease_name for lease in result.leases] == ["總公司", "分公司"]
    assert {lease.client_id for lease in result.leases} == {result.client.id}

    actions = [row.action for row in container.audit._repo.list_recent(limit=10)]
    assert actions.count("client.create") == 1
    assert actions.count("client.lease.create") == 2
    assert container.search.search_clients("原子客戶") == [result.client]


def test_second_lease_insert_failure_rolls_back_entire_new_profile(
    container, monkeypatch
) -> None:
    real_insert = container.client_profiles._leases_repo.insert
    calls = 0

    def fail_second_insert(client_id, **values):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second lease insert failed")
        return real_insert(client_id, **values)

    monkeypatch.setattr(
        container.client_profiles._leases_repo, "insert", fail_second_insert
    )

    with pytest.raises(RuntimeError, match="second lease insert failed"):
        container.client_profiles.create_client_with_leases(
            CreateClientInput(
                client_code="PROFILE-ROLLBACK-INSERT",
                client_name="第二租約失敗客戶",
            ),
            [
                _lease("第一租約", start="2026-01-01", end="2026-12-31"),
                _lease("第二租約", start="2027-01-01", end="2027-12-31"),
            ],
        )

    assert container.clients.find_by_code("PROFILE-ROLLBACK-INSERT") is None
    assert container.conn.execute("SELECT COUNT(*) FROM client_leases").fetchone()[0] == 0
    assert container.audit._repo.count() == 0
    assert container.conn.execute("SELECT COUNT(*) FROM fts_clients").fetchone()[0] == 0


def test_second_lease_audit_failure_rolls_back_entire_new_profile(
    container, monkeypatch
) -> None:
    real_record = container.client_profiles._audit.record
    lease_audits = 0

    def fail_second_lease_audit(**values):
        nonlocal lease_audits
        if values["action"] == "client.lease.create":
            lease_audits += 1
            if lease_audits == 2:
                raise RuntimeError("second lease audit failed")
        return real_record(**values)

    monkeypatch.setattr(
        container.client_profiles._audit, "record", fail_second_lease_audit
    )

    with pytest.raises(RuntimeError, match="second lease audit failed"):
        container.client_profiles.create_client_with_leases(
            CreateClientInput(
                client_code="PROFILE-ROLLBACK-AUDIT",
                client_name="第二稽核失敗客戶",
            ),
            [
                _lease("第一租約", start="2026-01-01", end="2026-12-31"),
                _lease("第二租約", start="2027-01-01", end="2027-12-31"),
            ],
        )

    assert container.clients.find_by_code("PROFILE-ROLLBACK-AUDIT") is None
    assert container.conn.execute("SELECT COUNT(*) FROM client_leases").fetchone()[0] == 0
    assert container.audit._repo.count() == 0
    assert container.conn.execute("SELECT COUNT(*) FROM fts_clients").fetchone()[0] == 0


def test_invalid_second_lease_is_rejected_before_any_profile_mutation(container) -> None:
    with pytest.raises(ClientLeaseValidationError) as exc:
        container.client_profiles.create_client_with_leases(
            CreateClientInput(
                client_code="PROFILE-INVALID-LEASE",
                client_name="租約驗證失敗客戶",
            ),
            [
                _lease("有效租約", start="2026-01-01", end="2026-12-31"),
                _lease("無效租約", start="2027-12-31", end="2027-01-01"),
            ],
        )

    assert exc.value.code == "client_lease.date_range.invalid"
    assert container.clients.find_by_code("PROFILE-INVALID-LEASE") is None
    assert container.conn.execute("SELECT COUNT(*) FROM client_leases").fetchone()[0] == 0
    assert container.audit._repo.count() == 0
    assert container.conn.execute("SELECT COUNT(*) FROM fts_clients").fetchone()[0] == 0


def test_profile_fts_failure_rolls_back_client_before_any_lease(container, monkeypatch) -> None:
    monkeypatch.setattr(
        container.client_profiles._search_repo,
        "add_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("profile FTS failed")
        ),
    )

    with pytest.raises(RuntimeError, match="profile FTS failed"):
        container.client_profiles.create_client_with_leases(
            CreateClientInput(
                client_code="PROFILE-ROLLBACK-FTS", client_name="索引失敗客戶"
            ),
            [_lease("不應建立", start="2026-01-01", end="2026-12-31")],
        )

    assert container.clients.find_by_code("PROFILE-ROLLBACK-FTS") is None
    assert container.conn.execute("SELECT COUNT(*) FROM client_leases").fetchone()[0] == 0
    assert container.audit._repo.count() == 0
    assert container.conn.execute("SELECT COUNT(*) FROM fts_clients").fetchone()[0] == 0


def test_update_client_profile_applies_create_update_and_archive_together(
    container,
) -> None:
    original = container.client_profiles.create_client_with_leases(
        CreateClientInput(
            client_code="PROFILE-UPDATE",
            client_name="更新前客戶",
            registered_address="舊登記地址",
            contact_address_same=True,
        ),
        [
            _lease("待更新租約", start="2026-01-01", end="2026-12-31"),
            _lease("待封存租約", start="2025-01-01", end="2025-12-31"),
        ],
    )
    update_id, archive_id = (lease.id for lease in original.leases)

    saved = container.client_profiles.update_client_with_lease_changes(
        original.client.id,
        UpdateClientInput(
            client_code="PROFILE-UPDATE",
            client_name="更新後客戶",
            registered_address="新登記地址",
            contact_address_same=True,
        ),
        [
            LeaseChange(
                operation="update",
                lease_id=update_id,
                payload=_lease(
                    "已更新租約", start="2026-01-01", end="2027-12-31"
                ),
            ),
            LeaseChange(operation="archive", lease_id=archive_id),
            LeaseChange(
                operation="create",
                payload=_lease("新增租約", start="2028-01-01", end="2028-12-31"),
            ),
        ],
    )

    assert saved.client.client_name == "更新後客戶"
    assert saved.client.registered_address == "新登記地址"
    assert saved.client.contact_address == "新登記地址"
    assert {lease.lease_name for lease in saved.leases} == {"已更新租約", "新增租約"}
    assert container.client_leases.get(archive_id, include_deleted=True).deleted_at
    assert container.search.search_clients("更新後客戶") == [saved.client]
    assert container.search.search_clients("更新前客戶") == []

    actions = [row.action for row in container.audit._repo.list_recent(limit=4)]
    assert set(actions) == {
        "client.update",
        "client.lease.update",
        "client.lease.archive",
        "client.lease.create",
    }


def test_middle_lease_operation_failure_restores_exact_profile_state(
    container, monkeypatch
) -> None:
    original = container.client_profiles.create_client_with_leases(
        CreateClientInput(client_code="PROFILE-MIDDLE", client_name="交易前名稱"),
        [
            _lease("保持原值", start="2026-01-01", end="2026-12-31"),
            _lease("不可封存", start="2027-01-01", end="2027-12-31"),
        ],
    )
    update_id, archive_id = (lease.id for lease in original.leases)
    before_client = container.clients.get_client(original.client.id)
    before_leases = container.client_leases.list_for_client(
        original.client.id, include_deleted=True
    )
    before_audits = container.audit._repo.list_recent(limit=100)
    before_fts = [
        tuple(row)
        for row in container.conn.execute(
            "SELECT rowid, client_code, client_name, tax_id, short_name, "
            "contact_name, note FROM fts_clients ORDER BY rowid"
        ).fetchall()
    ]

    monkeypatch.setattr(
        container.client_profiles._leases_repo,
        "update_for_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("middle lease update failed")
        ),
    )

    with pytest.raises(RuntimeError, match="middle lease update failed"):
        container.client_profiles.update_client_with_lease_changes(
            original.client.id,
            UpdateClientInput(
                client_code="PROFILE-MIDDLE", client_name="不應提交的新名稱"
            ),
            [
                LeaseChange(
                    operation="create",
                    payload=_lease(
                        "不應留下", start="2028-01-01", end="2028-12-31"
                    ),
                ),
                LeaseChange(
                    operation="update",
                    lease_id=update_id,
                    payload=_lease(
                        "不應更新", start="2026-01-01", end="2029-12-31"
                    ),
                ),
                LeaseChange(operation="archive", lease_id=archive_id),
            ],
        )

    assert container.clients.get_client(original.client.id) == before_client
    assert container.client_leases.list_for_client(
        original.client.id, include_deleted=True
    ) == before_leases
    assert container.audit._repo.list_recent(limit=100) == before_audits
    assert [
        tuple(row)
        for row in container.conn.execute(
            "SELECT rowid, client_code, client_name, tax_id, short_name, "
            "contact_name, note FROM fts_clients ORDER BY rowid"
        ).fetchall()
    ] == before_fts


@pytest.mark.parametrize("operation", ["update", "archive"])
def test_foreign_lease_change_is_rejected_before_profile_mutation(
    container, operation
) -> None:
    client_a = container.client_profiles.create_client_with_leases(
        CreateClientInput(client_code="PROFILE-OWNER-A", client_name="客戶甲"), []
    ).client
    profile_b = container.client_profiles.create_client_with_leases(
        CreateClientInput(client_code="PROFILE-OWNER-B", client_name="客戶乙"),
        [_lease("乙的租約", start="2026-01-01", end="2026-12-31")],
    )
    foreign_lease = profile_b.leases[0]
    before_a = container.clients.get_client(client_a.id)
    before_lease = container.client_leases.get(foreign_lease.id)
    before_audit_count = container.audit._repo.count()

    change = LeaseChange(
        operation=operation,
        lease_id=foreign_lease.id,
        payload=(
            _lease("越權更新", start="2026-01-01", end="2027-12-31")
            if operation == "update"
            else None
        ),
    )
    with pytest.raises(ClientProfileValidationError) as exc:
        container.client_profiles.update_client_with_lease_changes(
            client_a.id,
            UpdateClientInput(
                client_code=client_a.client_code, client_name="不應變更的客戶甲"
            ),
            [change],
        )

    assert exc.value.code == "client_profile.lease_change.foreign_client"
    assert container.clients.get_client(client_a.id) == before_a
    assert container.client_leases.get(foreign_lease.id) == before_lease
    assert container.audit._repo.count() == before_audit_count


def test_duplicate_contradictory_lease_changes_are_rejected_before_mutation(
    container,
) -> None:
    profile = container.client_profiles.create_client_with_leases(
        CreateClientInput(client_code="PROFILE-DUP", client_name="重複操作客戶"),
        [_lease("不可重複", start="2026-01-01", end="2026-12-31")],
    )
    lease = profile.leases[0]
    before_audit_count = container.audit._repo.count()

    with pytest.raises(ClientProfileValidationError) as exc:
        container.client_profiles.update_client_with_lease_changes(
            profile.client.id,
            UpdateClientInput(
                client_code=profile.client.client_code, client_name="不應更新"
            ),
            [
                LeaseChange(
                    operation="update",
                    lease_id=lease.id,
                    payload=_lease(
                        "不應更新", start="2026-01-01", end="2027-12-31"
                    ),
                ),
                LeaseChange(operation="archive", lease_id=lease.id),
            ],
        )

    assert exc.value.code == "client_profile.lease_change.duplicate_id"
    assert container.clients.get_client(profile.client.id) == profile.client
    assert container.client_leases.get(lease.id) == lease
    assert container.audit._repo.count() == before_audit_count


def test_update_profile_without_lease_changes_keeps_leases_and_updates_fts(
    container,
) -> None:
    profile = container.client_profiles.create_client_with_leases(
        CreateClientInput(client_code="PROFILE-ONLY", client_name="只有主檔舊名"),
        [_lease("保持租約", start="2026-01-01", end="2026-12-31")],
    )

    saved = container.client_profiles.update_client_with_lease_changes(
        profile.client.id,
        UpdateClientInput(
            client_code=profile.client.client_code, client_name="只有主檔新名"
        ),
        [],
    )

    assert saved.client.client_name == "只有主檔新名"
    assert saved.leases == profile.leases
    assert container.search.search_clients("只有主檔新名") == [saved.client]
    assert container.audit._repo.list_recent(limit=1)[0].action == "client.update"


def test_competing_archive_cannot_interleave_after_profile_prevalidation(
    container, monkeypatch
) -> None:
    profile = container.client_profiles.create_client_with_leases(
        CreateClientInput(client_code="PROFILE-RACE", client_name="競態前名稱"),
        [_lease("競態租約", start="2026-01-01", end="2026-12-31")],
    )
    lease = profile.leases[0]
    before_audits = container.audit._repo.list_recent(limit=100)
    competing_conn = open_connection(container.paths.db_path)
    competing_conn.execute("PRAGMA busy_timeout = 0")
    real_update = container.client_profiles._clients_repo.update

    def archive_from_competing_connection(client_id, **values):
        with competing_conn:
            competing_conn.execute(
                "UPDATE client_leases SET deleted_at = ?, updated_at = ? "
                "WHERE id = ? AND deleted_at IS NULL",
                ("2099-01-01T00:00:00Z", "2099-01-01T00:00:00Z", lease.id),
            )
        return real_update(client_id, **values)

    monkeypatch.setattr(
        container.client_profiles._clients_repo,
        "update",
        archive_from_competing_connection,
    )

    caught = None
    try:
        container.client_profiles.update_client_with_lease_changes(
            profile.client.id,
            UpdateClientInput(
                client_code=profile.client.client_code,
                client_name="競態後不應提交",
            ),
            [LeaseChange(operation="archive", lease_id=lease.id)],
        )
    except ClientProfileValidationError as exc:
        caught = exc
    finally:
        competing_conn.close()

    assert container.clients.get_client(profile.client.id) == profile.client
    assert container.client_leases.get(lease.id) == lease
    assert container.audit._repo.list_recent(limit=100) == before_audits
    assert caught is not None
    assert caught.code == "client_profile.transaction.busy"


def test_profile_save_rejects_an_existing_connection_transaction(container) -> None:
    container.conn.execute("BEGIN")
    try:
        with pytest.raises(ClientProfileValidationError) as exc:
            container.client_profiles.create_client_with_leases(
                CreateClientInput(
                    client_code="PROFILE-NESTED-TX", client_name="既有交易客戶"
                ),
                [],
            )
    finally:
        container.conn.rollback()

    assert exc.value.code == "client_profile.transaction.already_active"
    assert container.clients.find_by_code("PROFILE-NESTED-TX") is None
