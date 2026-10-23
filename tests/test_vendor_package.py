import hashlib
import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_vbcable", ROOT / "tools/windows/prepare_vbcable.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_vendor_archive_extracted_without_changes(tmp_path):
    archive = ROOT / "vendor/vbcable/VBCABLE_Driver_Pack45.zip"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == module.ARCHIVE_SHA256
    module.prepare(archive, tmp_path / "vendor")
    with zipfile.ZipFile(archive) as original:
        for name in original.namelist():
            assert (tmp_path / "vendor" / name).read_bytes() == original.read(name)


def test_modified_vendor_archive_is_rejected(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"Not the supplied package")
    with pytest.raises(ValueError, match="hash"):
        module.prepare(bad, tmp_path / "result")
    assert not (tmp_path / "result").exists()
