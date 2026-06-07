# Command Execution Rules

## Why PowerShell quoting failed

The failure was a shell-semantics mismatch, not a product bug. PowerShell does
not expand Bash-style path globs for every native executable. A command such as:

```powershell
rg PATTERN tests/test* -S
```

can pass the literal invalid Windows path `tests/test*` to `rg`.

Use the tool's own glob option:

```powershell
rg PATTERN tests -g '*.py' -S
```

## Required rules

1. Prefer native PowerShell cmdlets or direct argv lists; do not nest
   `powershell -Command` unless required.
2. Use single quotes for regex and literal paths. Use double quotes only when
   interpolation is required.
3. For ripgrep, search a real directory and use `-g` for file patterns.
4. For Python subprocesses, pass an argument list and keep `shell=False`.
5. For multiline inline Python, use a PowerShell here-string piped to Python.
6. Do not concatenate user-controlled values into shell, SQL, URL, or path
   commands.
7. Capture exit code, stdout, and stderr. No output is not proof that a command
   is still running.
8. For long tests, start one hidden process, record its PID, redirect output to
   named files, and poll that exact PID.
9. Stop only the recorded PID. Never kill every `python.exe`, `node.exe`, or
   browser process as a cleanup shortcut.
10. Re-run final verification if source or tests change while a suite is running.
11. Do not pipe directly from a `foreach (...) { ... }` statement. Assign its
    output first, then pipe the variable:

```powershell
$rows = foreach ($item in $items) { [pscustomobject]@{ Value = $item } }
$rows | Format-Table
```

## Safe examples

```powershell
rg -n 'TODO|FIXME|except pass' src tests -g '*.py'
Get-ChildItem -Path src -Recurse -Filter '*.py'
python -m pytest tests/test_tasks.py -q --tb=short
git diff --check
```

## Long-running test protocol

1. Redirect stdout and stderr to `.ai/`.
2. Store the PID in `.ai/`.
3. Poll `Get-Process -Id <pid>` and tail both output files.
4. If code changes, stop only that PID and restart from the final worktree.
5. On completion, verify process exit and inspect summary plus exit code before
   reporting success.
