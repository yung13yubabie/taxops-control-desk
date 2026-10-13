"""Guard known UTF-8 test inputs without changing or simulating the host locale."""
import ast
from pathlib import Path

import pytest


# These files read UTF-8 repository sources/reports and write synthetic fixtures.
# Keep the contract scoped: other formats need their own encoding review.
UTF8_TEST_FILES = (
    "test_deep_chinese_ui.py",
    "test_dependency_licenses.py",
    "test_frozen_self_test.py",
    "test_recombine_inputs.py",
)


def _assert_explicit_utf8(source: str) -> None:
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"read_text", "write_text"}
    ]
    assert calls, "Expected text I/O in the reviewed test file"
    missing = [
        node.lineno for node in calls
        if not any(
            keyword.arg == "encoding" and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "utf-8"
            for keyword in node.keywords
        )
    ]
    assert not missing, f"Text I/O needs explicit UTF-8 at lines {missing}"


@pytest.mark.parametrize("name", UTF8_TEST_FILES)
def test_known_utf8_test_inputs_do_not_use_the_host_encoding(name):
    source = Path(__file__).with_name(name).read_text(encoding="utf-8")
    _assert_explicit_utf8(source)


@pytest.mark.parametrize("source", ["path.read_text()", "path.write_text('合成')"])
def test_contract_rejects_missing_encoding(source):
    with pytest.raises(AssertionError, match="explicit UTF-8"):
        _assert_explicit_utf8(source)
