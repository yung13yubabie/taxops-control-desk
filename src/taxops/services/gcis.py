"""Minimal official GCIS online lookup by Taiwan unified business number.

This is deliberately a per-tax-id fallback, not a bulk scraper.  GCIS is kept
separate from the MOF BGMOPEN1 tax cache because the sources have different
coverage and semantics.  Some GCIS endpoints are IP-allowlisted by the agency;
that condition is surfaced to the user instead of being misreported as
"not found".
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..security.domains import is_allowed_official_url


class GCISQueryError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_BASE = "https://data.gcis.nat.gov.tw/od/data/api"
_TYPE_ENDPOINT = "673F0FC0-B3A7-429F-9041-E9866836B66D"
_DETAIL_ENDPOINTS: dict[str, tuple[str, str]] = {
    "公司": ("5F64D864-61CB-4D0D-8AD9-492047CC1EA6", "Business_Accounting_NO"),
    "商業": ("426D5542-5F05-43EB-83F9-F1300F14E1F1", "President_No"),
    "分公司": (
        "DC9AC6C1-38CC-479A-A492-088BD8C3328E",
        "Branch_Office_Business_Accounting_NO",
    ),
}
_MAX_RESPONSE_BYTES = 1_000_000


def _url(endpoint: str, filter_value: str) -> str:
    query = urllib.parse.urlencode(
        {
            "$format": "json",
            "$filter": filter_value,
            "$skip": "0",
            "$top": "50",
        }
    )
    return f"{_BASE}/{endpoint}?{query}"


def _fetch(endpoint: str, filter_value: str, *, timeout: int) -> list[dict[str, Any]]:
    url = _url(endpoint, filter_value)
    if not is_allowed_official_url(url):
        raise GCISQueryError("gcis.response.invalid")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TaxOps-ControlDesk/0.29 GCIS-official-lookup"},
    )
    try:
        # The requested and redirected URLs are both restricted to HTTPS hosts
        # in the official-domain allowlist.
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            final_url = getattr(response, "geturl", lambda: url)()
            if not isinstance(final_url, str) or not is_allowed_official_url(final_url):
                raise GCISQueryError("gcis.response.invalid")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except GCISQueryError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GCISQueryError("gcis.network_error") from exc

    if len(raw) > _MAX_RESPONSE_BYTES:
        raise GCISQueryError("gcis.response.too_large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GCISQueryError("gcis.response.invalid") from exc
    if isinstance(payload, str):
        if "非授權介接之IP" in payload:
            raise GCISQueryError("gcis.unauthorized_ip")
        raise GCISQueryError("gcis.response.invalid")
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
        raise GCISQueryError("gcis.response.invalid")
    values = payload["value"]
    if not all(isinstance(item, dict) for item in values):
        raise GCISQueryError("gcis.response.invalid")
    return values


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def query_gcis_by_tax_id(tax_id: str, *, timeout: int = 20) -> dict[str, str] | None:
    cleaned = tax_id.strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        raise GCISQueryError("gcis.tax_id.invalid")

    type_rows = _fetch(_TYPE_ENDPOINT, f"No eq {cleaned}", timeout=timeout)
    entity_type = next(
        (
            str(row.get("TYPE"))
            for row in type_rows
            if str(row.get("exist", "")).upper() == "Y"
            and str(row.get("TYPE")) in _DETAIL_ENDPOINTS
        ),
        None,
    )
    if entity_type is None:
        return None

    endpoint, filter_name = _DETAIL_ENDPOINTS[entity_type]
    detail_rows = _fetch(endpoint, f"{filter_name} eq {cleaned}", timeout=timeout)
    if not detail_rows:
        return None
    row = detail_rows[0]

    if entity_type == "公司":
        name = _first_text(row, "Company_Name")
        address = _first_text(row, "Company_Location")
        organization = "公司"
        registered_date = _first_text(row, "Company_Setup_Date")
        status = _first_text(row, "Company_Status_Desc")
    elif entity_type == "商業":
        name = _first_text(row, "Business_Name")
        address = _first_text(row, "Business_Address")
        subtype = _first_text(row, "Business_Organization_Type_Desc")
        organization = f"商業（{subtype}）" if subtype else "商業"
        registered_date = _first_text(row, "Business_Setup_Approve_Date")
        status = _first_text(row, "Business_Current_Status_Desc")
    else:
        name = _first_text(row, "Branch_Office_Name", "Company_Name")
        address = _first_text(row, "Branch_Office_Location", "Company_Location")
        organization = "分公司"
        registered_date = _first_text(row, "Branch_Office_Setup_Date", "Setup_Date")
        status = _first_text(row, "Status_Type_Desc", "Company_Status_Desc")

    if not name:
        raise GCISQueryError("gcis.response.invalid")
    return {
        "tax_id": cleaned,
        "business_name": name,
        "business_address": address,
        "organization_type": organization,
        "registered_date_roc": registered_date,
        "business_status": status,
        "source": "GCIS 官方線上查詢",
    }
