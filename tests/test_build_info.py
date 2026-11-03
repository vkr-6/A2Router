"""Release identity and icon geometry checks; no Windows settings are touched."""

import hashlib
import json
import subprocess
from pathlib import Path

from a2router.build_info import collect_build_info, read_build_info


def test_provenance_records_commit_dirty_state_and_native_hash(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    dll = tmp_path / "native.dll"
    dll.write_bytes(b"synthetic build input")
    subprocess.run(["git", "-C", str(tmp_path), "add", "native.dll"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    info = collect_build_info(tmp_path, dll)
    assert len(info["source_commit"]) == 40 and info["source_dirty"] is False
    assert info["native_dll_sha256"] == hashlib.sha256(dll.read_bytes()).hexdigest()
    assert info["built_at_utc"].endswith("+00:00")
    dll.write_bytes(b"changed")
    assert collect_build_info(tmp_path, dll)["source_dirty"] is True
    report = tmp_path / "info.json"
    report.write_text(json.dumps(info))
    assert read_build_info(report) == info
    report.write_text("invalid json")
    assert "app_version" in read_build_info(report)


def test_app_and_packaging_share_square_transparent_icon():
    from PySide6.QtGui import QImage

    root = Path(__file__).resolve().parents[1]
    image = QImage(str(root / "a2router/assets/a2router.png"))
    assert image.width() == image.height() == 1024 and image.hasAlphaChannel()
    assert all(image.pixelColor(x, y).alpha() == 0 for x, y in ((0, 0), (1023, 0), (0, 1023), (1023, 1023)))
