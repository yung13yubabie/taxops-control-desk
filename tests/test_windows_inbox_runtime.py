"""Exact inbox exception contracts; signatures here are synthetic fixtures."""

import copy
import ntpath
from pathlib import Path

import pytest
from build_tools import windows_inbox_runtime as inbox
from build_tools import windows_loaded_modules as modules
from test_loaded_modules import fixture, MEI, EXE, HASH, ROOTS


def row():
    path = ROOTS["system32"] + r"\msvcp110_win.dll"
    return {
        "path": path,
        "loader_path": path,
        "sha256": HASH,
        "bytes": 12,
        "location": "windows_system32",
    }


def signature():
    return {
        "status": "Valid",
        "subject": "CN=Microsoft Windows, O=Microsoft Corporation, C=US",
        "thumbprint": "1234",
        "original_filename": "msvcp110_win.dll",
        "product_name": "Synthetic Windows provider",
        "file_version": "synthetic",
        "process": {
            "returncode": 0,
            "timed_out": False,
            "command": ["synthetic.ps1"],
            "stdout_base64": "e30=",
            "stderr_base64": "",
        },
    }


def test_exact_inbox_runtime_requires_live_signature_and_stable_bytes(monkeypatch):
    observed, calls = row(), []
    identity = {key: observed[key] for key in ("path", "sha256", "bytes")}
    monkeypatch.setattr(
        inbox,
        "file_identity",
        lambda path: calls.append(("hash", path)) or identity.copy(),
    )
    monkeypatch.setattr(
        inbox,
        "microsoft_signature",
        lambda path: calls.append(("sign", path)) or signature(),
    )
    result = inbox.verify_inbox_runtime(observed, roots=ROOTS, protected_names=set())
    assert [kind for kind, path in calls] == ["hash", "sign", "hash"]
    assert all(path == Path(observed["path"]) for kind, path in calls)
    assert result["classification"] == "verified_windows_integrated_runtime"
    assert result["authenticode"]["process"]["stdout_base64"] == "e30="


@pytest.mark.parametrize(
    "fault",
    [
        "msvcp110.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp999_win.dll",
        "external",
        "winsxs",
        "system_subdir",
        "fake_root",
        "loader_alias",
        "payload",
        "normal",
        "delay",
        "forwarder",
        "bad_signature",
        "other_publisher",
        "missing_signature",
        "no_raw",
        "nonzero",
        "timeout",
        "hash",
        "size",
        "changed_during_signature",
        "deleted",
        "path_changed",
        "renamed_signed_dll",
        "missing_original_filename",
        "empty_original_filename",
    ],
)
def test_inbox_exception_is_exact_fail_closed(monkeypatch, fault):
    observed, attestation, protected, roots = (
        row(),
        signature(),
        set(),
        copy.deepcopy(ROOTS),
    )
    identity = {key: observed[key] for key in ("path", "sha256", "bytes")}
    if fault.endswith(".dll"):
        observed["path"] = observed["loader_path"] = ntpath.join(
            ROOTS["system32"], fault
        )
    elif fault in {"external", "winsxs", "system_subdir"}:
        root = {
            "external": r"C:\External",
            "winsxs": ROOTS["winsxs"],
            "system_subdir": ROOTS["system32"] + r"\sub",
        }[fault]
        observed["path"] = observed["loader_path"] = ntpath.join(root, inbox.NAME)
    elif fault == "fake_root":
        roots["system32"] = r"D:\Windows\System32"
    elif fault == "loader_alias":
        observed["loader_path"] = r"C:\Elsewhere\msvcp110_win.dll"
    elif fault in {"payload", "normal", "delay", "forwarder"}:
        protected.add(inbox.NAME)
    elif fault == "bad_signature":
        attestation["status"] = "NotTrusted"
    elif fault == "other_publisher":
        attestation["subject"] = "O=Not Microsoft Corporation"
    elif fault == "missing_signature":
        attestation = {}
    elif fault == "no_raw":
        del attestation["process"]["stdout_base64"]
    elif fault == "nonzero":
        attestation["process"]["returncode"] = 1
    elif fault == "timeout":
        attestation["process"]["timed_out"] = True
    elif fault == "hash":
        identity["sha256"] = "2" * 64
    elif fault == "size":
        identity["bytes"] += 1
    elif fault == "renamed_signed_dll":
        attestation["original_filename"] = "different_signed.dll"
    elif fault == "missing_original_filename":
        del attestation["original_filename"]
    elif fault == "empty_original_filename":
        attestation["original_filename"] = ""
    elif fault == "path_changed":
        identity["path"] = r"C:\Elsewhere\msvcp110_win.dll"
    calls = []

    def file_identity(_path):
        calls.append(1)
        if fault == "deleted":
            raise FileNotFoundError("synthetic removal")
        return (
            {**identity, "bytes": 99}
            if fault == "changed_during_signature" and len(calls) > 1
            else identity
        )

    monkeypatch.setattr(inbox, "file_identity", file_identity)
    monkeypatch.setattr(inbox, "microsoft_signature", lambda path: attestation)
    with pytest.raises((modules.LoadedModuleError, OSError)):
        inbox.verify_inbox_runtime(observed, roots=roots, protected_names=protected)


def test_all_unknown_and_vc_violations_are_collected_without_baseline():
    report, inventory = fixture()
    extras = [
        {
            **row(),
            "path": r"C:\Other\one.dll",
            "loader_path": r"C:\Other\one.dll",
            "location": "external",
        },
        {
            **row(),
            "path": r"C:\Other\two.dll",
            "loader_path": r"C:\Other\two.dll",
            "location": "external",
        },
        row(),
    ]
    report["modules"].extend(extras)
    with pytest.raises(modules.LoadedModuleError) as captured:
        modules.validate_loaded_modules(
            report,
            expected_native=inventory,
            meipass=MEI,
            executable=EXE,
            executable_sha256=HASH,
            os_roots=ROOTS,
            phase="gui_ready",
        )
    assert [item["path"] for item in captured.value.violations] == [
        item["path"] for item in extras
    ]


def test_inbox_classifier_cannot_overrule_payload_name(monkeypatch):
    report, inventory = fixture()
    observed = row()
    report["modules"].append(observed)
    inventory[inbox.NAME] = HASH

    def forbidden(_row):
        pytest.fail("Payload basename must reject before inbox exception")

    with pytest.raises(modules.LoadedModuleError):
        modules.validate_loaded_modules(
            report,
            expected_native=inventory,
            meipass=MEI,
            executable=EXE,
            executable_sha256=HASH,
            os_roots=ROOTS,
            phase="gui_ready",
            inbox_runtime_verifier=forbidden,
        )


def test_exact_inbox_success_is_separate_from_shell_classification():
    report, inventory = fixture()
    observed = row()
    report["modules"].append(observed)
    result = modules.validate_loaded_modules(
        report,
        expected_native=inventory,
        meipass=MEI,
        executable=EXE,
        executable_sha256=HASH,
        os_roots=ROOTS,
        phase="gui_ready",
        inbox_runtime_verifier=lambda actual: {
            "classification": "verified_windows_integrated_runtime",
            **actual,
        },
    )
    assert result["independently_shell_observed_external"] == []
    assert result["verified_windows_integrated_runtime"][0]["path"] == observed["path"]
    assert result["os_location_module_count"] == 2
