"""Dashboard aggregation service.

Computes a live snapshot of eight counts from the database.
The ``today`` parameter is injectable so tests can fix the reference date.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from ..repositories.dashboard import DashboardRepository

_UPCOMING_DAYS = 7
_LEASE_EXPIRY_DAYS = 30


@dataclass(frozen=True)
class DashboardCounts:
    tasks_due_today: int
    tasks_overdue: int
    waiting_client: int
    missing_item_requests: int
    upcoming_engagements: int
    overdue_engagements: int
    lease_expiring_soon: int


class DashboardService:
    def __init__(self, repo: DashboardRepository) -> None:
        self._repo = repo

    def get_counts(self, *, today: str | None = None) -> DashboardCounts:
        if today is None:
            today = datetime.date.today().isoformat()
        today_date = datetime.date.fromisoformat(today)
        until = (today_date + datetime.timedelta(days=_UPCOMING_DAYS)).isoformat()
        until_lease = (today_date + datetime.timedelta(days=_LEASE_EXPIRY_DAYS)).isoformat()
        return DashboardCounts(
            tasks_due_today=self._repo.count_tasks_due_today(today),
            tasks_overdue=self._repo.count_tasks_overdue(today),
            waiting_client=self._repo.count_waiting_client(),
            missing_item_requests=self._repo.count_missing_item_requests(),
            upcoming_engagements=self._repo.count_upcoming_engagements(today, until),
            overdue_engagements=self._repo.count_overdue_engagements(today),
            lease_expiring_soon=self._repo.count_lease_expiring_soon(today, until_lease),
        )
