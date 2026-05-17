"""Dashboard aggregation service.

Computes a live snapshot of eight counts from the database.
The ``today`` parameter is injectable so tests can fix the reference date.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from ..repositories.dashboard import DashboardRepository

_UPCOMING_DAYS = 7


@dataclass(frozen=True)
class DashboardCounts:
    tasks_due_today: int
    tasks_overdue: int
    waiting_client: int
    open_review_notes: int
    missing_item_requests: int
    upcoming_engagements: int
    overdue_engagements: int
    high_risk_engagements: int


class DashboardService:
    def __init__(self, repo: DashboardRepository) -> None:
        self._repo = repo

    def get_counts(self, *, today: str | None = None) -> DashboardCounts:
        if today is None:
            today = datetime.date.today().isoformat()
        until = (
            datetime.date.fromisoformat(today)
            + datetime.timedelta(days=_UPCOMING_DAYS)
        ).isoformat()
        return DashboardCounts(
            tasks_due_today=self._repo.count_tasks_due_today(today),
            tasks_overdue=self._repo.count_tasks_overdue(today),
            waiting_client=self._repo.count_waiting_client(),
            open_review_notes=self._repo.count_open_review_notes(),
            missing_item_requests=self._repo.count_missing_item_requests(),
            upcoming_engagements=self._repo.count_upcoming_engagements(today, until),
            overdue_engagements=self._repo.count_overdue_engagements(today),
            high_risk_engagements=self._repo.count_high_risk_engagements(),
        )
