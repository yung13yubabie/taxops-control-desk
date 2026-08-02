from __future__ import annotations

import json

import pytest

from taxops.services.client_industries import (
    ClientIndustryValidationError,
    IndustryInput,
)
from taxops.services.clients import CreateClientInput


def _client(container, code: str = "I001"):
    return container.clients.create_client(
        CreateClientInput(client_code=code, client_name="產業測試客戶")
    )


def test_replace_industries_preserves_order_and_promotes_first(container):
    client = _client(container)

    rows = container.client_industries.replace_from_registry(
        client.id,
        [
            IndustryInput(" 472927 ", "豆類製品零售"),
            IndustryInput("471913", "雜貨店"),
        ],
        source=" MOF-BGMOPEN1 ",
        source_version="20260716",
    )

    assert [row.industry_code for row in rows] == ["472927", "471913"]
    assert [row.sort_order for row in rows] == [0, 1]
    assert [row.is_primary for row in rows] == [True, False]
    assert rows[0].source == "MOF-BGMOPEN1"
    assert container.client_industries.list_for_client(client.id) == rows


def test_plan_tuple_input_and_code_alias(container):
    client = _client(container)
    rows = container.client_industries.replace_from_registry(
        client.id,
        [("7409", "其他專門設計服務業", True), ("7310", "廣告業", False)],
        source="mof_cache",
        source_version="2026-06",
    )
    assert [(row.code, row.is_primary) for row in rows] == [
        ("7409", True),
        ("7310", False),
    ]


def test_replace_is_atomic_and_empty_list_explicitly_clears(container):
    client = _client(container)
    container.client_industries.replace_from_registry(
        client.id,
        [IndustryInput("A1", "原產業", is_primary=True)],
        source="registry",
        source_version=None,
    )

    cleared = container.client_industries.replace_from_registry(
        client.id, [], source="registry", source_version="v2"
    )

    assert cleared == []
    assert container.client_industries.list_for_client(client.id) == []
    audit = container.conn.execute(
        "SELECT action, detail_json FROM audit_logs WHERE target_id = ? ORDER BY id DESC",
        (str(client.id),),
    ).fetchone()
    assert audit["action"] == "client.industries.replace"
    assert json.loads(audit["detail_json"])["source_version"] == "v2"


def test_missing_source_version_is_audited_as_empty_string(container):
    client = _client(container)
    container.client_industries.replace_from_registry(
        client.id,
        [IndustryInput("A", "產業", True)],
        source="registry",
        source_version=None,
    )
    audit = container.conn.execute(
        "SELECT detail_json FROM audit_logs WHERE action = 'client.industries.replace'"
        " AND target_id = ? ORDER BY id DESC",
        (str(client.id),),
    ).fetchone()
    assert json.loads(audit["detail_json"])["source_version"] == ""


@pytest.mark.parametrize(
    ("industries", "source", "code"),
    [
        ([IndustryInput("", "名稱")], "registry", "client_industry.code.required"),
        ([IndustryInput("A", "")], "registry", "client_industry.name.required"),
        (
            [IndustryInput("A", "甲"), IndustryInput(" a ", "乙")],
            "registry",
            "client_industry.code.duplicate",
        ),
        (
            [IndustryInput("A", "甲", True), IndustryInput("B", "乙", True)],
            "registry",
            "client_industry.primary.invalid",
        ),
        ([IndustryInput("X" * 21, "名稱")], "registry", "client_industry.code.too_long"),
        ([IndustryInput("A", "名" * 201)], "registry", "client_industry.name.too_long"),
        ([IndustryInput("A", "名稱")], "S" * 101, "client_industry.source.too_long"),
    ],
)
def test_industry_validation_codes(container, industries, source, code):
    client = _client(container)
    with pytest.raises(ClientIndustryValidationError) as exc:
        container.client_industries.replace_from_registry(
            client.id, industries, source=source, source_version=None
        )
    assert exc.value.code == code


def test_invalid_or_deleted_client_is_rejected(container):
    with pytest.raises(ClientIndustryValidationError) as missing:
        container.client_industries.replace_from_registry(
            99999, [], source="registry", source_version=None
        )
    assert missing.value.code == "client_industry.client_not_found"

    client = _client(container)
    container.clients.delete_client(client.id)
    with pytest.raises(ClientIndustryValidationError) as deleted:
        container.client_industries.replace_from_registry(
            client.id,
            [IndustryInput("A", "甲")],
            source="registry",
            source_version=None,
        )
    assert deleted.value.code == "client_industry.client_not_found"


def test_audit_failure_restores_previous_industry_list(container, monkeypatch):
    client = _client(container)
    original = container.client_industries.replace_from_registry(
        client.id,
        [IndustryInput("OLD", "舊產業", True)],
        source="registry",
        source_version="v1",
    )
    monkeypatch.setattr(
        container.client_industries._audit,
        "record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        container.client_industries.replace_from_registry(
            client.id,
            [IndustryInput("NEW", "新產業", True)],
            source="registry",
            source_version="v2",
        )

    assert container.client_industries.list_for_client(client.id) == original
