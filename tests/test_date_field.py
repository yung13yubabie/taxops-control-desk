"""Comprehensive tests for the DateField widget -- no sentinel values, clean semantics."""

from __future__ import annotations

import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# 1. Optional field initial state
# ---------------------------------------------------------------------------

def test_optional_init_value_is_none(qapp: QApplication) -> None:
    """Optional DateField starts with None -- NOT 1752, 1900, or 2000-01-01."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    assert field.value() is None
    assert field.raw_text() == ""


def test_optional_init_text_is_empty(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    assert field.raw_text() == ""


def test_optional_clear_button_is_visible(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    # isHidden() checks this widget's own flag; isVisible() requires full parent chain shown
    assert not field._clear_btn.isHidden()


# ---------------------------------------------------------------------------
# 2. Required field initial state
# ---------------------------------------------------------------------------

def test_required_init_value_is_today(qapp: QApplication) -> None:
    """Required DateField starts with local today's date."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=True)
    today = datetime.date.today().isoformat()
    assert field.value() == today


def test_required_clear_button_is_hidden(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=True)
    assert not field._clear_btn.isVisible()


# ---------------------------------------------------------------------------
# 3. set_value / value round-trip
# ---------------------------------------------------------------------------

def test_set_value_2000_01_01_returns_correctly(qapp: QApplication) -> None:
    """2000-01-01 is a valid real date and must NOT be treated as null sentinel."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field.set_value("2000-01-01")
    assert field.value() == "2000-01-01"
    assert field.raw_text() == "2000-01-01"


def test_set_value_valid_iso_roundtrips(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field.set_value("2026-05-21")
    assert field.value() == "2026-05-21"


def test_set_value_none_clears_field(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field.set_value("2026-03-15")
    field.set_value(None)
    assert field.value() is None
    assert field.raw_text() == ""


def test_set_value_invalid_iso_clears_field(qapp: QApplication) -> None:
    """Unrecognised value on set_value clears the field (programmer error path)."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field.set_value("not-a-date")
    assert field.value() is None
    assert field.raw_text() == ""


# ---------------------------------------------------------------------------
# 4. clear()
# ---------------------------------------------------------------------------

def test_clear_optional_returns_none(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field.set_value("2026-06-01")
    field.clear()
    assert field.value() is None


def test_clear_required_does_not_change_value(qapp: QApplication) -> None:
    """Required field's clear() is a no-op -- value remains today."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=True)
    today = datetime.date.today().isoformat()
    field.clear()
    assert field.value() == today


# ---------------------------------------------------------------------------
# 5. Invalid manual input -- must NOT silently become None / must show error
# ---------------------------------------------------------------------------

def test_invalid_text_value_returns_none(qapp: QApplication) -> None:
    """value() returns None for invalid text, but raw_text preserves input."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field._edit.setText("not-a-date")
    assert field.value() is None
    assert field.raw_text() == "not-a-date"


def test_invalid_text_raw_text_preserved(qapp: QApplication) -> None:
    """Bad input is preserved in raw_text -- not silently wiped."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field._edit.setText("2026-99-99")
    assert field.raw_text() == "2026-99-99"
    assert field.value() is None


def test_editing_finished_with_invalid_date_shows_error(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field._edit.setText("not-a-date")
    field._on_editing_finished()
    assert not field._error_label.isHidden()
    assert field._error_label.text() != ""


def test_editing_finished_with_valid_date_clears_error(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field._edit.setText("not-a-date")
    field._on_editing_finished()
    assert not field._error_label.isHidden()

    field._edit.setText("2026-02-28")
    field._on_editing_finished()
    assert field._error_label.isHidden()


# ---------------------------------------------------------------------------
# 6. value_changed signal
# ---------------------------------------------------------------------------

def test_clear_emits_value_changed_none(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field.set_value("2026-01-01")

    received: list = []
    field.value_changed.connect(received.append)
    field.clear()
    assert received == [None]


def test_on_date_confirmed_emits_value_changed(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    received: list = []
    field.value_changed.connect(received.append)
    field._on_date_confirmed("2026-07-04")
    assert received == ["2026-07-04"]
    assert field.value() == "2026-07-04"


# ---------------------------------------------------------------------------
# 7. Sentinel / null-representation audit (codebase-level)
# ---------------------------------------------------------------------------

def test_no_sentinel_date_constant_in_shared() -> None:
    """Ensure the old _SENTINEL_DATE pattern is gone from shared UI modules."""
    import taxops.ui.dialogs._shared as shared_mod
    src = open(shared_mod.__file__, encoding="utf-8").read()
    assert "_SENTINEL_DATE" not in src
    assert "make_nullable_date_edit" not in src


def test_no_make_nullable_date_edit_import_in_client_dialogs() -> None:
    """Client dialogs must not import the old sentinel helpers."""
    import taxops.ui.dialogs.edit_client_dialog as mod
    src = open(mod.__file__, encoding="utf-8").read()
    assert "make_nullable_date_edit" not in src
    assert "_SENTINEL_DATE" not in src


# ---------------------------------------------------------------------------
# 8. set_error / error label
# ---------------------------------------------------------------------------

def test_set_error_shows_label(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field.set_error("test error")
    assert not field._error_label.isHidden()
    assert field._error_label.text() == "test error"


def test_set_error_none_hides_label(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field.set_error("test error")
    field.set_error(None)
    assert field._error_label.isHidden()


# ---------------------------------------------------------------------------
# 9. Dialog construction -- all consumer dialogs must not crash
# ---------------------------------------------------------------------------

def test_new_engagement_dialog_constructs(qapp: QApplication, container) -> None:
    from taxops.ui.dialogs.new_engagement_dialog import NewEngagementDialog
    from taxops.services.clients import CreateClientInput

    client = container.clients.create_client(
        CreateClientInput(client_code="DLGSM01", client_name="對話框冒煙")
    )
    dlg = NewEngagementDialog(container.engagements, client_id=client.id)
    assert dlg._due_date.value() is None


def test_edit_engagement_dialog_loads_existing_date(qapp: QApplication, container) -> None:
    from taxops.ui.dialogs.edit_engagement_dialog import EditEngagementDialog
    from taxops.services.clients import CreateClientInput
    from taxops.services.engagements import CreateEngagementInput

    client = container.clients.create_client(
        CreateClientInput(client_code="DLGSM02", client_name="案件編輯冒煙")
    )
    eng = container.engagements.create_engagement(
        CreateEngagementInput(
            client_id=client.id,
            engagement_name="測試案件",
            tax_type="vat",
            period_name="2026",
            due_date="2026-12-31",
        )
    )
    row = container.engagements.get_engagement(eng.id)
    dlg = EditEngagementDialog(container.engagements, row)
    assert dlg._due_date.value() == "2026-12-31"


def test_new_task_dialog_constructs(qapp: QApplication, container) -> None:
    from taxops.ui.dialogs.new_task_dialog import NewTaskDialog

    dlg = NewTaskDialog(container.tasks)
    assert dlg._due_date.value() is None


def test_edit_client_dialog_constructs(qapp: QApplication, container) -> None:
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog
    from taxops.services.clients import CreateClientInput

    client = container.clients.create_client(
        CreateClientInput(client_code="DLGSM03", client_name="客戶編輯冒煙")
    )
    row = container.clients.get_client(client.id)
    dlg = EditClientDialog(container.clients, row)
    assert dlg._lease_start.value() is None
    assert dlg._lease_end.value() is None


def test_edit_client_dialog_loads_lease_dates(qapp: QApplication, container) -> None:
    from taxops.ui.dialogs.edit_client_dialog import EditClientDialog
    from taxops.services.clients import CreateClientInput

    client = container.clients.create_client(
        CreateClientInput(
            client_code="DLGSM04",
            client_name="租約日期客戶",
            lease_start="2026-01-01",
            lease_end="2026-12-31",
        )
    )
    row = container.clients.get_client(client.id)
    dlg = EditClientDialog(container.clients, row)
    assert dlg._lease_start.value() == "2026-01-01"
    assert dlg._lease_end.value() == "2026-12-31"


# ---------------------------------------------------------------------------
# 10. Calendar popup: empty field opens to today, value stays None
# ---------------------------------------------------------------------------

def test_calendar_popup_empty_navigates_to_today(qapp: QApplication) -> None:
    """When field is empty the popup navigates to today's month."""
    from taxops.ui.widgets.date_field import _CalendarPopup

    popup = _CalendarPopup(current_iso=None)
    today = QDate.currentDate()
    assert popup._cal.yearShown() == today.year()
    assert popup._cal.monthShown() == today.month()
    popup.close()


def test_calendar_popup_with_value_shows_that_date(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import _CalendarPopup

    popup = _CalendarPopup(current_iso="2025-03-15")
    assert popup._cal.yearShown() == 2025
    assert popup._cal.monthShown() == 3
    assert popup._cal.selectedDate() == QDate(2025, 3, 15)
    popup.close()


def test_calendar_popup_today_button_confirms_today(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import _CalendarPopup

    popup = _CalendarPopup(current_iso=None)
    received: list = []
    popup.date_confirmed.connect(received.append)
    popup._select_today()
    today_iso = datetime.date.today().isoformat()
    assert today_iso in received


def test_date_field_calendar_confirm_updates_value(qapp: QApplication) -> None:
    """Simulating a calendar confirm: field value updates from None to confirmed date."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    assert field.value() is None

    field._on_date_confirmed("2026-09-09")
    assert field.value() == "2026-09-09"


# ---------------------------------------------------------------------------
# 11. Late fee page: date pair validation at service layer
# ---------------------------------------------------------------------------

def test_late_fee_service_only_last_payment_date_raises(container) -> None:
    """Only one date must raise, not silently compute 0 penalty."""
    from taxops.services.late_fee import CalculateLateFeeInput, LateFeeValidationError

    with pytest.raises(LateFeeValidationError) as exc:
        container.late_fee.calculate_and_save(
            CalculateLateFeeInput(
                request_id=1,
                overdue_days=0,
                base_amount=10000,
                last_payment_date="2026-05-01",
                actual_payment_date=None,
            )
        )
    assert exc.value.code == "late_fee.date.required_pair"


def test_late_fee_service_only_actual_payment_date_raises(container) -> None:
    from taxops.services.late_fee import CalculateLateFeeInput, LateFeeValidationError

    with pytest.raises(LateFeeValidationError) as exc:
        container.late_fee.calculate_and_save(
            CalculateLateFeeInput(
                request_id=1,
                overdue_days=0,
                base_amount=10000,
                last_payment_date=None,
                actual_payment_date="2026-05-15",
            )
        )
    assert exc.value.code == "late_fee.date.required_pair"


# ---------------------------------------------------------------------------
# 12. validated_value() -- strict API
# ---------------------------------------------------------------------------

def test_validated_value_empty_returns_none(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    assert field.validated_value() is None


def test_validated_value_valid_date_returns_iso(qapp: QApplication) -> None:
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field._edit.setText("2026-08-15")
    assert field.validated_value() == "2026-08-15"


def test_validated_value_invalid_text_raises(qapp: QApplication) -> None:
    """Non-empty invalid text must raise InvalidInput, NOT silently return None."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field._edit.setText("not-a-date")
    with pytest.raises(DateField.InvalidInput):
        field.validated_value()


def test_validated_value_invalid_sets_error_label(qapp: QApplication) -> None:
    """validated_value() must mark the field with an error so the user sees it."""
    from taxops.ui.widgets.date_field import DateField

    field = DateField(required=False)
    field._edit.setText("2026-99-99")
    try:
        field.validated_value()
    except DateField.InvalidInput:
        pass
    assert not field._error_label.isHidden()


def test_new_client_dialog_invalid_lease_does_not_save(qapp: QApplication, container) -> None:
    """Invalid lease date must block save -- no DB row written."""
    from taxops.ui.dialogs.new_client_dialog import NewClientDialog

    dlg = NewClientDialog(container.clients)
    dlg._client_code._edit.setText("INVAL01") if hasattr(dlg._client_code, "_edit") else dlg._client_code.setText("INVAL01")
    dlg._client_name._edit.setText("無效日期客戶") if hasattr(dlg._client_name, "_edit") else dlg._client_name.setText("無效日期客戶")
    dlg._lease_start._edit.setText("not-a-date")

    before = len(container.clients.list_clients())
    dlg.on_save()
    after = len(container.clients.list_clients())
    assert after == before  # no row written
    assert dlg._save_btn.isEnabled()  # button re-enabled after rejection


def test_new_engagement_dialog_invalid_due_date_does_not_save(qapp: QApplication, container) -> None:
    """Invalid due_date must block engagement creation."""
    from taxops.ui.dialogs.new_engagement_dialog import NewEngagementDialog
    from taxops.services.clients import CreateClientInput

    client = container.clients.create_client(
        CreateClientInput(client_code="INVENG01", client_name="無效日期案件")
    )
    dlg = NewEngagementDialog(container.engagements, client_id=client.id)
    dlg._name.setText("測試案件")
    dlg._period.setText("2026")
    dlg._due_date._edit.setText("bad-date")

    before = len(container.engagements.list_all())
    dlg.on_save()
    after = len(container.engagements.list_all())
    assert after == before
    assert dlg._save_btn.isEnabled()


def test_new_task_dialog_invalid_due_date_does_not_save(qapp: QApplication, container) -> None:
    """Invalid due_date must block task creation."""
    from taxops.ui.dialogs.new_task_dialog import NewTaskDialog

    dlg = NewTaskDialog(container.tasks)
    dlg._title.setText("測試待辦")
    dlg._due_date._edit.setText("bad-date")

    before = len(container.tasks.list_all())
    dlg.on_save()
    after = len(container.tasks.list_all())
    assert after == before
    assert dlg._save_btn.isEnabled()


# ---------------------------------------------------------------------------
# 13. Version consistency
# ---------------------------------------------------------------------------

def test_package_version_matches_pyproject() -> None:
    """__version__ in taxops/__init__.py must match pyproject.toml version."""
    import importlib.metadata
    import taxops

    try:
        dist_version = importlib.metadata.version("taxops-control-desk")
        assert taxops.__version__ == dist_version
    except importlib.metadata.PackageNotFoundError:
        # Package not installed via pip; verify pyproject.toml manually
        import pathlib
        import re
        toml = (pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
        assert m is not None, "Could not find version in pyproject.toml"
        assert taxops.__version__ == m.group(1), (
            f"__version__ {taxops.__version__!r} != pyproject.toml {m.group(1)!r}"
        )
