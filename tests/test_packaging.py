"""Package layout checks use a dummy executable; never install a package/driver."""

import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from tools.linux.package import package

ROOT = Path(__file__).resolve().parents[1]


def test_linux_archive_and_deb_layout_without_installing(tmp_path):
    if not shutil.which("dpkg-deb"):
        pytest.skip("Debian packaging tool unavailable")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    executable = bundle / "a2router"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (bundle / "LICENSE").write_text("test fixture")
    artifacts = package(bundle, tmp_path / "dist")
    assert len(artifacts) == 2
    with tarfile.open(artifacts[0]) as archive:
        assert "A2Router-linux-x86_64/a2router" in archive.getnames()
    control = subprocess.run(
        ["dpkg-deb", "--field", str(artifacts[1])], text=True, capture_output=True, check=True
    ).stdout
    assert "Architecture: amd64" in control and "pipewire-pulse" in control
    extracted = tmp_path / "extracted"
    subprocess.run(["dpkg-deb", "--extract", str(artifacts[1]), str(extracted)], check=True)
    assert (extracted / "opt/a2router/a2router").exists()
    assert 'exec /opt/a2router/a2router "$@"' in (extracted / "usr/bin/a2router").read_text()
    assert "Name=A2Router" in (extracted / "usr/share/applications/a2router.desktop").read_text()
    assert not (extracted / "DEBIAN/postinst").exists()
    assert len((tmp_path / "dist/SHA256SUMS-linux.txt").read_text().splitlines()) == 2


def test_setup_bundles_payload_and_driver_options_are_opt_in():
    setup = (ROOT / "tools/windows/setup.iss").read_text()
    driver = next(line for line in setup.splitlines() if line.startswith("Name: vbcable;"))
    assert "Flags: unchecked" in driver
    assert "Choice.Checked := False" in setup
    assert "and RemoveSharedDriver then" in setup
    assert "and WizardIsTaskSelected('vbcable') then" in setup
    assert "install-vbcable.ps1" in setup and "ewWaitUntilTerminated" in setup
    assert "recursesubdirs" in setup and "UninstallNeedRestart" in setup
    helper = (ROOT / "tools/windows/build-setup.ps1").read_text()
    assert "VBCABLE_Setup_x64.exe" in helper
    assert "never installs tools" in helper
    assert "Start-Process" not in helper


def test_manual_workflow_has_separate_targets_and_no_installer_execution():
    text = (ROOT / ".github/workflows/build.yml").read_text()
    assert "workflow_dispatch:" in text and "\n  push:" not in text and "\n  pull_request:" not in text
    for key in ("windows_portable:", "windows_setup:", "linux:"):
        assert key in text
    for artifact in (
        "a2router-windows-x64.zip",
        "a2router-windows-x64-setup.exe",
        "a2router-linux-x86_64.tar.gz",
        "dist/*.deb",
    ):
        assert artifact in text
    assert "Build setup EXE without running it" in text
    assert "run: ./tools/windows/build-setup.ps1" in text


def test_frozen_audio_tools_receive_host_library_path(monkeypatch):
    import sys

    from a2router.backends.linux_pipewire import system_audio_environment

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/private/frozen/runtime")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    assert "LD_LIBRARY_PATH" not in system_audio_environment()
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/original/host/libraries")
    assert system_audio_environment()["LD_LIBRARY_PATH"] == "/original/host/libraries"
