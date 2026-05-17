"""Spreadsheet formula-injection defense (OWASP CSV Injection / Excel Injection).

Any cell value that starts with =, +, -, or @ can be interpreted as a formula
by Excel, LibreOffice Calc, and Google Sheets. Prepend a single quote to force
text interpretation.
"""

from __future__ import annotations

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def safe_spreadsheet_cell(value: str) -> str:
    """Return *value* safe for placement in a spreadsheet cell.

    If the value begins with a formula-trigger character, ignoring leading
    whitespace, prefix it with a single-quote (') so the spreadsheet treats it
    as a text literal.
    """
    if value and value.lstrip()[0:1] in _FORMULA_PREFIXES:
        return "'" + value
    return value
