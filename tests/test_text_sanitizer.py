"""Text sanitizer behaviour at UI boundaries."""

from __future__ import annotations

from taxops.core.text import is_safe_for_ui, sanitize_user_text


def test_sanitize_strips_control_chars_keeps_newline() -> None:
    raw = "客戶\x00名\x07稱\n第二行"
    assert sanitize_user_text(raw) == "客戶名稱\n第二行"


def test_sanitize_truncates_to_max_length() -> None:
    long_text = "甲" * 500
    out = sanitize_user_text(long_text, max_length=100)
    assert len(out) == 100


def test_sanitize_handles_none() -> None:
    assert sanitize_user_text(None) == ""


def test_is_safe_for_ui_flags_html_and_traceback() -> None:
    assert is_safe_for_ui("正常的中文訊息") is True
    assert is_safe_for_ui("<script>alert(1)</script>") is False
    assert is_safe_for_ui("Traceback (most recent call last)") is False
    assert is_safe_for_ui("sqlite3.OperationalError: no such table") is False


def test_is_safe_for_ui_empty() -> None:
    assert is_safe_for_ui("") is True
