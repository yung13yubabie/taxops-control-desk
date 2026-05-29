"""Work records repository for workflow templates/runs and error reviews."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.clock import now_iso


@dataclass(frozen=True)
class WorkflowTemplateRow:
    id: int
    name: str
    stages_json: str
    version: int
    client_id: int | None
    engagement_id: int | None
    context_snapshot: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkflowRunRow:
    id: int
    template_id: int | None
    name: str
    stages_json: str
    client_id: int | None
    engagement_id: int | None
    context_snapshot: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ErrorReviewRow:
    id: int
    title: str
    phenomenon: str
    root_cause: str
    short_term_fix: str | None
    long_term_guard: str | None
    severity: str
    workflow_template_id: int | None
    guard_stage_id: str | None
    guard_step_text: str | None
    client_id: int | None
    engagement_id: int | None
    context_snapshot: str | None
    created_at: str
    updated_at: str


def _template(row: sqlite3.Row) -> WorkflowTemplateRow:
    return WorkflowTemplateRow(
        id=row["id"],
        name=row["name"],
        stages_json=row["stages_json"],
        version=row["version"],
        client_id=row["client_id"],
        engagement_id=row["engagement_id"],
        context_snapshot=row["context_snapshot"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run(row: sqlite3.Row) -> WorkflowRunRow:
    return WorkflowRunRow(
        id=row["id"],
        template_id=row["template_id"],
        name=row["name"],
        stages_json=row["stages_json"],
        client_id=row["client_id"],
        engagement_id=row["engagement_id"],
        context_snapshot=row["context_snapshot"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _error(row: sqlite3.Row) -> ErrorReviewRow:
    return ErrorReviewRow(
        id=row["id"],
        title=row["title"],
        phenomenon=row["phenomenon"],
        root_cause=row["root_cause"],
        short_term_fix=row["short_term_fix"],
        long_term_guard=row["long_term_guard"],
        severity=row["severity"],
        workflow_template_id=row["workflow_template_id"],
        guard_stage_id=row["guard_stage_id"],
        guard_step_text=row["guard_step_text"],
        client_id=row["client_id"],
        engagement_id=row["engagement_id"],
        context_snapshot=row["context_snapshot"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class WorkRecordsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_template(
        self,
        *,
        name: str,
        stages_json: str,
        client_id: int | None = None,
        engagement_id: int | None = None,
        context_snapshot: str | None = None,
    ) -> WorkflowTemplateRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO workflow_templates_v2("
            "name, stages_json, version, client_id, engagement_id, context_snapshot, created_at, updated_at"
            ") VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
            (name, stages_json, client_id, engagement_id, context_snapshot, ts, ts),
        )
        self._conn.commit()
        row = self.get_template(int(cur.lastrowid))
        if row is None:
            raise RuntimeError("inserted workflow template could not be reloaded")
        return row

    def get_template(self, template_id: int) -> WorkflowTemplateRow | None:
        row = self._conn.execute(
            "SELECT * FROM workflow_templates_v2 WHERE id = ? AND deleted_at IS NULL",
            (template_id,),
        ).fetchone()
        return _template(row) if row else None

    def list_templates(self) -> list[WorkflowTemplateRow]:
        rows = self._conn.execute(
            "SELECT * FROM workflow_templates_v2 WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC"
        ).fetchall()
        return [_template(r) for r in rows]

    def update_template_stages(
        self,
        template_id: int,
        *,
        name: str,
        stages_json: str,
        bump_version: bool,
    ) -> WorkflowTemplateRow | None:
        ts = now_iso()
        version_expr = "version + 1" if bump_version else "version"
        self._conn.execute(
            f"UPDATE workflow_templates_v2 SET name = ?, stages_json = ?, version = {version_expr}, updated_at = ?"
            " WHERE id = ? AND deleted_at IS NULL",
            (name, stages_json, ts, template_id),
        )
        self._conn.commit()
        return self.get_template(template_id)

    def insert_run(
        self,
        *,
        template_id: int | None,
        name: str,
        stages_json: str,
        client_id: int | None = None,
        engagement_id: int | None = None,
        context_snapshot: str | None = None,
    ) -> WorkflowRunRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO workflow_runs("
            "template_id, name, stages_json, client_id, engagement_id, context_snapshot, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (template_id, name, stages_json, client_id, engagement_id, context_snapshot, ts, ts),
        )
        self._conn.commit()
        row = self.get_run(int(cur.lastrowid))
        if row is None:
            raise RuntimeError("inserted workflow run could not be reloaded")
        return row

    def get_run(self, run_id: int) -> WorkflowRunRow | None:
        row = self._conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ? AND deleted_at IS NULL",
            (run_id,),
        ).fetchone()
        return _run(row) if row else None

    def list_runs(self) -> list[WorkflowRunRow]:
        rows = self._conn.execute(
            "SELECT * FROM workflow_runs WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC"
        ).fetchall()
        return [_run(r) for r in rows]

    def update_run_stages(self, run_id: int, *, stages_json: str) -> WorkflowRunRow | None:
        ts = now_iso()
        self._conn.execute(
            "UPDATE workflow_runs SET stages_json = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (stages_json, ts, run_id),
        )
        self._conn.commit()
        return self.get_run(run_id)

    def insert_error_review(
        self,
        *,
        title: str,
        phenomenon: str,
        root_cause: str,
        short_term_fix: str | None,
        long_term_guard: str | None,
        severity: str,
        workflow_template_id: int | None,
        guard_stage_id: str | None,
        guard_step_text: str | None,
        client_id: int | None,
        engagement_id: int | None,
        context_snapshot: str | None,
    ) -> ErrorReviewRow:
        ts = now_iso()
        cur = self._conn.execute(
            "INSERT INTO error_reviews("
            "title, phenomenon, root_cause, short_term_fix, long_term_guard, severity,"
            " workflow_template_id, guard_stage_id, guard_step_text, client_id, engagement_id,"
            " context_snapshot, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                phenomenon,
                root_cause,
                short_term_fix,
                long_term_guard,
                severity,
                workflow_template_id,
                guard_stage_id,
                guard_step_text,
                client_id,
                engagement_id,
                context_snapshot,
                ts,
                ts,
            ),
        )
        self._conn.commit()
        row = self.get_error_review(int(cur.lastrowid))
        if row is None:
            raise RuntimeError("inserted error review could not be reloaded")
        return row

    def get_error_review(self, review_id: int) -> ErrorReviewRow | None:
        row = self._conn.execute(
            "SELECT * FROM error_reviews WHERE id = ? AND deleted_at IS NULL",
            (review_id,),
        ).fetchone()
        return _error(row) if row else None

    def list_error_reviews(self) -> list[ErrorReviewRow]:
        rows = self._conn.execute(
            "SELECT * FROM error_reviews WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC"
        ).fetchall()
        return [_error(r) for r in rows]
