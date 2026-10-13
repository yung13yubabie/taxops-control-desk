"""Plain-language storage failures and best-effort local startup diagnostics."""

from __future__ import annotations

import errno
import logging
import sqlite3
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


def _storage_guidance(error: sqlite3.Error | OSError) -> str:
    # Extended SQLite result codes keep the primary result in the low byte.
    code = getattr(error, "sqlite_errorcode", 0) & 0xFF
    os_code = getattr(error, "errno", None)
    if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
        return (
            "無法讀取資料檔，檔案可能已損壞或不是可用的資料庫。\n\n"
            "請先另外保留一份原始資料，再請維護人員檢查；"
            "需要復原時，請使用已確認可用的備份。"
        )
    if code == sqlite3.SQLITE_FULL or os_code == errno.ENOSPC:
        return (
            "儲存空間不足，無法完成啟動。\n\n"
            "請先騰出資料所在磁碟的空間，再重新開啟程式。"
            "不要刪除本程式的資料檔或附件來騰出空間。"
        )
    if (
        isinstance(error, PermissionError)
        or os_code in {errno.EACCES, errno.EPERM, errno.EROFS}
        or code in {sqlite3.SQLITE_PERM, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_AUTH}
    ):
        return (
            "目前無法寫入程式的資料夾或資料檔。\n\n"
            "請確認您對資料夾有讀寫權限，且磁碟不是唯讀，再重新開啟程式。"
            "若不確定如何處理，請聯絡電腦管理人員。"
        )
    if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return (
            "資料檔目前忙碌，無法完成啟動。\n\n"
            "請先關閉其他正在使用這份資料的程式，稍候再重新開啟。"
        )
    return (
        "讀取或寫入程式資料時失敗，無法完成啟動。\n\n"
        "請確認資料所在磁碟可正常使用、空間足夠，且資料夾有讀寫權限，"
        "再重新開啟程式。若仍無法開啟，請聯絡維護人員檢查。"
    )


def _save_diagnostic(error: sqlite3.Error | OSError) -> tuple[Path | None, Path | None]:
    """Return the complete log, or the possibly remaining incomplete log."""
    details = (type(error), error, error.__traceback__)
    _log.error("Application storage initialization failed", exc_info=details)
    created_path = None
    try:
        # Use an exclusively created local temporary file, not the failing data
        # directory. No locals, database contents, or attachments are collected.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="TaxOps-startup-", suffix=".log",
            delete=False,
        ) as output:
            created_path = Path(output.name)
            output.write(f"UTC: {datetime.now(timezone.utc).isoformat()}\n")
            output.write(f"Error type: {type(error).__name__}\n")
            output.write(f"SQLite code: {getattr(error, 'sqlite_errorcode', None)}\n")
            output.write("".join(traceback.format_exception(*details)))
        return created_path, None
    except OSError:
        # Storage may be unavailable everywhere. Never replace the startup
        # failure with a logging failure or promise that a file was saved.
        _log.warning("Could not save startup diagnostic file", exc_info=True)
        if created_path is not None:
            try:
                # Only this attempt's incomplete file is ours to clean up.
                created_path.unlink(missing_ok=True)
            except OSError:
                _log.warning("Could not remove incomplete startup diagnostic file", exc_info=True)
                return None, created_path
        return None, None


def startup_error_message(error: sqlite3.Error | OSError) -> str:
    """Describe recovery without exposing raw exceptions or rebuilding data."""
    message = _storage_guidance(error)
    message += "\n\n程式已停止啟動，沒有自動重建資料。請勿刪除或覆蓋原本的資料檔與附件。"
    diagnostic, incomplete = _save_diagnostic(error)
    if diagnostic is None:
        message += "\n\n診斷紀錄無法儲存。請記下此畫面，提供給維護人員。"
        if incomplete is not None:
            message += f"\n未完成的診斷檔無法清理，可能仍保留在：{incomplete}\n這不是完整的診斷紀錄。"
        return message
    return message + f"\n\n本機診斷紀錄：{diagnostic}\n如需協助，請將這份紀錄提供給維護人員。"
