"""Synthetic preparation contracts, not Windows compiler evidence."""
import hashlib
import io
import json
import tarfile

import pytest

from build_tools.qgif_rebuild import prepare_source as qgif


def archive(tmp_path, monkeypatch, extra=None):
    path = tmp_path / "source.tar.xz"
    with tarfile.open(path, "w:xz") as target:
        for name in qgif.INPUTS:
            data = b'{"Keys":["gif"],"MimeTypes":["image/gif"]}' if name == "gif.json" else b"synthetic source"
            entry = tarfile.TarInfo(f"{qgif.SOURCE_ROOT}/src/plugins/imageformats/gif/{name}")
            entry.size = len(data)
            target.addfile(entry, io.BytesIO(data))
        entry = tarfile.TarInfo(extra or f"{qgif.SOURCE_ROOT}/LICENSES/LGPL-3.0-only.txt")
        if extra and extra.endswith("link"):
            entry.type = tarfile.SYMTYPE
            entry.linkname = "../../escape"
            target.addfile(entry)
        else:
            entry.size = 7
            target.addfile(entry, io.BytesIO(b"license"))
    monkeypatch.setattr(qgif, "QTBASE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    return path


def test_prepare_retains_sources_licenses_and_changes_real_metadata(tmp_path, monkeypatch):
    path = archive(tmp_path, monkeypatch)
    out = tmp_path / "prepared"
    result = qgif.prepare(path, out)
    assert json.loads((out / "gif.json").read_text())["TaxOpsRecombineMarker"] == qgif.MARKER
    assert len(result["files"]) == 4
    assert (out / "LICENSES/LGPL-3.0-only.txt").read_bytes() == b"license"
    assert result["files"][-1]["upstream_sha256"] != result["files"][-1]["prepared_sha256"]
    with pytest.raises(ValueError, match="new source directory"):
        qgif.prepare(path, out)


def test_hash_failure_does_not_create_output(tmp_path):
    path = tmp_path / "invalid.tar.xz"
    path.write_bytes(b"not the Qt archive")
    with pytest.raises(ValueError, match="SHA-256"):
        qgif.prepare(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("tail", ["../../escape", "link", "C:/absolute", "back\\slash"])
def test_unsafe_license_member_is_rejected_and_partial_output_retained(tmp_path, monkeypatch, tail):
    path = archive(tmp_path, monkeypatch, f"{qgif.SOURCE_ROOT}/LICENSES/{tail}")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="Unsafe"):
        qgif.prepare(path, out)
    assert out.is_dir() and not (out / "source-receipt.json").exists()
    assert not (tmp_path / "escape").exists()
