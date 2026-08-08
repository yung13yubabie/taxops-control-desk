"""Stage 13 — late-fee trial page.

Each test states one condition from the audit row for
`pages/late_fee_page.py`: strategy "Input → result → collapsed segments",
acceptance "calculation regression + geometry", against the four recorded
problems — date popup occludes content, inputs crammed at the top, an empty
rate-segment table dominating the screen, and the result not prominent.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QRadioButton

import taxops.ui.pages.late_fee_page as late_fee_page_module
from taxops.services.late_fee import (
    build_penalty_schedule,
    calculate_overdue_days,
    calculate_penalty_percent,
    last_payment_date_for_period,
)
from taxops.ui import tokens
from taxops.ui.pages.late_fee_page import RATE_COLUMN, SCHEDULE_HEADERS, LateFeePage
from taxops.ui.style import APP_STYLESHEET
from taxops.ui.widgets.buttons import button_role
from taxops.ui.widgets.page_shell import ActionBar, PageHeader


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLESHEET)
    return app


def _select_period(page: LateFeePage, code: str) -> None:
    page._period_combo.setCurrentIndex(page._period_combo.findData(code))


def _band_of(page: LateFeePage, widget) -> int:
    """Index of the page-body row that contains `widget`."""
    body_layout = page._scroll_body.layout()
    for i in range(body_layout.count()):
        item = body_layout.itemAt(i)
        child = item.widget()
        if child is not None:
            if child is widget or child.isAncestorOf(widget):
                return i
            continue
        child_layout = item.layout()
        if child_layout is not None and child_layout.indexOf(widget) >= 0:
            return i
    raise AssertionError(f"{widget} is not inside the page body layout")


def _seed_request(container) -> int:
    conn = container.conn
    conn.execute(
        """
        INSERT INTO clients (client_code, client_name, created_at, updated_at)
        VALUES ('S13', 'Stage 13 Client',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """
    )
    client_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO engagements
            (client_id, engagement_name, tax_type, period_name, status,
             created_at, updated_at)
        VALUES (?, 'Stage 13 Engagement', 'vat', '2026Q1', 'draft',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """,
        (client_id,),
    )
    engagement_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO document_requests
            (engagement_id, period_name, tax_type, status, created_at, updated_at)
        VALUES (?, '2026Q1', 'vat', 'not_requested',
                '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """,
        (engagement_id,),
    )
    request_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return request_id


# ── Strategy: input → result → collapsed segments ───────────────────


def test_body_order_is_input_then_result_then_segments(qapp, container) -> None:
    page = LateFeePage(container)

    source = _band_of(page, page._source_case_radio)
    inputs = _band_of(page, page._year_spin)
    action = _band_of(page, page._calc_btn)
    result = _band_of(page, page._result_penalty_value)
    segments = _band_of(page, page._schedule_table)
    history = _band_of(page, page._table)

    assert source < inputs < action < result < segments < history


def test_inputs_read_top_down_in_need_order(qapp, container) -> None:
    """年份/期別 share a row; deadline, real payment date and amount stack."""
    page = LateFeePage(container)
    layout = page._form_layout

    def cell(widget) -> tuple[int, int]:
        return layout.getItemPosition(layout.indexOf(widget))[:2]

    year_row, year_col = cell(page._year_spin)
    period_row, period_col = cell(page._period_combo)
    deadline_row, deadline_col = cell(page._last_payment_date)
    actual_row, actual_col = cell(page._actual_payment_date)

    assert (year_row, year_col) == (0, 1)
    assert (period_row, period_col) == (0, 3)
    assert deadline_col == actual_col == 1
    assert year_row < deadline_row < actual_row


def test_data_source_is_an_explicit_radio_pair(qapp, container) -> None:
    page = LateFeePage(container)

    assert isinstance(page._source_case_radio, QRadioButton)
    assert isinstance(page._source_manual_radio, QRadioButton)
    assert page._source_case_radio.text() == "從案件帶入"
    assert page._source_manual_radio.text() == "手動輸入"
    assert page._source_case_radio.isChecked()
    assert not page._source_manual_radio.isChecked()
    assert page._source_group.exclusive()
    # `_manual_check` is the surviving name for the manual choice.
    assert page._manual_check is page._source_manual_radio


def test_not_stored_caveat_sits_beside_the_source_control(qapp, container) -> None:
    page = LateFeePage(container)

    assert "不會儲存" in page._source_note.text()
    assert page._source_note.parentWidget() is page._source_case_radio.parentWidget()
    assert page._source_note.objectName() == "HintText"


def test_case_selectors_appear_only_in_case_mode(qapp, container) -> None:
    page = LateFeePage(container)

    assert not page._filter_widget.isHidden()
    assert not page._history_block.isHidden()

    page._source_manual_radio.setChecked(True)
    assert page._filter_widget.isHidden()
    assert page._history_block.isHidden()

    page._source_case_radio.setChecked(True)
    assert not page._filter_widget.isHidden()
    assert not page._history_block.isHidden()


def test_switching_to_manual_preserves_what_the_user_typed(qapp, container) -> None:
    """Insufficient case data must not cost the user their typing."""
    page = LateFeePage(container)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._base_spin.setValue(48_500)

    page._source_manual_radio.setChecked(True)

    assert page._last_payment_date.value() == "2026-03-15"
    assert page._actual_payment_date.value() == "2026-03-20"
    assert page._base_spin.value() == 48_500

    page._source_case_radio.setChecked(True)

    assert page._last_payment_date.value() == "2026-03-15"
    assert page._actual_payment_date.value() == "2026-03-20"
    assert page._base_spin.value() == 48_500


# ── Result prominence ───────────────────────────────────────────────


def test_result_is_a_labelled_card_not_a_sentence(qapp, container) -> None:
    page = LateFeePage(container)
    page._source_manual_radio.setChecked(True)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._base_spin.setValue(206_000)

    page._calc_btn.click()

    assert page._result_days_value.text() == "5 天"
    assert page._result_rate_value.text() == "1%"
    assert page._result_penalty_value.text() == "NT$ 2,060"
    assert page._result_total_value.text() == "NT$ 208,060"
    assert page._result_label.text() == "手動試算結果未儲存。"


def test_the_two_amounts_are_the_largest_type_in_the_result(qapp, container) -> None:
    page = LateFeePage(container)

    emphasised = page._result_penalty_value.font().pixelSize()
    plain = page._result_days_value.font().pixelSize()

    assert plain >= tokens.FONT_BODY  # never below the type floor
    assert emphasised > plain
    assert page._result_penalty_value.font().bold()
    assert page._result_total_value.font().bold()


def test_amounts_are_right_aligned_with_thousands_separators(qapp, container) -> None:
    page = LateFeePage(container)
    page._base_spin.setValue(218_095)

    # currency unit is a separate label, never part of the editable string
    assert page._base_spin.prefix() == ""
    assert page._base_spin.suffix() == ""
    assert "元" not in page._base_spin.text()
    assert "NT$" not in page._base_spin.text()
    assert page._base_spin.isGroupSeparatorShown()
    assert "218,095" in page._base_spin.text()
    assert page._base_spin.alignment() & Qt.AlignmentFlag.AlignRight
    assert page._amount_unit_label.text() == "NT$"

    for value in (
        page._result_days_value,
        page._result_rate_value,
        page._result_penalty_value,
        page._result_total_value,
    ):
        assert value.alignment() & Qt.AlignmentFlag.AlignRight


def test_result_shows_an_em_dash_before_any_calculation(qapp, container) -> None:
    page = LateFeePage(container)

    for value in (
        page._result_days_value,
        page._result_rate_value,
        page._result_penalty_value,
        page._result_total_value,
    ):
        assert value.text() == "—"


def test_changing_an_input_retires_the_displayed_result(qapp, container) -> None:
    page = LateFeePage(container)
    page._source_manual_radio.setChecked(True)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._base_spin.setValue(10_000)
    page._calc_btn.click()
    assert page._result_penalty_value.text() == "NT$ 100"

    page._base_spin.setValue(20_000)

    assert page._result_penalty_value.text() == "—"
    assert page._result_total_value.text() == "—"


# ── Collapsed segments, no empty grid ───────────────────────────────


def test_segment_breakdown_is_collapsed_and_absent_until_it_has_content(
    qapp, container
) -> None:
    page = LateFeePage(container)

    assert page._schedule_table.rowCount() == 0
    assert page._schedule_toggle.isHidden()
    assert page._schedule_body.isHidden()

    page._year_spin.setValue(2026)
    _select_period(page, "1-2")

    assert page._schedule_table.rowCount() == 11
    assert not page._schedule_toggle.isHidden()
    assert not page._schedule_toggle.isChecked()
    assert page._schedule_body.isHidden()
    assert page._schedule_toggle.text() == "計算區間明細 ▸"
    assert button_role(page._schedule_toggle) == tokens.ROLE_QUIET

    page._schedule_toggle.setChecked(True)
    assert not page._schedule_body.isHidden()
    assert page._schedule_toggle.text() == "計算區間明細 ▾"

    page._schedule_toggle.setChecked(False)
    assert page._schedule_body.isHidden()


def test_segment_columns_show_start_end_days_rate_and_amount(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")  # 法定期限 = 2026-03-15
    page._base_spin.setValue(10_000)

    headers = [
        page._schedule_table.horizontalHeaderItem(c).text()
        for c in range(page._schedule_table.columnCount())
    ]
    assert headers == list(SCHEDULE_HEADERS)
    assert headers[RATE_COLUMN] == "適用滯納金率"

    # band index 1 is the 1% band, overdue days 4..6
    assert page._schedule_table.item(1, 0).text() == "2026-03-19"
    assert page._schedule_table.item(1, 1).text() == "2026-03-21"
    assert page._schedule_table.item(1, 2).text() == "第 4–6 日"
    assert page._schedule_table.item(1, RATE_COLUMN).text() == "1%"
    assert page._schedule_table.item(1, 4).text() == "NT$ 100"

    last = page._schedule_table.rowCount() - 1
    assert page._schedule_table.item(last, 1).text() == "（之後）"
    assert page._schedule_table.item(last, 2).text() == "第 31 日起"


def test_segment_amount_is_an_em_dash_without_a_tax_amount(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")

    assert page._base_spin.value() == 0
    assert page._schedule_table.item(1, 4).text() == "—"


def test_history_shows_an_empty_state_instead_of_an_empty_grid(qapp, container) -> None:
    page = LateFeePage(container)

    assert page._table.rowCount() == 0
    assert page._table.isHidden()
    assert not page._history_empty.isHidden()
    assert page._history_empty.action_button is None  # no fake next step

    request_id = _seed_request(container)
    page._req_combo.addItem("batch", request_id)
    page._req_combo.setCurrentIndex(page._req_combo.count() - 1)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._base_spin.setValue(10_000)
    page._calc_btn.click()

    assert page._table.rowCount() == 1
    assert not page._table.isHidden()
    assert page._history_empty.isHidden()


# ── Action rank ─────────────────────────────────────────────────────


def test_only_the_calculation_is_primary(qapp, container) -> None:
    page = LateFeePage(container)

    assert isinstance(page._header, PageHeader)
    assert isinstance(page._action_bar, ActionBar)
    assert page._header.title_label.text() == "滯納金試算"

    assert button_role(page._calc_btn) == tokens.ROLE_PRIMARY
    assert button_role(page._reset_btn) == tokens.ROLE_SECONDARY

    primaries = [
        btn
        for btn in page.findChildren(type(page._calc_btn))
        if button_role(btn) == tokens.ROLE_PRIMARY
    ]
    assert primaries == [page._calc_btn]
    assert page._action_bar.visible_action_count() <= 5


def test_page_owns_no_inline_stylesheets(qapp, container) -> None:
    """G12: the role and token system, not per-widget CSS."""
    import inspect

    source = inspect.getsource(late_fee_page_module)
    assert "setStyleSheet" not in source


def test_reset_clears_the_trial_but_not_the_case_selection(qapp, container) -> None:
    page = LateFeePage(container)
    page._eng_combo.addItem("案件 A", 4242)
    page._eng_combo.setCurrentIndex(page._eng_combo.count() - 1)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._base_spin.setValue(10_000)

    page._reset_btn.click()

    assert page._actual_payment_date.value() is None
    assert page._base_spin.value() == 0
    assert page._result_penalty_value.text() == "—"
    assert page._eng_combo.currentData() == 4242


# ── Geometry ────────────────────────────────────────────────────────


def _overflows(child, page) -> bool:
    top_left = child.mapTo(page, child.rect().topLeft())
    bottom_right = child.mapTo(page, child.rect().bottomRight())
    return (
        top_left.x() < -2
        or top_left.y() < -2
        or bottom_right.x() > page.width() + 2
        or bottom_right.y() > page.height() + 2
    )


@pytest.mark.parametrize("size", [(853, 614), (1366, 768)])
def test_inputs_action_and_result_fit_without_scrolling(qapp, container, size) -> None:
    page = LateFeePage(container)
    page.resize(*size)
    page.show()
    QApplication.processEvents()

    for widget in (
        page._source_case_radio,
        page._year_spin,
        page._last_payment_date,
        page._actual_payment_date,
        page._base_spin,
        page._calc_btn,
        page._result_total_value,
    ):
        assert not _overflows(widget, page), widget

    assert (
        page._scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert page._scroll_body.width() <= page._scroll.viewport().width()


def test_date_popup_cannot_cover_the_primary_action(qapp, container) -> None:
    """The popup drops below its field; the primary must not be in that column."""
    page = LateFeePage(container)
    page.resize(1366, 768)
    page.show()
    QApplication.processEvents()

    button_left = page._calc_btn.mapTo(page, page._calc_btn.rect().topLeft()).x()
    for field in (page._last_payment_date, page._actual_payment_date):
        field_right = field.mapTo(page, field.rect().bottomRight()).x()
        assert field_right < button_left, field

    # and the action no longer shares the grid that holds the date fields
    assert page._form_layout.indexOf(page._calc_btn) == -1


def test_one_scroll_region_only(qapp, container) -> None:
    """G10: the page scrolls; the tables inside it do not."""
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")
    page._schedule_toggle.setChecked(True)
    page.resize(853, 614)
    page.show()
    QApplication.processEvents()

    for table in (page._schedule_table, page._table):
        assert (
            table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # sized to its content, so it never needs a scrollbar of its own
        assert table.verticalScrollBar().maximum() == 0


# ── Calculation regression ──────────────────────────────────────────


@pytest.mark.parametrize(
    "actual,expected_days,expected_rate",
    [
        ("2026-03-15", 0, 0.0),
        ("2026-03-18", 3, 0.0),
        ("2026-03-19", 4, 1.0),
        ("2026-03-24", 9, 2.0),
        ("2026-04-30", 46, 10.0),
    ],
)
def test_displayed_numbers_equal_the_statutory_functions(
    qapp, container, actual, expected_days, expected_rate
) -> None:
    """The redesign moved the numbers; it did not compute them differently."""
    page = LateFeePage(container)
    page._source_manual_radio.setChecked(True)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")
    deadline = last_payment_date_for_period(2026, "1-2")
    assert page._last_payment_date.value() == deadline

    page._actual_payment_date.set_value(actual)
    page._base_spin.setValue(100_000)
    page._calc_btn.click()

    days = calculate_overdue_days(deadline, actual)
    rate = calculate_penalty_percent(days)
    assert (days, rate) == (expected_days, expected_rate)

    penalty = round(100_000 * rate / 100, 2)
    assert page._result_days_value.text() == f"{days} 天"
    assert page._result_rate_value.text() == f"{rate:g}%"
    assert page._result_penalty_value.text() == f"NT$ {penalty:,.0f}"
    assert page._result_total_value.text() == f"NT$ {100_000 + penalty:,.0f}"


def test_segment_rows_mirror_build_penalty_schedule(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")

    bands = build_penalty_schedule(last_payment_date_for_period(2026, "1-2"))
    assert page._schedule_table.rowCount() == len(bands)
    for row, band in enumerate(bands):
        assert page._schedule_table.item(row, 0).text() == band["start_date"]
        assert (
            page._schedule_table.item(row, RATE_COLUMN).text()
            == f"{float(band['percent']):g}%"
        )


def test_hit_band_is_marked_and_named(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")
    page._actual_payment_date.set_value("2026-03-20")  # 5 days -> 1%
    # set_value is silent by contract; typing or picking a date emits value_changed.
    page._refresh_schedule_display()

    marked = [
        page._schedule_table.item(r, RATE_COLUMN).text()
        for r in range(page._schedule_table.rowCount())
        if page._schedule_table.item(r, RATE_COLUMN).background().color().name()
        == tokens.STATUS_PENDING_BG.lower()
    ]
    assert marked == ["1%"]


def test_over_thirty_days_still_warns_in_words(qapp, container) -> None:
    page = LateFeePage(container)
    page._year_spin.setValue(2026)
    _select_period(page, "1-2")
    page._actual_payment_date.set_value("2026-05-01")
    page._refresh_schedule_display()

    assert "人工確認" in page._schedule_note.text()
    assert page._schedule_note.objectName() == "HintText"


# ── loud: failures are visible ──────────────────────────────────────


def test_invalid_date_text_calculates_nothing_and_leaves_the_field_to_report(
    qapp, container, monkeypatch
) -> None:
    """`validated_value` raising is the field's own error report, not a modal."""
    from taxops.ui.widgets.date_field import DateField

    page = LateFeePage(container)
    page._source_manual_radio.setChecked(True)
    page._last_payment_date.set_value("2026-03-15")
    page._base_spin.setValue(10_000)
    warnings: list[str] = []
    criticals: list[str] = []
    monkeypatch.setattr(
        late_fee_page_module.QMessageBox,
        "warning",
        lambda _parent, _title, body: warnings.append(body),
    )
    monkeypatch.setattr(
        late_fee_page_module.QMessageBox,
        "critical",
        lambda _parent, _title, body: criticals.append(body),
    )
    monkeypatch.setattr(
        page._actual_payment_date,
        "validated_value",
        lambda: (_ for _ in ()).throw(DateField.InvalidInput("2026-13-99")),
    )

    page._calc_btn.click()

    assert page._result_penalty_value.text() == "—"
    assert warnings == []
    assert criticals == []
    assert page._calc_btn.isEnabled()  # the button comes back either way


def test_missing_dates_and_batch_name_the_next_step(
    qapp, container, monkeypatch
) -> None:
    page = LateFeePage(container)
    warnings: list[str] = []
    monkeypatch.setattr(
        late_fee_page_module.QMessageBox,
        "warning",
        lambda _parent, _title, body: warnings.append(body),
    )

    page._calc_btn.click()
    assert warnings[-1] == "請輸入法定期限與實際繳款日"

    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._calc_btn.click()
    assert warnings[-1] == "請先選擇索件批次，或切換為手動輸入"


def test_history_load_failure_is_logged_and_shown(qapp, container, monkeypatch) -> None:
    request_id = _seed_request(container)
    page = LateFeePage(container)
    page._req_combo.addItem("batch", request_id)
    monkeypatch.setattr(
        container.late_fee,
        "list_by_request",
        lambda _rid: (_ for _ in ()).throw(RuntimeError("history locked")),
    )

    page._req_combo.setCurrentIndex(page._req_combo.count() - 1)

    assert page._history == []
    assert page._table.rowCount() == 0
    assert page._result_label.text() == "試算記錄載入失敗，請重新整理頁面"
    assert page._result_label.objectName() == "ErrorText"


def test_manual_review_tax_type_refuses_to_show_a_number(qapp, container) -> None:
    """勞健保 needs a human; the card must not imply a computed penalty."""
    request_id = _seed_request(container)
    container.conn.execute(
        "UPDATE document_requests SET tax_type = 'labor_health' WHERE id = ?",
        (request_id,),
    )
    container.conn.commit()

    page = LateFeePage(container)
    page._req_combo.addItem("batch", request_id)
    page._req_combo.setCurrentIndex(page._req_combo.count() - 1)
    page._last_payment_date.set_value("2026-03-15")
    page._actual_payment_date.set_value("2026-03-20")
    page._base_spin.setValue(10_000)

    page._calc_btn.click()

    assert page._result_rate_value.text() == "需人工確認"
    assert page._result_penalty_value.text() == "需人工確認"
    assert page._result_total_value.text() == "需人工確認"
    assert "人工確認" in page._result_label.text()
