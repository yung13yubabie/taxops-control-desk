"""Normalize industry slots carried by an official registry result."""

from __future__ import annotations

from collections.abc import Mapping

from ..client_industries import IndustryInput


_SLOTS = ("primary", "1", "2", "3")


def industries_from_registry(
    registry_row: Mapping[str, object],
) -> tuple[IndustryInput, ...]:
    """Return ordered, code-deduplicated complete industry pairs."""
    industries: list[IndustryInput] = []
    seen_codes: set[str] = set()
    for slot in _SLOTS:
        code = str(registry_row.get(f"industry_code_{slot}") or "").strip().upper()
        name = str(registry_row.get(f"industry_name_{slot}") or "").strip()
        if not code or not name or code in seen_codes:
            continue
        seen_codes.add(code)
        industries.append(IndustryInput(code, name, is_primary=slot == "primary"))
    return tuple(industries)


def industry_display_lines(registry_row: Mapping[str, object]) -> list[str]:
    return [
        f"{item.industry_code} {item.industry_name}"
        for item in industries_from_registry(registry_row)
    ]


def primary_industry_display(registry_row: Mapping[str, object]) -> str | None:
    """Return only a complete source-declared primary pair; never infer one."""
    code = str(registry_row.get("industry_code_primary") or "").strip().upper()
    name = str(registry_row.get("industry_name_primary") or "").strip()
    if not code or not name:
        return None
    return f"{code} {name}"
