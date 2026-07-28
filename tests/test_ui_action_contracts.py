"""UI action contract registry consistency checks."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from taxops.i18n import DISABLED_TOOLTIP, NAV_LABELS
from taxops.ui.action_registry import (
    ACTION_REGISTRY,
    NAV_ORDER,
    PAGE_ANNUAL_WORKBENCH,
    PAGE_DOC_REQUESTS,
    PLACEHOLDER_HANDLER,
    actions_for_page,
)

# Pages whose contracts still exist even though the page is no longer a
# sidebar destination (Slice 21B: doc_requests merged into engagements as
# an embedded widget).
_EMBEDDED_ONLY_PAGES = {PAGE_DOC_REQUESTS}

_HANDLER_MODULES = {
    "AnnualWorkbenchPage": "taxops.ui.pages.annual_workbench_page",
    "AnnualWorkspaceDialog": "taxops.ui.dialogs.annual_workspace_dialog",
    "AnnualItemDetail": "taxops.ui.widgets.annual_item_detail",
    "AnnualItemDialog": "taxops.ui.dialogs.annual_item_dialog",
    "AnnualWorkflowDialog": "taxops.ui.dialogs.annual_workflow_dialog",
    "CreateLinkedRequestDialog": "taxops.ui.dialogs.annual_workflow_dialog",
    "LinkExistingEngagementDialog": "taxops.ui.dialogs.annual_workflow_dialog",
    "AnnualTransactionPanel": "taxops.ui.widgets.annual_transaction_panel",
    "AnnualAttachmentPanel": "taxops.ui.widgets.annual_attachment_panel",
    "AnnualTaskPanel": "taxops.ui.widgets.annual_task_panel",
    "AttachmentsPage": "taxops.ui.pages.attachments_page",
    "ClientsPage": "taxops.ui.pages.clients_page",
    "DocumentRequestsPage": "taxops.ui.pages.document_requests_page",
    "EditClientDialog": "taxops.ui.dialogs.edit_client_dialog",
    "EditEngagementDialog": "taxops.ui.dialogs.edit_engagement_dialog",
    "EngagementsPage": "taxops.ui.pages.engagements_page",
    "FolderBookmarksPage": "taxops.ui.pages.folder_bookmarks_page",
    "LateFeePage": "taxops.ui.pages.late_fee_page",
    "NewClientDialog": "taxops.ui.dialogs.new_client_dialog",
    "NewEngagementDialog": "taxops.ui.dialogs.new_engagement_dialog",
    "RecurringBillingPage": "taxops.ui.pages.recurring_billing_page",
    "RegistryPage": "taxops.ui.pages.registry_page",
    "SettingsPage": "taxops.ui.pages.settings_page",
    "TasksPage": "taxops.ui.pages.tasks_page",
    "TemplateFormDialog": "taxops.ui.dialogs.template_form_dialog",
    "TemplatesPage": "taxops.ui.pages.templates_page",
    "WorkRecordsPage": "taxops.ui.pages.work_records_page",
    "_ClientGroup": "taxops.ui.pages.recurring_billing_page",
    "_LineRow": "taxops.ui.pages.recurring_billing_page",
    "_OccRow": "taxops.ui.pages.recurring_billing_page",
    "_PlanSection": "taxops.ui.pages.recurring_billing_page",
}


def test_create_annual_workspace_action_contract_is_enabled_and_precise() -> None:
    by_label = {
        action.button_label: action
        for action in actions_for_page(PAGE_ANNUAL_WORKBENCH)
    }
    assert set(by_label) == {
        "建立年度工作",
        "搜尋客戶",
        "載入預覽",
        "新增自訂列",
        "確認建立",
        "取消",
        "開啟明細",
        "儲存明細",
        "完成工作",
        "取消此工作",
        "還原",
        "重新開啟",
        "協作管理",
        "建立第一筆索件",
        "連結既有案件",
        "重新整理索件",
        "重新讀取索件",
        "關閉協作管理",
        "上傳案件共用附件",
        "標記附件已驗收",
        "標記附件退回",
        "封存附件",
        "重新核對附件",
        "附件上一頁",
        "附件下一頁",
        "建立年度待辦",
        "完成年度待辦",
        "更新待辦狀態",
        "刪除年度待辦",
        "重新核對待辦",
        "待辦上一頁",
        "待辦下一頁",
        "建立索件",
        "取消建立索件",
        "連結案件",
        "取消連結案件",
        "新增交易",
        "編輯交易",
        "刪除交易",
        "重新讀取交易",
        "交易上一頁",
        "交易下一頁",
    }

    opener = by_label["建立年度工作"]
    assert opener.enabled is True
    assert opener.handler == "AnnualWorkbenchPage._open_create_dialog"
    assert opener.service is None
    assert opener.repository is None
    assert opener.audit_action is None
    assert opener.success_text == ""
    assert opener.failure_text == ""

    search = by_label["搜尋客戶"]
    assert search.handler == "AnnualWorkspaceDialog._search_clients"
    assert search.service == (
        "AnnualClientSearchWorker.run (isolated read-only connection)"
    )
    assert search.repository == (
        "clients active query LIMIT 101 + optional id lookup"
    )
    assert search.audit_action is None
    assert search.success_text == "找到 N 筆客戶。"
    assert search.failure_text == "載入客戶失敗，請稍後再試。"

    preview = by_label["載入預覽"]
    assert preview.handler == "AnnualWorkspaceDialog._load_preview"
    assert preview.service == "AnnualWorkService.preview"
    assert preview.repository == "ComplianceProfilesRepository.get_for_client"
    assert preview.audit_action is None
    assert preview.success_text == "已載入 N 項年度工作預覽。"
    assert preview.failure_text == "載入預覽失敗，請稍後再試。"

    custom = by_label["新增自訂列"]
    assert custom.handler == "AnnualWorkspaceDialog._add_custom"
    assert custom.service is None
    assert custom.repository is None
    assert custom.audit_action is None

    confirm = by_label["確認建立"]
    assert confirm.handler == "AnnualWorkspaceDialog._confirm"
    assert confirm.service == "AnnualWorkService.confirm_preview_selection"
    assert confirm.repository == "AnnualWorkRepository.insert_item_if_missing"
    assert confirm.audit_action == "annual_workspace.confirm"
    assert confirm.success_text == "建立成功，已新增 N 項年度工作。"
    assert confirm.failure_text == "建立年度工作失敗，請稍後再試。"

    cancel = by_label["取消"]
    assert cancel.handler == "AnnualWorkspaceDialog.reject"
    assert cancel.service is None
    assert cancel.repository is None
    assert cancel.audit_action is None


def test_every_action_targets_a_known_page() -> None:
    for action in ACTION_REGISTRY:
        assert action.page in NAV_ORDER or action.page in _EMBEDDED_ONLY_PAGES, action
        assert action.page in NAV_LABELS, action


def test_action_labels_are_chinese_and_non_empty() -> None:
    for action in ACTION_REGISTRY:
        assert action.button_label.strip()
        assert any("一" <= ch <= "鿿" for ch in action.button_label), action


def test_enabled_actions_have_real_handler() -> None:
    for action in ACTION_REGISTRY:
        if action.enabled:
            assert action.handler != PLACEHOLDER_HANDLER, action


def test_enabled_action_handler_strings_resolve_to_callables() -> None:
    for action in ACTION_REGISTRY:
        if not action.enabled:
            continue
        class_name, method_name = action.handler.split(".", 1)
        module = import_module(_HANDLER_MODULES[class_name])
        handler = getattr(getattr(module, class_name), method_name)
        assert callable(handler), action


def test_action_coverage_hints_are_explicit_scenario_ids() -> None:
    for action in ACTION_REGISTRY:
        assert action.test_marker.startswith("test_"), action
        assert action.test_marker.strip(), action


def test_every_annual_action_marker_names_a_collected_test_function() -> None:
    tests_root = Path(__file__).parent
    function_names: set[str] = set()
    for test_file in tests_root.glob("test_*.py"):
        module = ast.parse(test_file.read_text(encoding="utf-8"))
        function_names.update(
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    for action in actions_for_page(PAGE_ANNUAL_WORKBENCH):
        assert action.test_marker in function_names, action


def test_audit_action_implies_service_and_repository() -> None:
    for action in ACTION_REGISTRY:
        if action.audit_action is not None:
            assert action.service, action
            assert action.repository, action


def test_action_keys_are_unique() -> None:
    seen: set[tuple[str, str]] = set()
    for action in ACTION_REGISTRY:
        key = (action.page, action.button_label)
        assert key not in seen, f"duplicate action contract: {key}"
        seen.add(key)


def test_every_nav_page_has_at_least_one_action() -> None:
    for page in NAV_ORDER:
        assert actions_for_page(page), page


def test_disabled_actions_marked_via_placeholder() -> None:
    for action in ACTION_REGISTRY:
        if not action.enabled:
            assert action.handler == PLACEHOLDER_HANDLER, action
            assert action.service is None
            assert action.repository is None
            assert action.audit_action is None


def test_disabled_tooltip_is_canonical_chinese() -> None:
    assert DISABLED_TOOLTIP == "此功能尚未開放"
