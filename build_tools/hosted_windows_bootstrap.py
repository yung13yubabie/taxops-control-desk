"""Run existing vcvars and the fixed-kit proof in one isolated child CMD.

A raw Windows command line bypasses PowerShell's legacy cmd.exe argv quoting.
No environment is dumped, imported into the parent, or persistently changed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from build_tools.hosted_recombine_proof import clean_environment, file_hash, require, write_json


def quoted(value: str) -> str:
    # CALL performs a second expansion. Reject expansion/control syntax even in
    # quoted paths; spaces and parentheses in ASCII hosted paths are valid.
    # The generated CMD is ASCII, so non-ASCII paths fail before invocation.
    require(bool(value) and all(32 <= ord(c) < 127 for c in value)
            and not any(c in value for c in '"%!^&|<>'), "Unsupported CMD argument character")
    return '"' + value + '"'


def command_line(cmd: Path, batch: Path) -> str:
    # Windows CreateProcess receives this string unchanged. Do not replace it
    # with a sequence (C-runtime list2cmdline) or shell=True/PowerShell nesting.
    return f'{quoted(str(cmd))} /d /q /v:off /s /c call {quoted(str(batch))}'


def wrapper(batch: Path, target: Path, child: list[str]) -> None:
    require(not batch.exists(), "Bootstrap batch already exists")
    lines = ['@echo off', f'call {quoted(str(target))} x64',
             'if not "%errorlevel%"=="0" exit /b %errorlevel%',
             'if /i not "%VSCMD_ARG_TGT_ARCH%"=="x64" exit /b 41',
             ' '.join(quoted(value) for value in child), 'exit /b %errorlevel%']
    batch.write_bytes(('\r\n'.join(lines) + '\r\n').encode('ascii'))


def invoke(cmd: Path, batch: Path, *, cwd: Path, env: dict, log: Path,
           timeout: int | None = None) -> int:
    with log.open('wb') as handle:
        result = subprocess.run(command_line(cmd, batch), executable=str(cmd), shell=False,
                                cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
    return result.returncode


def native_preflight(root: Path, cmd: Path, env: dict) -> dict:
    """Actual Windows controls, using exactly the invocation used for vcvars."""
    folder = root / 'bootstrap spaced paths'
    folder.mkdir(exist_ok=False)
    receiver = folder / 'receive selected marker.py'
    receiver.write_text(
        'import json, os, pathlib, sys\n'
        'pathlib.Path(sys.argv[2]).write_text("entered", encoding="utf-8")\n'
        'marker = os.environ.get("TAXOPS_TOOLCHAIN_PROBE")\n'
        'arch = os.environ.get("VSCMD_ARG_TGT_ARCH")\n'
        'if marker != "synthetic marker with spaces" or arch != "x64":\n'
        '    raise SystemExit(43)\n'
        'pathlib.Path(sys.argv[1]).write_text(json.dumps({"marker": marker, "arch": arch}), encoding="utf-8")\n',
        encoding='utf-8')
    controls = {
        'success': ('set "TAXOPS_TOOLCHAIN_PROBE=synthetic marker with spaces"\r\n'
                    'set "VSCMD_ARG_TGT_ARCH=x64"\r\nexit /b 0', 0),
        'nonzero': ('echo PATH=synthetic partial environment\r\n'
                    'set "VSCMD_ARG_TGT_ARCH=x64"\r\nexit /b 37', 37),
        'missing-marker': ('set "VSCMD_ARG_TGT_ARCH=x64"\r\nexit /b 0', 43),
        'wrong-arch': ('set "TAXOPS_TOOLCHAIN_PROBE=synthetic marker with spaces"\r\n'
                       'set "VSCMD_ARG_TGT_ARCH=x86"\r\nexit /b 0', 41),
    }
    original = os.environ.copy()
    report = {'status': 'failed', 'platform': sys.platform, 'phase': 'prepare',
              'controls': [], 'same_raw_cmd_invocation': True,
              'full_environment_dumped': False, 'ascii_command_paths_only': True,
              'bootstrap_sha256': file_hash(Path(__file__))}
    receipt = root / 'evidence/bootstrap-native-controls.json'
    try:
        for label, (body, expected) in controls.items():
            report.update(active_control=label, phase='prepare')
            write_json(receipt, report)
            target = folder / f'{label} tool chain.bat'
            target.write_bytes(('@echo off\r\nif not "%~1"=="x64" exit /b 39\r\n' + body + '\r\n').encode('ascii'))
            child_report = folder / f'{label}.json'
            child_entry = folder / f'{label}.entered'
            batch = folder / f'invoke {label}.cmd'
            wrapper(batch, target, [sys.executable, str(receiver), str(child_report), str(child_entry)])
            report['phase'] = 'invoke'
            write_json(receipt, report)
            try:
                code = invoke(cmd, batch, cwd=folder, env=env, log=root / f'evidence/bootstrap-{label}.log', timeout=30)
            except subprocess.TimeoutExpired:
                report['error'] = {'type': 'TimeoutExpired', 'timeout_seconds': 30, 'observed_exit_code': None}
                raise
            row = {'control': label, 'expected_exit_code': expected, 'exit_code': code,
                   'child_reached': child_entry.exists(), 'child_report_written': child_report.exists()}
            report['controls'].append(row)
            report['phase'] = 'validate'
            write_json(receipt, report)
            require(code == expected, 'Native spaced-path batch control returned an unexpected exit code: ' + label)
            require(child_entry.exists() == (expected in (0, 43)), 'Unexpected child entry after native batch control')
            require(child_report.exists() == (expected == 0), 'Native control produced an unexpected success report')
            if expected == 0:
                require(json.loads(child_report.read_text()) == {
                    'marker': 'synthetic marker with spaces', 'arch': 'x64'}, 'Native child did not inherit selected batch environment')
        require(dict(os.environ) == original, 'Native preflight changed the parent environment')
        report.update(status='passed', phase='complete', active_control=None)
        return report
    finally:
        report['parent_environment_unchanged'] = dict(os.environ) == original
        write_json(receipt, report)


def bootstrap(root: Path, vcvars: Path) -> None:
    require(sys.platform == 'win32' and sys.version_info[:3] == (3, 11, 9), 'Windows CPython 3.11.9 required')
    cmd = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
    require(cmd.is_file() and vcvars.is_file() and vcvars.name.casefold() == 'vcvarsall.bat', 'Existing Windows CMD and vcvars required')
    env = clean_environment()
    # Avoid inherited overrides of CMD status or verbose VS environment dumps.
    env.pop('ERRORLEVEL', None)
    env.pop('VSCMD_DEBUG', None)
    native_preflight(root, cmd, env)
    batch = root / 'bootstrap spaced paths/invoke actual compiler.cmd'
    wrapper(batch, vcvars, [sys.executable, '-m', 'build_tools.hosted_recombine_proof', 'run', '--root', str(root)])
    before = os.environ.copy()
    code = invoke(cmd, batch, cwd=Path(__file__).resolve().parents[1], env=env,
                  log=root / 'evidence/bootstrap-proof.log')
    require(dict(os.environ) == before, 'Compiler bootstrap changed the parent environment')
    require(code == 0, 'Compiler/proof child failed; see bootstrap-proof.log')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--vcvars', required=True, type=Path)
    args = parser.parse_args()
    try:
        bootstrap(args.root.resolve(), args.vcvars.resolve())
        print('Native compiler bootstrap: passed')
        return 0
    except Exception as exc:
        # Do not echo arbitrary native exception details/environment values.
        from build_tools.hosted_recombine_proof import ProofError
        message = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
        print('Native compiler bootstrap: failed (' + message + ')', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
