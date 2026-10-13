"""Offline contracts for hosted orchestration; never Windows execution evidence."""
from __future__ import annotations

from contextlib import ExitStack
import copy
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from build_tools import hosted_recombine_proof as proof
from build_tools import hosted_windows_bootstrap as bootstrap


class Response(io.BytesIO):
    def __init__(self, data=b"", status=200, headers=None):
        super().__init__(data)
        self.status, self.headers = status, headers or {}


def zip_bytes(entries):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return target.getvalue()


def fixture(change=None):
    source = {"BUILD_RECOMBINE.txt": b"Instructions", "assets/third_party_licenses/RECOMBINE_PERMISSION.txt": b"Permission",
              "src/example.py": b"print('synthetic')", "build_tools/recombine.py": b"# synthetic"}
    material = {name: proof.digest(content) for name, content in source.items()}
    manifest = {"schema": 1, "source_commit": proof.COMMIT, "source_tree": proof.TREE,
                "accepted_exe_sha256": proof.digest(b"synthetic exe"), "files": [
                    {"path": name, "bytes": len(content), "sha256": material[name]} for name, content in source.items()]}
    entries = [("source/" + name, content) for name, content in source.items()]
    if change:
        change(manifest, entries)
    entries += [("source/SOURCE_IDENTITY.json", json.dumps(manifest).encode()),
                ("BUILD_RECOMBINE.txt", b"Instructions"), ("RECOMBINE_PERMISSION.txt", b"Permission")]
    kit = zip_bytes(entries)
    provenance = json.dumps({"status": "passed", "single_file": True, "recombined": False,
                            "source_exe_sha256": proof.digest(b"synthetic exe"),
                            "build_source_commit": proof.COMMIT, "build_source_tree": proof.TREE}).encode()
    outer_entries = [(proof.KIT_NAME, kit), ("windows-onefile/TaxOpsControlDesk.exe", b"synthetic exe"),
                     ("windows-onefile/onefile-provenance.json", provenance)]
    outer = zip_bytes(outer_entries)
    values = {"OUTER_BYTES": len(outer), "OUTER_SHA": proof.digest(outer), "OUTER_FILES": 3,
              "OUTER_EXPANDED": sum(len(v) for _, v in outer_entries), "KIT_SHA": proof.digest(kit),
              "KIT_BYTES": len(kit), "KIT_EXPANDED": sum(len(v) for _, v in entries), "EXE_BYTES": len(b"synthetic exe"),
              "EXE_SHA": proof.digest(b"synthetic exe"), "PROVENANCE_SHA": proof.digest(provenance), "SOURCE_FILES": 4,
              "MATERIAL_SHA": proof.digest(json.dumps(material, sort_keys=True, separators=(",", ":")).encode())}
    return outer, values


def job_environment_context_violations(text):
    # Target the job-env block in this workflow's deliberately fixed indentation.
    # GitHub context availability explicitly excludes runner/env/job/steps here:
    # https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
    allowed = {"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"}
    blocks = re.findall(r"(?m)^    env:\n((?:      [^\n]*\n)*)", text)
    return [context for block in blocks
            for context in re.findall(r"\$\{\{\s*([a-zA-Z_][a-zA-Z_0-9]*)[.\[]", block)
            if context not in allowed]


class HostedProofTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def materialize_fixture(self, change=None, values_change=None):
        content, values = fixture(change)
        if values_change:
            values_change(values)
        path = self.root / "outer.zip"
        path.write_bytes(content)
        with ExitStack() as stack:
            for key, value in values.items():
                stack.enter_context(patch.object(proof, key, value))
            return proof.materialize(path, self.root)

    def test_materializes_exact_source_without_git_or_code_execution(self):
        result = self.materialize_fixture()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["source_file_count"], 4)
        self.assertFalse((self.root / "kit/source/.git").exists())
        self.assertEqual((self.root / "kit/source/src/example.py").read_bytes(), b"print('synthetic')")
        self.assertTrue((self.root / "original/TaxOpsControlDesk.exe").is_file())

    def test_wrong_outer_hash_fails_before_materialization(self):
        with self.assertRaisesRegex(proof.ProofError, "Outer"):
            self.materialize_fixture(values_change=lambda v: v.update(OUTER_SHA="0" * 64))
        self.assertFalse((self.root / "kit").exists())

    def test_wrong_kit_hash_fails_before_materialization(self):
        with self.assertRaisesRegex(proof.ProofError, "kit identity"):
            self.materialize_fixture(values_change=lambda v: v.update(KIT_SHA="0" * 64))
        self.assertFalse((self.root / "kit").exists())

    def test_wrong_normal_exe_hash_fails_before_materialization(self):
        with self.assertRaisesRegex(proof.ProofError, "normal EXE"):
            self.materialize_fixture(values_change=lambda v: v.update(EXE_SHA="0" * 64))

    def test_wrong_provenance_hash_fails_before_materialization(self):
        with self.assertRaisesRegex(proof.ProofError, "provenance"):
            self.materialize_fixture(values_change=lambda v: v.update(PROVENANCE_SHA="0" * 64))

    def test_source_commit_tree_and_accepted_exe_are_bound(self):
        for key in ("source_commit", "source_tree", "accepted_exe_sha256"):
            with self.subTest(key=key), self.assertRaisesRegex(proof.ProofError, "manifest identity"):
                self.materialize_fixture(lambda manifest, entries: manifest.update({key: "wrong"}))
            (self.root / "outer.zip").unlink()

    def test_source_rows_require_exact_bytes_and_hashes(self):
        for key, value in (("bytes", 99), ("sha256", "0" * 64)):
            with self.subTest(key=key), self.assertRaisesRegex(proof.ProofError, "differs from manifest"):
                self.materialize_fixture(lambda manifest, entries: manifest["files"][0].update({key: value}))
            (self.root / "outer.zip").unlink()

    def test_self_consistent_tamper_cannot_replace_independent_material_pin(self):
        def change(manifest, entries):
            entries[0] = (entries[0][0], b"tampered")
            manifest["files"][0].update(bytes=8, sha256=proof.digest(b"tampered"))
        with self.assertRaisesRegex(proof.ProofError, "independently fixed"):
            self.materialize_fixture(change)

    def test_extra_source_file_is_rejected(self):
        with self.assertRaises(proof.ProofError):
            self.materialize_fixture(lambda manifest, entries: entries.append(("source/extra.py", b"extra")))

    def test_duplicate_manifest_rows_are_rejected(self):
        def change(manifest, entries):
            manifest["files"][1] = copy.deepcopy(manifest["files"][0])
        with self.assertRaisesRegex(proof.ProofError, "Duplicate source"):
            self.materialize_fixture(change)

    def test_unsafe_windows_names_are_rejected(self):
        for name in ("/root", "../escape", "a/../b", "a//b", "a/./b", "a\\b", "C:/x", "file:stream",
                     "a.", "a ", "NUL", "con.txt", "COM1/x", "LPT9.txt", "a/aux.py", "CONIN$", "CONOUT$", "COM¹", "COM².txt", "LPT³", "a?b", "a\x00b", "a/"):
            with self.subTest(name=name), self.assertRaises(proof.ProofError):
                proof.safe_name(name)
        self.assertEqual(proof.safe_name("source/中文 空白.py"), "source/中文 空白.py")

    def test_zip_duplicate_case_and_file_directory_aliases_fail(self):
        for entries in ([('a', b'a'), ('a', b'b')], [('a', b'a'), ('A', b'b')], [('a', b'a'), ('a/b', b'b')]):
            with self.subTest(entries=entries), zipfile.ZipFile(io.BytesIO(zip_bytes(entries))) as archive:
                with self.assertRaises(proof.ProofError):
                    proof.zip_files(archive, max_files=10, max_bytes=100)

    def test_zip_symlink_and_reparse_entries_fail(self):
        for attributes in ((stat.S_IFLNK | 0o777) << 16, 0x400):
            item = zipfile.ZipInfo("a")
            item.external_attr = attributes
            with zipfile.ZipFile(io.BytesIO(zip_bytes([(item, b"x")]))) as archive:
                with self.assertRaises(proof.ProofError):
                    proof.zip_files(archive, max_files=10, max_bytes=100)

    def test_zip_count_and_expansion_bounds_fail(self):
        for count, size in ((0, 100), (10, 0)):
            with zipfile.ZipFile(io.BytesIO(zip_bytes([("a", b"x")]))) as archive:
                with self.assertRaisesRegex(proof.ProofError, "bounds"):
                    proof.zip_files(archive, max_files=count, max_bytes=size)

    def test_artifact_metadata_pins_both_distinct_commits_and_run(self):
        data = {"id": proof.ARTIFACT, "name": "windows-candidate-" + proof.COMMIT,
                "size_in_bytes": proof.OUTER_BYTES, "expired": False, "digest": "sha256:" + proof.OUTER_SHA,
                "workflow_run": {"id": proof.RUN, "head_sha": proof.HEAD,
                                 "repository_id": 1241835486, "head_repository_id": 1241835486}}
        proof.artifact_metadata(data)
        for key, value in (("id", 1), ("expired", True), ("digest", "wrong")):
            altered = copy.deepcopy(data)
            altered[key] = value
            with self.assertRaises(proof.ProofError):
                proof.artifact_metadata(altered)
        data["workflow_run"]["head_sha"] = proof.COMMIT
        with self.assertRaises(proof.ProofError):
            proof.artifact_metadata(data)

    def test_authenticated_redirect_never_forwards_token(self):
        calls = []
        def request(url, *, token=None):
            calls.append((url, token))
            return (Response(status=302, headers={"Location": "https://example.blob.core.windows.net/artifact?signature=PRIVATE"})
                    if len(calls) == 1 else Response(b"artifact"))
        with patch.object(proof, "request_once", request):
            proof.download(f"https://api.github.com/repos/{proof.REPO}/actions/artifacts/{proof.ARTIFACT}/zip",
                           self.root / "artifact.zip", expected_size=8, expected_hash=proof.digest(b"artifact"), token="SECRET")
        self.assertEqual(calls[0][1], "SECRET")
        self.assertIsNone(calls[1][1])

    def test_subsequent_storage_redirects_still_have_no_auth(self):
        calls = []
        def request(url, *, token=None):
            calls.append(token)
            if len(calls) < 3:
                return Response(status=302, headers={"Location": "https://example.blob.core.windows.net/a"})
            return Response(b"x")
        with patch.object(proof, "request_once", request):
            proof.download("https://api.github.com/repos/" + proof.REPO + "/actions/artifacts/1/zip",
                           self.root / "out", expected_size=1, expected_hash=proof.digest(b"x"), token="SECRET")
        self.assertEqual(calls, ["SECRET", None, None])

    def test_unexpected_storage_hosts_and_insecure_urls_stop_before_second_request(self):
        for url in ("http://a.blob.core.windows.net/x", "https://attacker.invalid/x",
                    "https://user:password@a.blob.core.windows.net/x", "https://a.blob.core.windows.net:444/x"):
            with self.subTest(url=url), patch.object(proof, "request_once", return_value=Response(
                    status=302, headers={"Location": url})) as request:
                with self.assertRaises(proof.ProofError):
                    proof.download("https://api.github.com/repos/" + proof.REPO + "/actions/artifacts/1/zip",
                                   self.root / "out", expected_size=1, expected_hash="x", token="SECRET")
                self.assertEqual(request.call_count, 1)

    def test_opener_disables_automatic_redirect_and_limits_auth_endpoint(self):
        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(request.get_header("Authorization"), "Bearer SECRET")
                self.assertEqual(timeout, 120)
                return Response()
        with patch.object(proof.urllib.request, "build_opener", return_value=Opener()) as factory:
            proof.request_once("https://api.github.com/repos/" + proof.REPO + "/actions/artifacts/1", token="SECRET")
            self.assertIsInstance(factory.call_args.args[0], proof.NoRedirect)
        self.assertIsNone(proof.NoRedirect().redirect_request(None, None, 302, None, None, "https://attacker.invalid"))
        with self.assertRaises(proof.ProofError):
            proof.request_once("https://attacker.invalid", token="SECRET")

    def test_transport_error_does_not_expose_url_or_secret(self):
        with patch.object(proof.urllib.request, "build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.URLError("https://host/?secret=SECRET")
            with self.assertRaises(proof.ProofError) as error:
                proof.request_once("https://example.blob.core.windows.net/x")
        self.assertNotIn("SECRET", str(error.exception))
        self.assertNotIn("https:", str(error.exception))

    def test_main_redacts_unexpected_exception_detail(self):
        out = io.StringIO()
        with patch.object(proof.sys, "argv", ["proof", "acquire", "--root", str(self.root)]), \
             patch.object(proof, "acquire", side_effect=OSError("SECRET signed-url")), \
             patch.object(proof.sys, "stderr", out):
            self.assertEqual(proof.main(), 1)
        self.assertNotIn("SECRET", out.getvalue())
        self.assertNotIn("signed-url", out.getvalue())

    def test_download_checks_length_and_hash(self):
        for content, size, sha in ((b"xx", 1, proof.digest(b"x")), (b"", 1, proof.digest(b"x")), (b"x", 1, "0" * 64)):
            with self.subTest(content=content), patch.object(proof, "request_once", return_value=Response(content)):
                with self.assertRaises(proof.ProofError):
                    proof.download("https://download.qt.io/x", self.root / "download", expected_size=size, expected_hash=sha)
            (self.root / "download").unlink(missing_ok=True)

    def test_build_environment_has_no_tokens_or_import_injection(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "SECRET", "GH_TOKEN": "SECRET", "PYTHONPATH": "evil",
                                    "QT_PLUGIN_PATH": "evil", "TAXOPS_RECOMBINE_INPUT": "evil",
                                    "ACTIONS_RUNTIME_TOKEN": "SECRET", "CMAKE_TOOLCHAIN_FILE": "evil",
                                    "CMAKE_PREFIX_PATH": "evil", "PYINSTALLER_CONFIG_DIR": "evil",
                                    "CL": "evil", "PATH": "compiler"}, clear=True):
            env = proof.clean_environment()
        self.assertEqual(env["PATH"], "compiler")
        self.assertFalse(any(value in {"SECRET", "evil"} for value in env.values()))
        self.assertEqual(env["PYTHONUTF8"], "1")

    def test_negative_control_requires_exact_expected_failure(self):
        report = {"status": "failed", "error": {"type": "ValueError",
                  "message": "Actual qgif plugin metadata lacks the compiled modification"}}
        proof.negative_report(report, 1)
        for altered, code in ((report, 0), (report, 77), ({"status": "passed"}, 1),
                              ({"status": "failed", "error": {"type": "ImportError", "message": "crash"}}, 1)):
            with self.assertRaises(proof.ProofError):
                proof.negative_report(altered, code)

    def test_embedded_code_fingerprint_detects_modified_code_not_build_path(self):
        a = compile("VALUE = 'marker'\n", "machine-a.py", "exec")
        b = compile("VALUE = 'marker'\n", "machine-b.py", "exec")
        c = compile("VALUE = 'unmodified'\n", "machine-a.py", "exec")
        self.assertEqual(proof.code_fingerprint(a), proof.code_fingerprint(b))
        self.assertNotEqual(proof.code_fingerprint(a), proof.code_fingerprint(c))

    def test_collection_excludes_sdk_vsix_venvs_profiles_and_normal_exe(self):
        for relative in ("downloads/private.vsix", "qt-sdk/bin/moc.exe", "work/venv-release/python.exe",
                         "negative-profile/database.sqlite", "original/TaxOpsControlDesk.exe"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"must not upload")
        receipt = self.root / "evidence/materialization.json"
        receipt.parent.mkdir()
        receipt.write_text('{"status":"passed"}')
        proof.collect(self.root, self.root / "upload")
        names = {p.relative_to(self.root / "upload").as_posix() for p in (self.root / "upload").rglob("*") if p.is_file()}
        self.assertEqual(names, {"evidence/materialization.json", "EVIDENCE-INVENTORY.json"})
        self.assertEqual(proof.read_json(self.root / "upload/EVIDENCE-INVENTORY.json")["status"], "incomplete")

    def test_before_import_independent_verification_detects_forged_identity_module(self):
        content, values = fixture()
        (self.root / "outer.zip").write_bytes(content)
        with ExitStack() as stack:
            for key, value in values.items():
                stack.enter_context(patch.object(proof, key, value))
            proof.materialize(self.root / "outer.zip", self.root)
            source = self.root / "kit/source"
            proof.verify_materialized_source(source)
            (source / "build_tools/recombine.py").write_bytes(b"forged code")
            with self.assertRaisesRegex(proof.ProofError, "bytes changed"):
                proof.verify_materialized_source(source)

    def test_collection_rejects_symlink_directory_root_and_ancestor(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.json").write_text("secret")
        (self.root / "evidence").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(proof.ProofError, "reparse"):
            proof.collect(self.root, self.root / "upload")

    def test_receipt_contracts_match_actual_run_38343015308_schema_fields(self):
        # Schema/status fields read from the fixed real normal artifact, not inferred.
        records = {"package-environment.json": {"schema": 1, "status": "passed"},
                   "official-vc.json": {"schema": 1, "status": "passed"},
                   "windows-system-runtime.json": {"schema": 2, "status": "passed"},
                   "windows-staging-input.json": {"schema": 1},
                   "windows-staging-dependencies.json": {"schema": 1, "status": "passed"}}
        proof.verify_receipt_contracts(records)
        for name, schema in (("package-environment.json", 2), ("windows-system-runtime.json", 1)):
            altered = copy.deepcopy(records)
            altered[name]["schema"] = schema
            with self.assertRaisesRegex(proof.ProofError, "contract mismatch"):
                proof.verify_receipt_contracts(altered)

    def test_collection_excludes_failed_extractions_and_profile_text_files(self):
        onefile = self.root / "work/recombined-onefile"
        for relative in ("selftest-profile/temp/_MEI123/secret.json", "payload-inspection/secret.txt",
                         "unusable-data-profile/private.json", "隔離使用者 空白/private.log"):
            path = onefile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("must not upload")
        for relative in ("onefile-provenance.json", "current-host-native-proof/windows-final-staging-input.json",
                         "shell-baseline/report.json", "shell-baseline/stderr.bin"):
            path = onefile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("diagnostic evidence")
        proof.collect(self.root, self.root / "upload")
        names = {p.relative_to(self.root / "upload").as_posix() for p in (self.root / "upload").rglob("*") if p.is_file()}
        self.assertEqual(names, {"EVIDENCE-INVENTORY.json", "recombined-onefile/onefile-provenance.json",
            "recombined-onefile/current-host-native-proof/windows-final-staging-input.json",
            "recombined-onefile/shell-baseline/report.json", "recombined-onefile/shell-baseline/stderr.bin"})

    def test_runner_context_is_only_used_in_step_environments(self):
        text = (Path(__file__).parents[1] / ".github/workflows/hosted-recombine-proof.yml").read_text()
        self.assertEqual(job_environment_context_violations(text), [])
        self.assertEqual(text.count("PROOF_ROOT: ${{ runner.temp }}"), 3)
        self.assertEqual(text.count("          PROOF_ROOT: ${{ runner.temp }}"), 3)
        for context in ("runner", "env", "job", "steps"):
            invalid = text.replace("    env:\n", "    env:\n      BAD: ${{ " + context + ".value }}\n", 1)
            self.assertEqual(job_environment_context_violations(invalid), [context])
        for context in ("github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"):
            valid = text.replace("    env:\n", "    env:\n      GOOD: ${{ " + context + ".value }}\n", 1)
            self.assertEqual(job_environment_context_violations(valid), [])

    def test_bootstrap_uses_raw_windows_command_line_without_native_argv_marshalling(self):
        cmd = Path(r"C:\Windows\System32\cmd.exe")
        batch = Path(r"C:\Runner Temp\tool chain (space)\invoke compiler.cmd")
        line = bootstrap.command_line(cmd, batch)
        self.assertEqual(line, '"C:\\Windows\\System32\\cmd.exe" /d /q /v:off /s /c call '
                               '"C:\\Runner Temp\\tool chain (space)\\invoke compiler.cmd"')
        with patch.object(bootstrap.subprocess, "run") as run:
            run.return_value.returncode = 37
            code = bootstrap.invoke(cmd, batch, cwd=self.root, env={"PATH": "kept"}, log=self.root / "native.log")
        self.assertEqual(code, 37)
        self.assertIsInstance(run.call_args.args[0], str)
        self.assertEqual(run.call_args.kwargs["executable"], str(cmd))
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertEqual(run.call_args.kwargs["env"], {"PATH": "kept"})

    def test_bootstrap_batch_propagates_failure_before_arch_or_child_and_never_dumps_environment(self):
        target = self.root / "existing tool chain.bat"
        batch = self.root / "wrapper.cmd"
        bootstrap.wrapper(batch, target, ["python.exe", "child.py"])
        content = batch.read_text()
        self.assertLess(content.index('if not "%errorlevel%"=="0" exit /b %errorlevel%'), content.index("VSCMD_ARG_TGT_ARCH"))
        self.assertLess(content.index("VSCMD_ARG_TGT_ARCH"), content.index('"python.exe"'))
        self.assertNotIn("&& set", content)
        self.assertNotIn("\nset\n", content)
        for value in ('percent%path', 'quote"path', 'line\nbreak', 'bang!path', 'caret^path', 'amp&path', 'nul\x00path', 'tab\tpath', 'nonascii中文', 'delete\x7f'):
            with self.assertRaises(proof.ProofError):
                bootstrap.quoted(value)

    def test_bootstrap_controls_precede_real_compiler_and_preserve_parent(self):
        source = Path(bootstrap.__file__).read_text()
        self.assertLess(source.index("    native_preflight(root, cmd, env)"), source.index("    wrapper(batch, vcvars"))
        for label in ("success", "nonzero", "missing-marker", "wrong-arch"):
            self.assertIn("'" + label + "':", source)
        self.assertIn("dict(os.environ) == before", source)
        workflow = (Path(__file__).parents[1] / ".github/workflows/hosted-recombine-proof.yml").read_text()
        self.assertIn("python -m build_tools.hosted_windows_bootstrap", workflow)
        self.assertNotIn("cmd.exe /d /s /c", workflow)
        self.assertNotIn("SetEnvironmentVariable", workflow)

    def test_native_controls_record_entry_separately_from_success_report(self):
        (self.root / "evidence").mkdir()
        def fake_invoke(cmd, batch, **kwargs):
            label = batch.stem.removeprefix("invoke ")
            if label in ("success", "missing-marker"):
                (batch.parent / (label + ".entered")).write_text("entered")
            if label == "success":
                (batch.parent / "success.json").write_text(json.dumps({
                    "marker": "synthetic marker with spaces", "arch": "x64"}))
            return {"success": 0, "nonzero": 37, "missing-marker": 43, "wrong-arch": 41}[label]
        with patch.object(bootstrap, "invoke", fake_invoke):
            report = bootstrap.native_preflight(self.root, Path("cmd.exe"), {})
        controls = {row["control"]: row for row in report["controls"]}
        self.assertTrue(controls["missing-marker"]["child_reached"])
        self.assertFalse(controls["missing-marker"]["child_report_written"])
        self.assertFalse(controls["nonzero"]["child_reached"])
        self.assertFalse(controls["wrong-arch"]["child_reached"])

    def test_native_controls_reject_child_entry_after_nonzero_batch(self):
        (self.root / "evidence").mkdir()
        def fake_invoke(cmd, batch, **kwargs):
            label = batch.stem.removeprefix("invoke ")
            (batch.parent / (label + ".entered")).write_text("entered")
            if label == "success":
                (batch.parent / "success.json").write_text(json.dumps({
                    "marker": "synthetic marker with spaces", "arch": "x64"}))
                return 0
            return 37
        with patch.object(bootstrap, "invoke", fake_invoke):
            with self.assertRaisesRegex(proof.ProofError, "Unexpected child entry"):
                bootstrap.native_preflight(self.root, Path("cmd.exe"), {})

    def test_native_preflight_preserves_safe_unexpected_exit_evidence(self):
        (self.root / "evidence").mkdir()
        with patch.object(bootstrap, "invoke", return_value=19):
            with self.assertRaises(proof.ProofError):
                bootstrap.native_preflight(self.root, Path("cmd.exe"), {})
        report = proof.read_json(self.root / "evidence/bootstrap-native-controls.json")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["active_control"], "success")
        self.assertEqual(report["phase"], "validate")
        self.assertEqual(report["controls"][0]["exit_code"], 19)

    def test_native_preflight_timeout_receipt_redacts_raw_command_details(self):
        (self.root / "evidence").mkdir()
        with patch.object(bootstrap, "invoke", side_effect=bootstrap.subprocess.TimeoutExpired("SECRET", 30)):
            with self.assertRaises(bootstrap.subprocess.TimeoutExpired):
                bootstrap.native_preflight(self.root, Path("cmd.exe"), {})
        path = self.root / "evidence/bootstrap-native-controls.json"
        report = proof.read_json(path)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["phase"], "invoke")
        self.assertEqual(report["error"]["type"], "TimeoutExpired")
        self.assertIsNone(report["error"]["observed_exit_code"])
        self.assertNotIn("SECRET", path.read_text())

    def test_workflow_is_bounded_read_only_and_does_not_run_new_checkout_as_product(self):
        workflow = Path(__file__).parents[1] / ".github/workflows/hosted-recombine-proof.yml"
        text = workflow.read_text()
        self.assertIn("branches: [diagnostics/hosted-recombine-proof-20261013]", text)
        self.assertIn("runs-on: windows-2022", text)
        self.assertIn("actions: read", text)
        self.assertNotIn("actions: write", text)
        self.assertNotIn("contents: write", text)
        self.assertIn("persist-credentials: false", text)
        self.assertEqual(text.count("GITHUB_TOKEN:"), 1)
        self.assertIn("path: artifacts/fixed-kit-proof/", text)
        self.assertNotIn("pull_request_target", text)


if __name__ == "__main__":
    unittest.main()
