"""HTTP download of the official MOF tax registry ZIP.

Only URLs that pass ``is_allowed_official_url()`` may be downloaded.
The service validates both the requested URL and the final redirect target.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from pathlib import Path

from ..security.domains import is_allowed_official_url

_log = logging.getLogger(__name__)


class DownloadError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_CHUNK = 65_536  # 64 KB read chunks
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB, aligned with ZIP import guard


def _content_length(resp: object) -> int | None:
    headers = getattr(resp, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("Content-Length")
    except AttributeError:
        return None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        _log.warning("failed to remove partial download %s", path, exc_info=True)


def download_registry_zip(
    url: str,
    dest_path: Path,
    timeout: int = 300,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> None:
    """Download *url* to *dest_path* as a raw binary file.

    Raises DownloadError on network, I/O, or resource-limit failure.
    The file is written to ``*.part`` first and atomically moved into place only
    after the full download succeeds. Failed downloads do not leave a partial
    file at ``dest_path``.
    """
    part_path = dest_path.with_name(dest_path.name + ".part")
    try:
        if not is_allowed_official_url(url):
            raise DownloadError("registry.download.url_not_allowed")
        req = urllib.request.Request(
            url, headers={"User-Agent": "TaxOps-ControlDesk/1.0"}
        )
        # The requested and redirected URLs are both restricted to HTTPS hosts
        # in the official-domain allowlist.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            response_url = getattr(resp, "geturl", lambda: url)()
            if isinstance(response_url, str) and not is_allowed_official_url(
                response_url
            ):
                raise DownloadError("registry.download.url_not_allowed")
            announced_size = _content_length(resp)
            if announced_size is not None and announced_size > max_bytes:
                raise DownloadError("registry.download.too_large")

            total = 0
            with open(part_path, "wb") as fh:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadError("registry.download.too_large")
                    fh.write(chunk)
            part_path.replace(dest_path)
    except DownloadError:
        _unlink_quietly(part_path)
        raise
    except urllib.error.URLError as exc:
        _unlink_quietly(part_path)
        raise DownloadError("registry.download.network_error") from exc
    except OSError as exc:
        _unlink_quietly(part_path)
        raise DownloadError("registry.download.io_error") from exc
    except Exception:
        _unlink_quietly(part_path)
        raise
