# Run by dockur's OEM install hook in the disposable guest, never on the host.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$tools = 'C:\a2router-tools'
New-Item -ItemType Directory -Force $tools | Out-Null
Start-Transcript -Path "$tools\bootstrap.log" -Append
$share = '\\host.lan\Data'
try {
    if (!(Test-Path "$tools\Python\python.exe")) {
        Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile "$tools\python-installer.exe"
        $p = Start-Process "$tools\python-installer.exe" -ArgumentList '/quiet', 'InstallAllUsers=1', "TargetDir=$tools\Python", 'Include_test=0', 'PrependPath=0' -Wait -PassThru
        if ($p.ExitCode -notin @(0,3010)) { throw "Python installation failed: $($p.ExitCode)" }
    }
    if (!(Test-Path "$tools\BuildTools\VC\Auxiliary\Build\vcvars64.bat")) {
        Invoke-WebRequest 'https://aka.ms/vs/17/release/vs_BuildTools.exe' -OutFile "$tools\vs_BuildTools.exe"
        $p = Start-Process "$tools\vs_BuildTools.exe" -ArgumentList '--quiet', '--wait', '--norestart', '--nocache', '--installPath', "$tools\BuildTools", '--add', 'Microsoft.VisualStudio.Workload.VCTools', '--includeRecommended' -Wait -PassThru
        if ($p.ExitCode -notin @(0,3010)) { throw "MSVC installation failed: $($p.ExitCode)" }
    }
    & "$tools\Python\python.exe" -m pip install PySide6-Essentials pytest cmake ninja
    if ($LASTEXITCODE) { throw 'Python dependencies failed' }
    Copy-Item C:\OEM\vm-agent.ps1 "$tools\vm-agent.ps1" -Force
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File $tools\vm-agent.ps1"
    Register-ScheduledTask -TaskName a2router-test-agent -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -User SYSTEM -RunLevel Highest -Force | Out-Null
    Start-ScheduledTask -TaskName a2router-test-agent
    if (Test-Path $share) {
        New-Item -ItemType Directory -Force "$share\build\windows-vm\results" | Out-Null
        'ready' | Set-Content "$share\build\windows-vm\results\bootstrap-ready.txt"
    }
} catch {
    $_ | Out-String | Set-Content "$tools\bootstrap-error.txt"
    if (Test-Path $share) { Copy-Item "$tools\bootstrap-error.txt" "$share\build\windows-vm\bootstrap-error.txt" -Force }
    throw
} finally {
    Stop-Transcript
    if (Test-Path $share) { Copy-Item "$tools\bootstrap.log" "$share\build\windows-vm\bootstrap.log" -Force }
}
