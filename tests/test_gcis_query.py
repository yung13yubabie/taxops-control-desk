from __future__ import annotations

import io
import json
import urllib.error

import pytest
from PySide6.QtWidgets import QApplication

from taxops.services.gcis import GCISQueryError, query_gcis_by_tax_id
from taxops.ui.pages.registry_page import _GCISWorker


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Response:
    def __init__(self, payload, *, url="https://data.gcis.nat.gov.tw/result"):
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._url = url
        self.headers = {"Content-Length": str(len(self._body))}
        self._stream = io.BytesIO(self._body)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self._stream.read(size)

    def geturl(self):
        return self._url


def test_company_lookup_uses_type_then_official_company_detail(monkeypatch):
    responses = iter(
        [
            _Response({"value": [{"exist": "Y", "TYPE": "公司"}], "Count": 1}),
            _Response(
                {
                    "value": [
                        {
                            "Business_Accounting_NO": "20828393",
                            "Company_Name": "宏碁股份有限公司",
                            "Company_Location": "臺北市松山區復興北路369號",
                            "Company_Status_Desc": "核准設立",
                            "Company_Setup_Date": "0680718",
                        }
                    ],
                    "Count": 1,
                }
            ),
        ]
    )
    urls: list[str] = []

    def urlopen(request, timeout):
        urls.append(request.full_url)
        assert timeout == 20
        return next(responses)

    monkeypatch.setattr("taxops.services.gcis.urllib.request.urlopen", urlopen)

    result = query_gcis_by_tax_id("20828393")

    assert result == {
        "tax_id": "20828393",
        "business_name": "宏碁股份有限公司",
        "business_address": "臺北市松山區復興北路369號",
        "organization_type": "公司",
        "registered_date_roc": "0680718",
        "business_status": "核准設立",
        "source": "GCIS 官方線上查詢",
    }
    assert "673F0FC0-B3A7-429F-9041-E9866836B66D" in urls[0]
    assert "5F64D864-61CB-4D0D-8AD9-492047CC1EA6" in urls[1]


def test_business_lookup_maps_business_fields(monkeypatch):
    responses = iter(
        [
            _Response({"value": [{"exist": "Y", "TYPE": "商業"}]}),
            _Response(
                {
                    "value": [
                        {
                            "President_No": "15725713",
                            "Business_Name": "鴻燿商品行",
                            "Business_Address": "臺南市安南區公學路2段55號",
                            "Business_Organization_Type_Desc": "獨資",
                            "Business_Current_Status_Desc": "核准設立",
                            "Business_Setup_Approve_Date": "0920430",
                        }
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: next(responses),
    )

    result = query_gcis_by_tax_id("15725713")

    assert result["business_name"] == "鴻燿商品行"
    assert result["organization_type"] == "商業（獨資）"
    assert result["business_address"] == "臺南市安南區公學路2段55號"


def test_gcis_unauthorized_response_is_not_reported_as_not_found(monkeypatch):
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response("非授權介接之IP(203.0.113.1)，請查明後繼續。"),
    )

    with pytest.raises(GCISQueryError) as exc:
        query_gcis_by_tax_id("20828393")

    assert exc.value.code == "gcis.unauthorized_ip"


@pytest.mark.parametrize("tax_id", ["", "123", "abcdefgh", "123456789"])
def test_gcis_rejects_invalid_tax_id_before_network(tax_id, monkeypatch):
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network must not be called"),
    )

    with pytest.raises(GCISQueryError) as exc:
        query_gcis_by_tax_id(tax_id)

    assert exc.value.code == "gcis.tax_id.invalid"


def test_gcis_rejects_redirect_outside_official_allowlist(monkeypatch):
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {"value": []}, url="https://evil.example/redirect"
        ),
    )

    with pytest.raises(GCISQueryError) as exc:
        query_gcis_by_tax_id("20828393")

    assert exc.value.code == "gcis.response.invalid"


def test_gcis_rejects_generated_url_outside_allowlist(monkeypatch):
    monkeypatch.setattr("taxops.services.gcis.is_allowed_official_url", lambda _url: False)
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("network must not be called"),
    )

    with pytest.raises(GCISQueryError) as exc:
        query_gcis_by_tax_id("20828393")

    assert exc.value.code == "gcis.response.invalid"


@pytest.mark.parametrize(
    "error",
    [urllib.error.URLError("offline"), TimeoutError("slow"), OSError("socket")],
)
def test_gcis_maps_network_failures_to_visible_error(monkeypatch, error):
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(GCISQueryError) as exc:
        query_gcis_by_tax_id("20828393")

    assert exc.value.code == "gcis.network_error"


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ("unexpected agency message", "gcis.response.invalid"),
        ({"not_value": []}, "gcis.response.invalid"),
        ({"value": "not-a-list"}, "gcis.response.invalid"),
        ({"value": ["not-an-object"]}, "gcis.response.invalid"),
    ],
)
def test_gcis_rejects_malformed_payload_shapes(monkeypatch, payload, expected_code):
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(payload),
    )

    with pytest.raises(GCISQueryError) as exc:
        query_gcis_by_tax_id("20828393")

    assert exc.value.code == expected_code


def test_gcis_rejects_invalid_utf8_and_oversized_responses(monkeypatch):
    class RawResponse(_Response):
        def __init__(self, body: bytes):
            self._body = body
            self._url = "https://data.gcis.nat.gov.tw/result"
            self._stream = io.BytesIO(body)

    responses = iter([RawResponse(b"\xff"), RawResponse(b"x" * 1_000_001)])
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(GCISQueryError) as invalid:
        query_gcis_by_tax_id("20828393")
    assert invalid.value.code == "gcis.response.invalid"

    with pytest.raises(GCISQueryError) as too_large:
        query_gcis_by_tax_id("20828393")
    assert too_large.value.code == "gcis.response.too_large"


def test_gcis_returns_none_for_unknown_type_or_empty_detail(monkeypatch):
    responses = iter(
        [
            _Response({"value": [{"exist": "N", "TYPE": "公司"}]}),
            _Response({"value": [{"exist": "Y", "TYPE": "公司"}]}),
            _Response({"value": []}),
        ]
    )
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: next(responses),
    )

    assert query_gcis_by_tax_id("20828393") is None
    assert query_gcis_by_tax_id("20828393") is None


def test_branch_lookup_maps_fallback_fields(monkeypatch):
    responses = iter(
        [
            _Response({"value": [{"exist": "Y", "TYPE": "分公司"}]}),
            _Response(
                {
                    "value": [
                        {
                            "Company_Name": "測試分公司",
                            "Company_Location": "臺北市測試路 1 號",
                            "Setup_Date": "1150101",
                            "Company_Status_Desc": "核准設立",
                        }
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: next(responses),
    )

    result = query_gcis_by_tax_id("20828393")

    assert result is not None
    assert result["business_name"] == "測試分公司"
    assert result["organization_type"] == "分公司"
    assert result["registered_date_roc"] == "1150101"


def test_gcis_rejects_detail_without_name(monkeypatch):
    responses = iter(
        [
            _Response({"value": [{"exist": "Y", "TYPE": "公司"}]}),
            _Response({"value": [{"Company_Name": ""}]}),
        ]
    )
    monkeypatch.setattr(
        "taxops.services.gcis.urllib.request.urlopen",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(GCISQueryError) as exc:
        query_gcis_by_tax_id("20828393")

    assert exc.value.code == "gcis.response.invalid"


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize(
    ("result", "error", "expected_success", "expected_error"),
    [({"tax_id": "20828393"}, None, {"tax_id": "20828393"}, None),
     (None, GCISQueryError("gcis.network_error"), None, "gcis.network_error"),
     (None, RuntimeError("secret"), None, "system.unexpected")],
)
def test_gcis_worker_maps_success_known_and_unknown_errors(
    monkeypatch, result, error, expected_success, expected_error
):
    def query(_tax_id):
        if error is not None:
            raise error
        return result

    monkeypatch.setattr("taxops.ui.pages.registry_page.query_gcis_by_tax_id", query)
    worker = _GCISWorker("20828393")
    successes = []
    errors = []
    worker.succeeded.connect(successes.append)
    worker.errored.connect(errors.append)

    worker.run()

    assert successes == ([] if expected_success is None else [expected_success])
    assert errors == ([] if expected_error is None else [expected_error])
