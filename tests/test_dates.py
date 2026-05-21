"""Tests for taxops.core.dates shared date utilities."""
from __future__ import annotations

import datetime

import pytest

from taxops.core.dates import date_range_is_valid, parse_optional_iso_date


class TestParseOptionalIsoDate:
    def test_none_returns_none(self) -> None:
        assert parse_optional_iso_date(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_optional_iso_date("") is None

    def test_valid_date_returns_date(self) -> None:
        assert parse_optional_iso_date("2026-05-30") == datetime.date(2026, 5, 30)

    def test_invalid_month_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_iso_date("2026-99-01")

    def test_invalid_day_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_iso_date("2026-02-31")

    def test_non_date_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_iso_date("abc")

    def test_partial_date_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_optional_iso_date("2026-12")

    def test_whitespace_only_returns_none(self) -> None:
        assert parse_optional_iso_date("   ") is None


class TestDateRangeIsValid:
    def test_both_none_is_valid(self) -> None:
        assert date_range_is_valid(None, None)

    def test_start_none_is_valid(self) -> None:
        assert date_range_is_valid(None, datetime.date(2026, 12, 31))

    def test_end_none_is_valid(self) -> None:
        assert date_range_is_valid(datetime.date(2026, 1, 1), None)

    def test_equal_dates_is_valid(self) -> None:
        d = datetime.date(2026, 6, 1)
        assert date_range_is_valid(d, d)

    def test_start_before_end_is_valid(self) -> None:
        assert date_range_is_valid(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))

    def test_start_after_end_is_invalid(self) -> None:
        assert not date_range_is_valid(datetime.date(2026, 12, 31), datetime.date(2026, 1, 1))
