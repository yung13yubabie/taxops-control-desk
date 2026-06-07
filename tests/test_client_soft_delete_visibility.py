"""Client soft-delete must hide, not destroy, all client-owned records."""

from __future__ import annotations

import datetime

from taxops.services.attachments import UploadAttachmentInput
from taxops.services.clients import CreateClientInput
from taxops.services.canvas_notes import CreateCanvasNoteInput
from taxops.services.container import ServiceContainer
from taxops.services.document_requests import CreateDocumentRequestInput
from taxops.services.engagements import CreateEngagementInput
from taxops.services.generated_messages import GenerateMessageInput
from taxops.services.late_fee import CalculateLateFeeInput
from taxops.services.recurring_billing import CreateLineInput, CreatePlanInput
from taxops.services.tasks import CreateTaskInput
from taxops.services.work_records import (
    CreateWorkflowTemplateInput,
    WorkflowStageInput,
    WorkflowStepInput,
)


def _ids(rows: list[object]) -> set[int]:
    return {row.id for row in rows}  # type: ignore[attr-defined]


def test_client_soft_delete_hides_children_and_restore_reveals_them(
    container: ServiceContainer,
    tmp_path,
) -> None:
    client = container.clients.create_client(
        CreateClientInput(client_code="VIS001", client_name="Visibility client")
    )
    engagement = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="Visibility engagement",
            tax_type="vat",
            period_name="2026Q2",
            due_date="2026-06-06",
        )
    )
    task = container.tasks.create_task(
        CreateTaskInput(
            engagement_id=engagement.id,
            title="Visibility task",
            due_date="2026-06-06",
        )
    )
    request, items = container.doc_requests.create_request(
        CreateDocumentRequestInput(
            engagement_id=engagement.id,
            request_name="Visibility request",
            tax_type="vat",
            period_name="2026Q2",
            item_names=("Visibility item",),
        )
    )
    source = tmp_path / "visibility.pdf"
    source.write_bytes(b"%PDF-1.4\nvisibility")
    attachment = container.attachments.upload_attachment(
        UploadAttachmentInput(
            engagement_id=engagement.id,
            request_id=request.id,
            source_path=source,
        )
    )
    plan = container.recurring_billing.create_plan(
        CreatePlanInput(
            client_id=client.id,
            plan_name="Visibility plan",
            start_date="2026-06-01",
            issue_day=6,
        )
    )
    line = container.recurring_billing.create_line(
        CreateLineInput(
            plan_id=plan.id,
            bill_to_name="Visibility recipient",
            amount=1000,
        )
    )
    container.recurring_billing.generate_occurrences(
        plan.id,
        until_date=datetime.date(2026, 6, 30),
    )
    occurrence = container.recurring_billing.list_occurrences(plan_id=plan.id)[0]
    message = container.gen_messages.generate(
        GenerateMessageInput(request_id=request.id, template_id=1)
    )
    late_fee = container.late_fee.calculate_and_save(
        CalculateLateFeeInput(
            request_id=request.id,
            overdue_days=4,
            base_amount=1000,
        )
    )
    template = container.work_records.create_template(
        CreateWorkflowTemplateInput(
            name="Visibility workflow",
            stages=(
                WorkflowStageInput(
                    title="Visibility stage",
                    steps=(WorkflowStepInput("Visibility step"),),
                ),
            ),
            client_id=client.id,
            engagement_id=engagement.id,
        )
    )
    run = container.work_records.instantiate_run(template.id)
    note = container.canvas_notes.create_note(
        CreateCanvasNoteInput(
            title="Visibility note",
            client_id=client.id,
            engagement_id=engagement.id,
        )
    )

    def assert_visible() -> None:
        assert container.engagements.get_engagement(engagement.id) is not None
        assert engagement.id in _ids(container.engagements.list_by_client(client.id))
        assert engagement.id in _ids(container.engagements.list_all())
        assert engagement.id in _ids(
            container.engagements.list_upcoming("2026-06-01", "2026-06-30")
        )
        assert engagement.id in _ids(container.engagements.list_overdue("2026-06-07"))
        assert engagement.id in _ids(
            container.search.search_engagements("Visibility engagement")
        )

        assert container.tasks.get_task(task.id) is not None
        assert task.id in _ids(container.tasks.list_by_engagement(engagement.id))
        assert task.id in _ids(container.tasks.list_by_client(client.id))
        assert task.id in _ids(container.tasks.list_all())
        assert task.id in _ids(container.tasks.list_due_today("2026-06-06"))
        assert task.id in _ids(container.tasks.list_overdue("2026-06-07"))

        assert container.doc_requests.get_request(request.id) is not None
        assert request.id in _ids(container.doc_requests.list_by_engagement(engagement.id))
        assert request.id in _ids(container.doc_requests.list_all())
        assert items[0].id in _ids(container.doc_requests.list_items(request.id))

        assert container.attachments.get(attachment.id) is not None
        assert attachment.id in _ids(
            container.attachments.list_by_engagement(engagement.id)
        )
        assert attachment.id in _ids(container.attachments.list_by_request(request.id))
        assert attachment.id in _ids(container.attachments.list_all())

        assert container.recurring_billing.get_plan(plan.id) is not None
        assert plan.id in _ids(container.recurring_billing.list_plans())
        assert plan.id in _ids(container.recurring_billing.list_plans(client_id=client.id))
        assert line.id in _ids(container.recurring_billing.list_lines(plan.id))
        assert occurrence.id in _ids(
            container.recurring_billing.list_occurrences(plan_id=plan.id)
        )
        assert container.recurring_billing.get_occurrence_summary(plan.id) == {
            "pending": 1
        }

        assert container.gen_messages.get_message(message.id) is not None
        assert message.id in _ids(container.gen_messages.list_by_request(request.id))
        assert late_fee.id in _ids(container.late_fee.list_by_request(request.id))
        assert template.id in _ids(container.work_records.list_templates())
        assert run.id in _ids(container.work_records.list_runs())
        assert note.id in _ids(container.canvas_notes.list_notes())

    def assert_hidden() -> None:
        assert container.engagements.get_engagement(engagement.id) is None
        assert engagement.id not in _ids(container.engagements.list_by_client(client.id))
        assert engagement.id not in _ids(container.engagements.list_all())
        assert engagement.id not in _ids(
            container.engagements.list_upcoming("2026-06-01", "2026-06-30")
        )
        assert engagement.id not in _ids(container.engagements.list_overdue("2026-06-07"))
        assert engagement.id not in _ids(
            container.search.search_engagements("Visibility engagement")
        )

        assert container.tasks.get_task(task.id) is None
        assert task.id not in _ids(container.tasks.list_by_engagement(engagement.id))
        assert task.id not in _ids(container.tasks.list_by_client(client.id))
        assert task.id not in _ids(container.tasks.list_all())
        assert task.id not in _ids(container.tasks.list_due_today("2026-06-06"))
        assert task.id not in _ids(container.tasks.list_overdue("2026-06-07"))

        assert container.doc_requests.get_request(request.id) is None
        assert request.id not in _ids(container.doc_requests.list_by_engagement(engagement.id))
        assert request.id not in _ids(container.doc_requests.list_all())
        assert container.doc_requests.list_items(request.id) == []

        assert container.attachments.get(attachment.id) is None
        assert attachment.id not in _ids(
            container.attachments.list_by_engagement(engagement.id)
        )
        assert attachment.id not in _ids(container.attachments.list_by_request(request.id))
        assert attachment.id not in _ids(container.attachments.list_all())

        assert container.recurring_billing.get_plan(plan.id) is None
        assert plan.id not in _ids(container.recurring_billing.list_plans())
        assert plan.id not in _ids(
            container.recurring_billing.list_plans(client_id=client.id)
        )
        assert container.recurring_billing.list_lines(plan.id) == []
        assert container.recurring_billing.list_occurrences(plan_id=plan.id) == []
        assert container.recurring_billing.get_occurrence_summary(plan.id) == {}

        assert container.gen_messages.get_message(message.id) is None
        assert container.gen_messages.list_by_request(request.id) == []
        assert container.late_fee.list_by_request(request.id) == []
        assert template.id not in _ids(container.work_records.list_templates())
        assert run.id not in _ids(container.work_records.list_runs())
        assert note.id not in _ids(container.canvas_notes.list_notes())

    assert_visible()
    container.clients.delete_client(client.id)
    assert_hidden()

    raw_counts = {
        "engagements": container.conn.execute(
            "SELECT COUNT(*) FROM engagements WHERE id = ?", (engagement.id,)
        ).fetchone()[0],
        "tasks": container.conn.execute(
            "SELECT COUNT(*) FROM workflow_tasks WHERE id = ?", (task.id,)
        ).fetchone()[0],
        "requests": container.conn.execute(
            "SELECT COUNT(*) FROM document_requests WHERE id = ?", (request.id,)
        ).fetchone()[0],
        "request_items": container.conn.execute(
            "SELECT COUNT(*) FROM document_request_items WHERE id = ?", (items[0].id,)
        ).fetchone()[0],
        "attachments": container.conn.execute(
            "SELECT COUNT(*) FROM attachments WHERE id = ?", (attachment.id,)
        ).fetchone()[0],
        "plans": container.conn.execute(
            "SELECT COUNT(*) FROM recurring_billing_plans WHERE id = ?", (plan.id,)
        ).fetchone()[0],
        "lines": container.conn.execute(
            "SELECT COUNT(*) FROM recurring_billing_lines WHERE id = ?", (line.id,)
        ).fetchone()[0],
        "occurrences": container.conn.execute(
            "SELECT COUNT(*) FROM recurring_billing_occurrences WHERE id = ?",
            (occurrence.id,),
        ).fetchone()[0],
        "messages": container.conn.execute(
            "SELECT COUNT(*) FROM generated_messages WHERE id = ?", (message.id,)
        ).fetchone()[0],
    }
    assert set(raw_counts.values()) == {1}

    container.clients.restore_client(client.id)
    assert_visible()
