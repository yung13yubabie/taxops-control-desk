"""Slice 7 UI smoke tests: DocumentRequestsPage generate button + GenerateMessageDialog."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from taxops.db.connection import open_connection
from taxops.db.migrate import apply_migrations
from taxops.repositories.app_settings import AppSettingsRepository
from taxops.repositories.audit_logs import AuditLogRepository
from taxops.repositories.clients import ClientsRepository
from taxops.repositories.document_requests import DocumentRequestsRepository
from taxops.repositories.engagements import EngagementsRepository
from taxops.repositories.generated_messages import GeneratedMessagesRepository
from taxops.repositories.system_logs import SystemLogRepository
from taxops.repositories.templates import TemplatesRepository
from taxops.services.audit import AuditService
from taxops.services.clients import ClientsService
from taxops.services.document_requests import DocumentRequestsService
from taxops.services.engagements import EngagementsService
from taxops.services.generated_messages import GeneratedMessagesService
from taxops.services.settings import SettingsService
from taxops.services.system_log import SystemLogService
from taxops.services.templates import TemplatesService
from taxops.ui.dialogs.generate_message_dialog import GenerateMessageDialog
from taxops.ui.pages.document_requests_page import DocumentRequestsPage


# ── QApplication singleton ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


# ── DB + fake container ───────────────────────────────────────────────────────

class _FakeContainer:
    def __init__(self, conn):
        audit_repo = AuditLogRepository(conn)
        self._audit = AuditService(audit_repo, actor="ui_test")
        self.system_log = SystemLogService(SystemLogRepository(conn))
        self.engagements = EngagementsService(EngagementsRepository(conn), self._audit)
        self.clients = ClientsService(ClientsRepository(conn), self._audit)
        self.doc_requests = DocumentRequestsService(DocumentRequestsRepository(conn), self._audit)
        tmpl_repo = TemplatesRepository(conn)
        self.templates = TemplatesService(tmpl_repo, self._audit)
        self.gen_messages = GeneratedMessagesService(
            repo=GeneratedMessagesRepository(conn),
            doc_requests_repo=DocumentRequestsRepository(conn),
            engagements_repo=EngagementsRepository(conn),
            clients_repo=ClientsRepository(conn),
            templates_svc=self.templates,
            audit=self._audit,
        )
        settings_repo = AppSettingsRepository(conn)
        settings_repo.seed_defaults()
        self.settings = SettingsService(settings_repo, self._audit)


@pytest.fixture()
def conn(tmp_path):
    c = open_connection(tmp_path / "ui7_test.db")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture()
def container(conn):
    return _FakeContainer(conn)


def _seed(conn) -> tuple[int, int]:
    """Insert client + engagement + document_request; return (eng_id, req_id)."""
    ts = "2024-01-01T00:00:00"
    cur = conn.execute(
        "INSERT INTO clients(client_code, client_name, created_at, updated_at) VALUES (?,?,?,?)",
        ("C001", "UI測試公司", ts, ts),
    )
    client_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO engagements(client_id, engagement_name, tax_type, period_name, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (client_id, "UI案件", "vat", "2024Q1", "active", ts, ts),
    )
    eng_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO document_requests(engagement_id, tax_type, period_name, status, follow_up_count, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (eng_id, "vat", "2024Q1", "requested", 0, ts, ts),
    )
    req_id = cur.lastrowid
    conn.commit()
    return eng_id, req_id


# ── DocumentRequestsPage: generate button ─────────────────────────────────────

@pytest.fixture()
def page(qapp, container):
    w = DocumentRequestsPage(container)
    w.show()
    return w


def test_doc_requests_page_instantiates(page):
    assert page is not None


def test_generate_btn_disabled_without_engagement(page):
    assert not page._generate_btn.isEnabled()


def test_generate_btn_disabled_without_selection(conn, container, page):
    eng_id, _ = _seed(conn)
    page.load_engagement(eng_id)
    # No row selected yet — button must stay disabled
    assert not page._generate_btn.isEnabled()


def test_generate_btn_enabled_after_row_selection(conn, container, page):
    eng_id, _ = _seed(conn)
    page.load_engagement(eng_id)
    page._req_table.selectRow(0)
    assert page._generate_btn.isEnabled()


# ── GenerateMessageDialog ─────────────────────────────────────────────────────

def test_dialog_instantiates(qapp, conn, container):
    _, req_id = _seed(conn)
    dlg = GenerateMessageDialog(
        gen_svc=container.gen_messages,
        templates_svc=container.templates,
        request_id=req_id,
    )
    assert dlg is not None
    assert dlg.windowTitle() == "產生催件訊息"


def test_dialog_save_btn_disabled_initially(qapp, conn, container):
    _, req_id = _seed(conn)
    dlg = GenerateMessageDialog(
        gen_svc=container.gen_messages,
        templates_svc=container.templates,
        request_id=req_id,
    )
    assert not dlg._save_btn.isEnabled()
    assert not dlg._copy_btn.isEnabled()


def test_dialog_has_builtin_templates_in_combo(qapp, conn, container):
    _, req_id = _seed(conn)
    dlg = GenerateMessageDialog(
        gen_svc=container.gen_messages,
        templates_svc=container.templates,
        request_id=req_id,
    )
    # combo has "— 請選擇 —" + at least 2 builtin templates
    assert dlg._template_combo.count() >= 3


def test_dialog_select_template_preview_save_persists(qapp, conn, container):
    _, req_id = _seed(conn)
    dlg = GenerateMessageDialog(
        gen_svc=container.gen_messages,
        templates_svc=container.templates,
        request_id=req_id,
    )
    # Select first real template (index 1 = builtin id=1)
    dlg._template_combo.setCurrentIndex(1)
    # Preview should now contain rendered text
    assert len(dlg._preview.toPlainText()) > 0
    assert dlg._save_btn.isEnabled()
    # Trigger save directly
    dlg._on_save()
    # Verify DB has the generated message
    msgs = container.gen_messages.list_by_request(req_id)
    assert len(msgs) == 1
    assert msgs[0].request_id == req_id
    assert len(msgs[0].body) > 0


def test_dialog_save_records_audit(qapp, conn, container):
    _, req_id = _seed(conn)
    dlg = GenerateMessageDialog(
        gen_svc=container.gen_messages,
        templates_svc=container.templates,
        request_id=req_id,
    )
    dlg._template_combo.setCurrentIndex(1)
    dlg._on_save()
    row = conn.execute(
        "SELECT action FROM audit_logs WHERE action = 'gen_message.create' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["action"] == "gen_message.create"
