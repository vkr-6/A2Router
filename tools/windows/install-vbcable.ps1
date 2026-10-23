param(
    [Parameter(Mandatory = $true)][string]$Directory,
    [string]$StateFile = '',
    [string]$LogPath = '',
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$log = $LogPath
if (!$log) { $log = Join-Path $env:TEMP 'A2Router-VBCABLE-install.log' }
function Write-InstallLog([string]$Message) {
    Add-Content -LiteralPath $log -Value ((Get-Date -Format o) + ' ' + $Message)
}
function Find-Cable {
    @(Get-CimInstance Win32_PnPEntity -Filter "Service='VBAudioVACMME'" -ErrorAction Stop)
}
try {
    $existing = @(Find-Cable)
    if ($Uninstall -and !$existing.Count) {
        Write-InstallLog 'VB-CABLE already absent; no driver changes.'
        if ($StateFile -and (Test-Path -LiteralPath $StateFile)) { Remove-Item -LiteralPath $StateFile -Force }
        exit 0
    }
    if (!$Uninstall -and $existing.Count -gt 0) {
        if (@($existing | Where-Object { $_.ConfigManagerErrorCode -notin @(0, 14) }).Count) {
            throw 'Existing VB-CABLE reports a device problem. Repair it with the vendor installer; setup will not overwrite it.'
        }
        Write-InstallLog 'VB-CABLE already installed; left unchanged.'
        if (@($existing | Where-Object { $_.ConfigManagerErrorCode -eq 14 }).Count) { exit 3010 }
        exit 0
    }
    $installer = Join-Path $Directory 'VBCABLE_Setup_x64.exe'
    if (!(Test-Path -LiteralPath $installer -PathType Leaf)) { throw 'VB-CABLE vendor installer is missing' }
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid') { throw "Vendor installer signature is not accepted: $($signature.Status)" }
    $action = if ($Uninstall) { '-u' } else { '-i' }
    Write-InstallLog "Starting original VB-CABLE setup ($action). No certificate or security policy changes."
    $process = Start-Process -FilePath $installer -ArgumentList $action,'-h' -WorkingDirectory $Directory -Wait -PassThru
    Write-InstallLog "Vendor installer exit code: $($process.ExitCode)"
    # Vendor exit codes are not used as proof of installation: inspect PnP.
    $cable = @()
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $cable = @(Find-Cable)
        if (($Uninstall -and !$cable.Count) -or (!$Uninstall -and $cable.Count)) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($Uninstall) {
        if ($cable.Count -and @($cable | Where-Object { $_.ConfigManagerErrorCode -ne 14 }).Count) {
            throw 'VB-CABLE removal could not be verified. Close audio apps, restart Windows and retry its vendor uninstaller.'
        }
        Write-InstallLog 'VB-CABLE removal verified or Windows reports restart pending. Restart required.'
        if ($StateFile -and (Test-Path -LiteralPath $StateFile)) { Remove-Item -LiteralPath $StateFile -Force }
        exit 3010
    }
    if (!$cable.Count) { throw 'VB-CABLE was not detected after setup. Review the vendor installer and restart requirements.' }
    if ($StateFile) {
        # Only mark installations created by this setup, never pre-existing ones.
        [IO.File]::WriteAllText($StateFile, 'Installed by A2Router setup; shared VB-CABLE driver.')
    }
    if (@($cable | Where-Object { $_.ConfigManagerErrorCode -notin @(0, 14) }).Count) {
        throw 'Windows reports a problem with the newly installed VB-CABLE device.'
    }
    Write-InstallLog 'VB-CABLE PnP device found. Windows restart required; audio playback has not been verified.'
    exit 3010
} catch {
    Write-InstallLog $_.Exception.Message
    Write-Error $_
    exit 1
}
