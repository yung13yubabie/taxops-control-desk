from __future__ import annotations

import sqlite3

import pytest

from taxops.services.clients import CreateClientInput
from taxops.services.annual_work import AnnualWorkValidationError
from taxops.services.compliance_profiles import ComplianceProfileItemInput
from taxops.services.engagements import CreateEngagementInput
from taxops.services.attachments import UploadAttachmentInput


def _work_item(container: object, *, code: str = "ANNUAL-LINK"):
    client = getattr(container, "clients").create_client(
        CreateClientInput(client_code=code, client_name="年度整合作業客戶")
    )
    getattr(container, "compliance_profiles").upsert_profile(
        client.id,
        fiscal_year_start_month=1,
        items=(ComplianceProfileItemInput("vat", "bimonthly"),),
    )
    annual = getattr(container, "annual_work")
    result = annual.confirm_preview(client.id, 2026, annual.preview(client.id, 2026))
    return client, result.items[0]


def test_linked_request_is_the_same_existing_workflow_row(container: object) -> None:
    _client, item = _work_item(container)
    annual = getattr(container, "annual_work")

    linked = annual.create_linked_request(
        item.id,
        request_name="三至四月憑證\n補件清單",
        item_names=("進項發票", "銷項發票"),
        due_date="2026-05-10",
        notes="第一行\n第二行",
    )

    existing = getattr(container, "doc_requests").get_request(linked.request.id)
    assert existing == linked.request
    assert [row.id for row in getattr(container, "doc_requests").list_items(existing.id)] == [
        row.id for row in linked.items
    ]
    assert existing.request_name == "三至四月憑證\n補件清單"
    assert existing.notes == "第一行\n第二行"
    summary = annual.document_summary(item.id)
    assert (summary.request_count, summary.total, summary.missing) == (1, 2, 2)


def test_link_existing_engagement_same_link_is_truthful_noop(container: object) -> None:
    client, item = _work_item(container, code="ANNUAL-EXISTING-LINK")
    engagement = getattr(container, "engagements").create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="既有營業稅案件",
            tax_type="vat",
            period_name="2026-01-02",
        )
    )
    annual = getattr(container, "annual_work")
    first = annual.link_existing_engagement(item.id, engagement.id)
    audit_count = getattr(container, "audit")._repo.count()

    second = annual.link_existing_engagement(item.id, engagement.id)

    assert first.engagement_id == engagement.id
    assert second == first
    assert second.updated_at == first.updated_at
    assert getattr(container, "audit")._repo.count() == audit_count


def test_linked_task_is_the_same_existing_task_row(container: object) -> None:
    client, item = _work_item(container, code="ANNUAL-TASK-LINK")
    annual = getattr(container, "annual_work")

    linked = annual.create_linked_task(
        item.id,
        title="確認營業稅申報資料",
        assignee="王小姐",
        due_date="2026-03-12",
        priority="high",
        notes="檢核一\n檢核二",
    )

    existing = getattr(container, "tasks").get_task(linked.id)
    assert existing == linked
    assert existing.client_id == client.id
    assert existing.engagement_id is not None
    assert existing.annual_work_item_id == item.id
    assert getattr(container, "tasks").list_by_annual_work_item(item.id) == [linked]


def test_repeated_request_reuses_engagement_but_creates_new_request_event(
    container: object,
) -> None:
    _client, item = _work_item(container, code="ANNUAL-REQUEST-REPEAT")
    annual = getattr(container, "annual_work")

    first = annual.create_linked_request(
        item.id, request_name="第一次請款", item_names=("附件甲",)
    )
    second = annual.create_linked_request(
        item.id, request_name="第二次補件", item_names=("附件乙",)
    )

    assert second.engagement.id == first.engagement.id
    assert second.request.id != first.request.id
    assert len(getattr(container, "engagements").list_by_client(first.engagement.client_id)) == 1
    actions = [
        row.action
        for row in getattr(container, "audit")._repo.list_recent(limit=100)
    ]
    assert actions.count("annual_work.request.create") == 2


def test_relink_is_allowed_until_workflow_history_exists(container: object) -> None:
    client, item = _work_item(container, code="ANNUAL-RELINK")
    engagements = getattr(container, "engagements")
    first = engagements.create_engagement(
        CreateEngagementInput(client.id, "舊案件", "vat", "2026-01-02")
    )
    second = engagements.create_engagement(
        CreateEngagementInput(client.id, "新案件", "vat", "2026-03-04")
    )
    annual = getattr(container, "annual_work")
    annual.link_existing_engagement(item.id, first.id)
    relinked = annual.link_existing_engagement(item.id, second.id)
    assert relinked.engagement_id == second.id

    annual.create_linked_request(
        item.id, request_name="已有補件歷史", item_names=("發票",)
    )
    with pytest.raises(AnnualWorkValidationError) as caught:
        annual.link_existing_engagement(item.id, first.id)
    assert caught.value.code == "annual_work.engagement.relink_has_history"
    with pytest.raises(AnnualWorkValidationError) as unlink:
        annual.unlink_engagement(item.id)
    assert unlink.value.code == "annual_work.engagement.unlink_has_history"


def test_existing_link_rejects_cross_client_and_mistyped_ids(container: object) -> None:
    _client, item = _work_item(container, code="ANNUAL-CROSS-LINK")
    other = getattr(container, "clients").create_client(
        CreateClientInput(client_code="ANNUAL-OTHER", client_name="其他客戶")
    )
    engagement = getattr(container, "engagements").create_engagement(
        CreateEngagementInput(other.id, "其他客戶案件", "vat", "2026-01-02")
    )
    annual = getattr(container, "annual_work")

    with pytest.raises(AnnualWorkValidationError) as cross:
        annual.link_existing_engagement(item.id, engagement.id)
    assert cross.value.code == "annual_work.engagement.client_mismatch"
    with pytest.raises(AnnualWorkValidationError) as mistyped:
        annual.link_existing_engagement(True, engagement.id)
    assert mistyped.value.code == "annual_work.item_id.invalid"


def test_document_summary_tracks_status_and_nonarchived_attachments(
    container: object, tmp_path
) -> None:
    _client, item = _work_item(container, code="ANNUAL-SUMMARY")
    annual = getattr(container, "annual_work")
    linked = annual.create_linked_request(
        item.id,
        request_name="狀態彙總",
        item_names=("缺件", "已收", "無效", "不適用"),
    )
    documents = getattr(container, "doc_requests")
    documents.set_item_status(linked.items[1].id, item_status="received")
    documents.set_item_status(linked.items[2].id, item_status="invalid")
    documents.set_item_status(linked.items[3].id, item_status="not_applicable")
    source = tmp_path / "證明.pdf"
    source.write_bytes(b"annual evidence")
    attachment = getattr(container, "attachments").upload_attachment(
        UploadAttachmentInput(linked.engagement.id, linked.request.id, source)
    )

    summary = annual.document_summary(item.id)
    assert (
        summary.request_count,
        summary.total,
        summary.missing,
        summary.received,
        summary.invalid,
        summary.not_applicable,
        summary.attachment_count,
    ) == (1, 4, 1, 1, 1, 1, 1)

    getattr(container, "attachments").delete_attachment(attachment.id)
    assert annual.document_summary(item.id).attachment_count == 0
    replacement = getattr(container, "attachments").upload_attachment(
        UploadAttachmentInput(linked.engagement.id, linked.request.id, source)
    )
    assert replacement.status != "archived"
    assert annual.document_summary(item.id).attachment_count == 1
    documents.delete_request(linked.request.id)
    assert annual.document_summary(item.id).request_count == 0
    assert annual.document_summary(item.id).total == 0
    assert annual.document_summary(item.id).attachment_count == 0


def test_annual_and_task_completion_are_independent(container: object) -> None:
    _client, item = _work_item(container, code="ANNUAL-INDEPENDENT")
    annual = getattr(container, "annual_work")
    task = annual.create_linked_task(item.id, title="獨立完成測試")

    completed_item = annual.complete_item(item.id, exception_reason="文件狀態另行處理")
    assert completed_item.work_status == "completed_with_exception"
    assert getattr(container, "tasks").get_task(task.id).status == "todo"

    # Reopening annual work and completing the task does not drive annual state.
    reopened = annual.set_work_status(item.id, "in_progress")
    assert reopened.work_status == "in_progress"
    getattr(container, "tasks").complete_task(task.id)
    assert annual.repository.get_item(item.id).work_status == "in_progress"


@pytest.mark.parametrize(
    "failure_point", ("engagement", "fts", "link", "request", "item", "audit")
)
def test_linked_request_rolls_back_every_stage(
    container: object, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    _client, item = _work_item(container, code=f"ANNUAL-RB-{failure_point}")
    annual = getattr(container, "annual_work")
    conn = getattr(container, "conn")
    tables = ("engagements", "document_requests", "document_request_items", "audit_logs")
    before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in tables
    }
    before_fts = conn.execute("SELECT COUNT(*) FROM fts_engagements").fetchone()[0]

    if failure_point == "engagement":
        conn.execute(
            "CREATE TEMP TRIGGER fail_annual_engagement BEFORE INSERT ON engagements "
            "BEGIN SELECT RAISE(ABORT, 'boom engagement'); END"
        )
        conn.commit()
    elif failure_point == "fts":
        monkeypatch.setattr(
            getattr(container, "engagements")._search_repo,
            "add_engagement",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("raw fts")),
        )
    elif failure_point == "link":
        monkeypatch.setattr(
            annual.repository,
            "set_engagement_link",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("raw link")),
        )
    elif failure_point == "request":
        conn.execute(
            "CREATE TEMP TRIGGER fail_annual_request BEFORE INSERT ON document_requests "
            "BEGIN SELECT RAISE(ABORT, 'boom request'); END"
        )
        conn.commit()
    elif failure_point == "item":
        conn.execute(
            "CREATE TEMP TRIGGER fail_annual_request_item BEFORE INSERT ON document_request_items "
            "BEGIN SELECT RAISE(ABORT, 'boom item'); END"
        )
        conn.commit()
    else:
        original_record = getattr(container, "audit").record

        def fail_final_audit(**kwargs):
            if kwargs.get("action") == "annual_work.request.create":
                raise RuntimeError("private audit backend")
            return original_record(**kwargs)

        monkeypatch.setattr(getattr(container, "audit"), "record", fail_final_audit)

    with pytest.raises(Exception) as caught:
        annual.create_linked_request(
            item.id, request_name="不可留下半套資料", item_names=("文件",)
        )
    assert getattr(caught.value, "code", None) == "annual_work.request.create_failed"
    assert {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in tables
    } == before
    assert conn.execute("SELECT COUNT(*) FROM fts_engagements").fetchone()[0] == before_fts
    assert annual.repository.get_item(item.id).engagement_id is None


@pytest.mark.parametrize("failure_point", ("task", "audit"))
def test_linked_task_rolls_back_task_engagement_link_and_audits(
    container: object, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    _client, item = _work_item(container, code=f"ANNUAL-TASK-RB-{failure_point}")
    annual = getattr(container, "annual_work")
    conn = getattr(container, "conn")
    before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("engagements", "workflow_tasks", "audit_logs")
    }
    before_fts = conn.execute("SELECT COUNT(*) FROM fts_engagements").fetchone()[0]
    if failure_point == "task":
        conn.execute(
            "CREATE TEMP TRIGGER fail_annual_task BEFORE INSERT ON workflow_tasks "
            "BEGIN SELECT RAISE(ABORT, 'boom task'); END"
        )
        conn.commit()
    else:
        original_record = getattr(container, "audit").record

        def fail_final_audit(**kwargs):
            if kwargs.get("action") == "annual_work.task.create":
                raise RuntimeError("private task audit")
            return original_record(**kwargs)

        monkeypatch.setattr(getattr(container, "audit"), "record", fail_final_audit)

    with pytest.raises(Exception) as caught:
        annual.create_linked_task(item.id, title="不可留下半套任務")
    assert getattr(caught.value, "code", None) == "annual_work.task.create_failed"
    assert {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("engagements", "workflow_tasks", "audit_logs")
    } == before
    assert conn.execute("SELECT COUNT(*) FROM fts_engagements").fetchone()[0] == before_fts
    assert annual.repository.get_item(item.id).engagement_id is None


def test_workflow_mutations_fail_fast_without_touching_caller_transaction(
    container: object,
) -> None:
    _client, item = _work_item(container, code="ANNUAL-CALLER-TX")
    annual = getattr(container, "annual_work")
    conn = getattr(container, "conn")
    conn.execute("BEGIN")
    conn.execute("UPDATE annual_work_items SET notes = 'caller-owned' WHERE id = ?", (item.id,))

    for operation in (
        lambda: annual.create_linked_request(
            item.id, request_name="禁止巢狀提交", item_names=("文件",)
        ),
        lambda: annual.create_linked_task(item.id, title="禁止巢狀提交"),
        lambda: annual.unlink_engagement(item.id),
    ):
        with pytest.raises(AnnualWorkValidationError) as caught:
            operation()
        assert caught.value.code == "annual_work.transaction.already_active"
        assert conn.in_transaction is True
        assert conn.execute(
            "SELECT notes FROM annual_work_items WHERE id = ?", (item.id,)
        ).fetchone()[0] == "caller-owned"
    conn.rollback()


def test_linked_overview_returns_existing_engagement_requests_and_tasks(
    container: object,
) -> None:
    _client, item = _work_item(container, code="ANNUAL-OVERVIEW")
    annual = getattr(container, "annual_work")
    request = annual.create_linked_request(
        item.id, request_name="總覽補件", item_names=("總覽文件",)
    )
    task = annual.create_linked_task(item.id, title="總覽任務")

    overview = annual.linked_overview(item.id)

    assert overview.item.id == item.id
    assert overview.engagement == request.engagement
    assert overview.requests == (request.request,)
    assert overview.tasks == (task,)
    assert annual.list_linked_requests(item.id) == (request.request,)
    assert annual.list_linked_tasks(item.id) == (task,)


def test_annual_linked_request_lists_use_bounded_pagination(container: object) -> None:
    _client, item = _work_item(container, code="ANNUAL-REQUEST-PAGE")
    annual = getattr(container, "annual_work")
    created = [
        annual.create_linked_request(
            item.id,
            request_name=f"第 {index} 批補件",
            item_names=(f"文件 {index}",),
        ).request
        for index in range(3)
    ]
    for index in range(3, 205):
        getattr(container, "doc_requests")._repo.insert_request(
            engagement_id=created[0].engagement_id,
            request_name=f"第 {index} 批補件",
            tax_type="vat",
            period_name=created[0].period_name,
        )

    assert annual.list_linked_requests(item.id, limit=1, offset=1) == (created[1],)
    assert annual.linked_overview(item.id, limit=1, offset=2).requests == (
        created[2],
    )
    assert len(annual.list_linked_requests(item.id)) == 200
    assert [
        row.request_name
        for row in annual.list_linked_requests(item.id, limit=5, offset=200)
    ] == [f"第 {index} 批補件" for index in range(200, 205)]


@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (True, 0),
        ("1", 0),
        (0, 0),
        (501, 0),
        ("1 LIMIT 999999", 0),
        (1, True),
        (1, "0"),
        (1, -1),
        (1, 1_000_001),
        (1, "0; SELECT 1"),
    ],
)
def test_annual_linked_request_pagination_rejects_invalid_or_injectable_values(
    container: object, limit: object, offset: object
) -> None:
    _client, item = _work_item(
        container, code=f"ANNUAL-PAGE-INVALID-{type(limit).__name__}-{type(offset).__name__}"
    )
    annual = getattr(container, "annual_work")

    for operation in (
        lambda: annual.list_linked_requests(item.id, limit=limit, offset=offset),
        lambda: annual.linked_overview(item.id, limit=limit, offset=offset),
    ):
        with pytest.raises(AnnualWorkValidationError) as caught:
            operation()
        assert caught.value.code == "annual_work.linked_requests.pagination.invalid"


def test_deleted_engagement_and_client_are_excluded_from_summary(
    container: object,
) -> None:
    client, item = _work_item(container, code="ANNUAL-DELETED-OWNER")
    annual = getattr(container, "annual_work")
    linked = annual.create_linked_request(
        item.id, request_name="待刪除上層", item_names=("文件",)
    )
    conn = getattr(container, "conn")
    conn.execute(
        "UPDATE engagements SET deleted_at = '2026-07-19T00:00:00' WHERE id = ?",
        (linked.engagement.id,),
    )
    conn.commit()
    assert annual.document_summary(item.id).request_count == 0
    assert annual.document_summary(item.id).total == 0

    conn.execute(
        "UPDATE clients SET deleted_at = '2026-07-19T00:00:00' WHERE id = ?",
        (client.id,),
    )
    conn.commit()
    assert annual.document_summary(item.id).request_count == 0
    assert annual.document_summary(item.id).attachment_count == 0


def test_writer_lock_returns_stable_busy_without_partial_rows(container: object) -> None:
    _client, item = _work_item(container, code="ANNUAL-WRITER-LOCK")
    annual = getattr(container, "annual_work")
    conn = getattr(container, "conn")
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    locker = sqlite3.connect(db_path, timeout=0)
    conn.execute("PRAGMA busy_timeout = 0")
    try:
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises(Exception) as caught:
            annual.create_linked_request(
                item.id, request_name="鎖定時不可部分寫入", item_names=("文件",)
            )
        assert getattr(caught.value, "code", None) == "annual_work.transaction.busy"
        assert annual.repository.get_item(item.id).engagement_id is None
    finally:
        locker.rollback()
        locker.close()
        conn.execute("PRAGMA busy_timeout = 5000")
