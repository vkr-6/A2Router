"""Exercise driver decisions with mocked Windows commands; no installer execution."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell required")


def test_install_uninstall_preserves_ownership_and_checks_pnp(tmp_path):
    source = str(Path(__file__).resolve().parents[1] / "tools/windows/install-vbcable.ps1").replace("'", "''")
    fixture = str(tmp_path).replace("'", "''")
    script = r"""
$ErrorActionPreference = 'Stop'
$directory = '__FIXTURE__'
[IO.File]::WriteAllBytes((Join-Path $directory 'VBCABLE_Setup_x64.exe'), [byte[]]@())
$state = Join-Path $directory 'owned.flag'
$log = Join-Path $directory 'mock.log'
$global:Present = $false
$global:ProblemCode = 0
$global:Calls = @()
$global:FailRemoval = $false
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($global:Present) { [pscustomobject]@{ConfigManagerErrorCode = $global:ProblemCode} }
}
function Get-AuthenticodeSignature {
    param($LiteralPath)
    [pscustomobject]@{Status = 'Valid'}
}
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, [switch]$Wait, [switch]$PassThru)
    $global:Calls += $ArgumentList[0]
    if ($ArgumentList[0] -eq '-i') { $global:Present = $true }
    elseif (!$global:FailRemoval) { $global:Present = $false }
    # Proves the code checks device state rather than assuming vendor exit code 0.
    [pscustomobject]@{ExitCode = 17}
}
function Start-Sleep { param($Milliseconds) }
& '__SOURCE__' -Directory $directory -StateFile $state -LogPath $log
if ($LASTEXITCODE -ne 0 -or !(Test-Path $state)) { throw 'Ready install not recorded' }
& '__SOURCE__' -Directory $directory -StateFile $state -LogPath $log
if ($LASTEXITCODE -ne 0 -or $global:Calls.Count -ne 1) { throw 'Existing cable was modified' }
$global:FailRemoval = $true
$failed = $false
try { & '__SOURCE__' -Directory $directory -StateFile $state -LogPath $log -Uninstall }
catch { $failed = $true }
if (!$failed -or !(Test-Path $state)) { throw 'Failed removal was not reported/ownership lost' }
$global:FailRemoval = $false
& '__SOURCE__' -Directory $directory -StateFile $state -LogPath $log -Uninstall
if ($LASTEXITCODE -ne 3010 -or (Test-Path $state)) { throw 'Removal/restart/ownership cleanup failed' }
$count = $global:Calls.Count
& '__SOURCE__' -Directory $directory -StateFile $state -LogPath $log -Uninstall
if ($LASTEXITCODE -ne 0 -or $global:Calls.Count -ne $count) { throw 'Absent driver removal was not idempotent' }
$global:Present = $true
& '__SOURCE__' -Directory $directory -StateFile $state -LogPath $log
if ((Test-Path $state) -or $global:Calls.Count -ne $count) { throw 'Pre-existing cable was claimed/modified' }
$global:ProblemCode = 14
& '__SOURCE__' -Directory $directory -StateFile $state -LogPath $log
if ($LASTEXITCODE -ne 3010 -or $global:Calls.Count -ne $count) { throw 'Pending restart was not reported' }
Write-Output 'PASS: installer/uninstaller mock decisions; no vendor executable ran'
""".replace("__FIXTURE__", fixture).replace("__SOURCE__", source)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: installer/uninstaller mock decisions" in result.stdout


@pytest.mark.parametrize("outcome", ["ready", "restart", "cancel", "timeout", "read_failure", "changed_com"])
def test_elevated_process_handles_and_com_are_released_without_launch(monkeypatch, tmp_path, outcome):
    import ctypes

    from a2router.backends import windows_vbcable
    from a2router.models import BackendError

    calls = []

    class Function:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    class Library:
        def __init__(self, **functions):
            for name, callback in functions.items():
                setattr(self, name, Function(callback))

    def execute(pointer):
        info = pointer._obj
        assert info.cbSize == (112 if ctypes.sizeof(ctypes.c_void_p) == 8 else 60)
        assert info.lpVerb == "runas" and info.lpFile == "not-an-executable"
        calls.append("shell_mock")
        if outcome == "cancel":
            return False
        info.hProcess = 123
        return True

    def exit_code(handle, pointer):
        pointer._obj.value = 3010 if outcome == "restart" else 0
        return outcome != "read_failure"

    libraries = {
        "shell32": Library(ShellExecuteExW=execute),
        "kernel32": Library(
            WaitForSingleObject=lambda *args: 258 if outcome == "timeout" else 0,
            GetExitCodeProcess=exit_code,
            CloseHandle=lambda handle: calls.append("close_mock") or 1,
        ),
        "ole32": Library(
            CoInitializeEx=lambda *args: -2147417850 if outcome == "changed_com" else 0,
            CoUninitialize=lambda: calls.append("uninitialize_mock"),
        ),
    }
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **kwargs: libraries[name])
    if outcome in ("cancel", "timeout", "read_failure"):
        with pytest.raises(BackendError):
            windows_vbcable._run_elevated("not-an-executable", ["test argument"], tmp_path)
    else:
        assert windows_vbcable._run_elevated("not-an-executable", ["test argument"], tmp_path) == (
            3010 if outcome == "restart" else 0
        )
    assert ("close_mock" in calls) == (outcome != "cancel")
    assert ("uninitialize_mock" in calls) == (outcome != "changed_com")
