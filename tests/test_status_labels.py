"""Status enum → Chinese label mapping."""

from __future__ import annotations

from taxops.i18n.status_labels import (
    STATUS_LABELS,
    UNKNOWN_STATUS_TEXT,
    status_to_label,
)

EXPECTED = {
    "todo": "待處理",
    "doing": "處理中",
    "waiting_client": "等客戶回覆",
    "waiting_internal_review": "等內部覆核",
    "done": "已完成",
    "cancelled": "已取消",
    "needs_manual_review": "需人工確認",
}


def test_known_statuses_map_to_expected_labels() -> None:
    for raw, label in EXPECTED.items():
        assert STATUS_LABELS[raw] == label
        assert status_to_label(raw) == label


def test_unknown_status_returns_generic_message() -> None:
    assert status_to_label("invented_value") == UNKNOWN_STATUS_TEXT
    assert status_to_label(None) == UNKNOWN_STATUS_TEXT
    assert status_to_label("") == UNKNOWN_STATUS_TEXT


def test_no_label_is_a_raw_enum_value() -> None:
    for raw, label in STATUS_LABELS.items():
        assert label != raw
        assert any("一" <= ch <= "鿿" for ch in label)
