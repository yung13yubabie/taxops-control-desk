"""Stable, read-only navigation targets. A target never changes business data."""
from __future__ import annotations

from dataclasses import dataclass

from .action_registry import (
    PAGE_ANNUAL_WORKBENCH, PAGE_ATTACHMENTS, PAGE_CLIENTS, PAGE_ENGAGEMENTS,
    PAGE_FOLDER_BOOKMARKS, PAGE_LATE_FEE, PAGE_RECURRING_BILLING, PAGE_REGISTRY,
    PAGE_SETTINGS, PAGE_TASKS, PAGE_TEMPLATES, PAGE_WORK_RECORDS,
)

NAV_ICON_ROLES: dict[str, str] = {
    PAGE_CLIENTS: "nav-clients",
    PAGE_ANNUAL_WORKBENCH: "nav-calendar",
    PAGE_ENGAGEMENTS: "nav-engagements",
    PAGE_TASKS: "nav-tasks",
    PAGE_WORK_RECORDS: "nav-work-records",
    PAGE_TEMPLATES: "nav-templates",
    PAGE_REGISTRY: "nav-registry",
    PAGE_LATE_FEE: "trial",
    PAGE_ATTACHMENTS: "nav-attachments",
    PAGE_FOLDER_BOOKMARKS: "nav-folders",
    PAGE_RECURRING_BILLING: "nav-billing",
    PAGE_SETTINGS: "nav-settings",
}


@dataclass(frozen=True)
class NavigationTarget:
    page_id: str
    engagement_id: int | None = None
    request_id: int | None = None
    task_id: int | None = None
    attachment_id: int | None = None
