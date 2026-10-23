"""Exercise installer decisions with mocked Windows commands; no driver execution."""

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
$global:Calls = @()
$global:FailRemoval = $false
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($global:Present) { [pscustomobject]@{ConfigManagerErrorCode = 0} }
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
if ($LASTEXITCODE -ne 3010 -or !(Test-Path $state)) { throw 'New install not recorded/reboot not requested' }
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
