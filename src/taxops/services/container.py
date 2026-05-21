"""Lightweight service container used by the UI and tests.

Holds the SQLite connection plus all repositories and services. The UI
shell receives the container; pages pull only the services they need.

The container takes ownership of the SQLite connection — callers must not
close the connection separately.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..core.paths import AppPaths
from ..repositories.app_settings import AppSettingsRepository
from ..repositories.attachments import AttachmentsRepository
from ..repositories.audit_logs import AuditLogRepository
from ..repositories.clients import ClientsRepository
from ..repositories.document_requests import DocumentRequestsRepository
from ..repositories.engagements import EngagementsRepository
from ..repositories.registry_matches import RegistryMatchRepository
from ..repositories.system_logs import SystemLogRepository
from ..repositories.generated_messages import GeneratedMessagesRepository
from ..repositories.late_fee import LateFeeRepository
from ..repositories.review_notes import ReviewNotesRepository
from ..repositories.backup import BackupRepository
from ..repositories.dashboard import DashboardRepository
from ..repositories.search import SearchRepository
from ..repositories.recurring_billing import RecurringBillingRepository
from ..repositories.tasks import TasksRepository
from ..repositories.templates import TemplatesRepository
from ..repositories.tax_registry import (
    TaxCacheMetadataRepository,
    TaxRegistryRepository,
)
from .audit import AuditService
from .clients import ClientsService
from .document_requests import DocumentRequestsService
from .engagements import EngagementsService
from .registry.bundle import TaxCacheBundleService
from .registry.importer import TaxRegistryImporter
from .registry.matcher import RegistryMatcher
from .settings import SettingsService
from .system_log import SystemLogService
from .attachments import AttachmentsService
from .backup import BackupService
from .dashboard import DashboardService
from .export import ExportService
from .search import SearchService
from .generated_messages import GeneratedMessagesService
from .late_fee import LateFeeService
from .review_notes import ReviewNotesService
from .recurring_billing import RecurringBillingService
from .tasks import TasksService
from .templates import TemplatesService


@dataclass
class ServiceContainer:
    paths: AppPaths
    conn: sqlite3.Connection
    settings: SettingsService
    clients: ClientsService
    clients_repo: ClientsRepository
    audit: AuditService
    system_log: SystemLogService
    tax_cache_importer: TaxRegistryImporter
    tax_cache_bundle: TaxCacheBundleService
    tax_cache_matcher: RegistryMatcher
    tax_registry_repo: TaxRegistryRepository
    tax_cache_metadata_repo: TaxCacheMetadataRepository
    engagements: EngagementsService
    doc_requests: DocumentRequestsService
    tasks: TasksService
    templates: TemplatesService
    gen_messages: GeneratedMessagesService
    review_notes: ReviewNotesService
    late_fee: LateFeeService
    attachments: AttachmentsService
    export: ExportService
    backup: BackupService
    dashboard: DashboardService
    search: SearchService
    recurring_billing: RecurringBillingService

    def close(self) -> None:
        """Close the owned SQLite connection.

        Errors propagate — silent failure here would mask a leaked or
        already-closed connection bug.
        """
        self.conn.close()


def build_container(paths: AppPaths, conn: sqlite3.Connection) -> ServiceContainer:
    """Wire up repositories and services for a given DB connection."""
    audit_repo = AuditLogRepository(conn)
    system_log_repo = SystemLogRepository(conn)
    settings_repo = AppSettingsRepository(conn)
    clients_repo = ClientsRepository(conn)
    tax_registry_repo = TaxRegistryRepository(conn)
    tax_cache_metadata_repo = TaxCacheMetadataRepository(conn)
    match_repo = RegistryMatchRepository(conn)
    engagements_repo = EngagementsRepository(conn)
    doc_requests_repo = DocumentRequestsRepository(conn)
    tasks_repo = TasksRepository(conn)

    settings_repo.seed_defaults()

    actor = settings_repo.get("display.local_user_name") or "local_user"
    audit_service = AuditService(audit_repo, actor=actor)
    system_log_service = SystemLogService(system_log_repo)
    settings_service = SettingsService(settings_repo, audit_service)
    search_repo = SearchRepository(conn)
    clients_service = ClientsService(clients_repo, audit_service, search_repo)
    engagements_service = EngagementsService(engagements_repo, audit_service, search_repo)
    doc_requests_service = DocumentRequestsService(doc_requests_repo, audit_service)
    tasks_service = TasksService(tasks_repo, audit_service)
    templates_repo = TemplatesRepository(conn)
    templates_service = TemplatesService(templates_repo, audit_service)
    gen_messages_repo = GeneratedMessagesRepository(conn)
    gen_messages_service = GeneratedMessagesService(
        repo=gen_messages_repo,
        doc_requests_repo=doc_requests_repo,
        engagements_repo=engagements_repo,
        clients_repo=clients_repo,
        templates_svc=templates_service,
        audit=audit_service,
    )

    review_notes_repo = ReviewNotesRepository(conn)
    review_notes_service = ReviewNotesService(
        repo=review_notes_repo,
        engagements_repo=engagements_repo,
        audit=audit_service,
    )
    late_fee_repo = LateFeeRepository(conn)
    late_fee_service = LateFeeService(
        repo=late_fee_repo,
        doc_requests_repo=doc_requests_repo,
        audit=audit_service,
    )
    attachments_repo = AttachmentsRepository(conn)
    attachments_service = AttachmentsService(
        repo=attachments_repo,
        attachments_dir=paths.attachments_dir,
        audit=audit_service,
    )
    export_service = ExportService(
        repo=doc_requests_repo,
        audit=audit_service,
    )
    backup_repo = BackupRepository(conn)
    backup_service = BackupService(
        conn=conn,
        repo=backup_repo,
        audit=audit_service,
    )
    search_service = SearchService(
        repo=search_repo,
        clients_repo=clients_repo,
        engagements_repo=engagements_repo,
    )
    dashboard_repo = DashboardRepository(conn)
    dashboard_service = DashboardService(dashboard_repo)

    recurring_billing_repo = RecurringBillingRepository(conn)
    recurring_billing_service = RecurringBillingService(
        repo=recurring_billing_repo,
        audit=audit_service,
    )

    tax_cache_importer = TaxRegistryImporter(
        registry_repo=tax_registry_repo,
        metadata_repo=tax_cache_metadata_repo,
        audit=audit_service,
        system_log=system_log_service,
    )
    tax_cache_bundle = TaxCacheBundleService(
        registry_repo=tax_registry_repo,
        metadata_repo=tax_cache_metadata_repo,
        audit=audit_service,
        system_log=system_log_service,
    )
    tax_cache_matcher = RegistryMatcher(
        clients_repo=clients_repo,
        registry_repo=tax_registry_repo,
        match_repo=match_repo,
        metadata_repo=tax_cache_metadata_repo,
        audit=audit_service,
    )

    return ServiceContainer(
        paths=paths,
        conn=conn,
        settings=settings_service,
        clients=clients_service,
        clients_repo=clients_repo,
        audit=audit_service,
        system_log=system_log_service,
        tax_cache_importer=tax_cache_importer,
        tax_cache_bundle=tax_cache_bundle,
        tax_cache_matcher=tax_cache_matcher,
        tax_registry_repo=tax_registry_repo,
        tax_cache_metadata_repo=tax_cache_metadata_repo,
        engagements=engagements_service,
        doc_requests=doc_requests_service,
        tasks=tasks_service,
        templates=templates_service,
        gen_messages=gen_messages_service,
        review_notes=review_notes_service,
        late_fee=late_fee_service,
        attachments=attachments_service,
        export=export_service,
        backup=backup_service,
        dashboard=dashboard_service,
        search=search_service,
        recurring_billing=recurring_billing_service,
    )
