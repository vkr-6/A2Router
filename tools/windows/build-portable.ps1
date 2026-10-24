param(
    [string]$Workspace = "$env:LOCALAPPDATA\a2router-build",
    [string]$ToolchainRoot = '',
    [switch]$SkipTests,
    [switch]$Headless
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$source = (Resolve-Path "$PSScriptRoot\..\..").ProviderPath
New-Item -ItemType Directory -Force $Workspace | Out-Null
# Work on a task-owned local copy; UNC workdirs can break native build tools.
foreach ($folder in @('a2router', 'src', 'tests', 'tools', 'vendor')) {
    & robocopy "$source\$folder" "$Workspace\$folder" /E /R:2 /W:1 /XD __pycache__ .pytest_cache .ruff_cache /NFL /NDL /NJH /NJS
    if ($LASTEXITCODE -ge 8) { throw "Copy failed: $folder" }
}
foreach ($file in @('CMakeLists.txt','pyproject.toml','README.md','THIRD_PARTY_NOTICES.md','LICENSE','LICENSING.md')) { Copy-Item "$source\$file" "$Workspace\$file" -Force }
$python = "$Workspace\venv\Scripts\python.exe"
if (!(Test-Path $python)) {
    & py -3.12 -m venv "$Workspace\venv"
    if ($LASTEXITCODE) { throw 'Cannot create Windows Python environment' }
}
$wheelCache = "$source\build\windows-tools\wheels"
if (Test-Path "$wheelCache\*.whl") {
    & $python -m pip install --no-index --find-links $wheelCache -e "${Workspace}[test,build]"
} else {
    & $python -m pip install -e "${Workspace}[test,build]"
}
if ($LASTEXITCODE) { throw 'Windows build dependencies failed' }
$env:PATH = "$Workspace\venv\Scripts;$env:PATH"
if ($ToolchainRoot) {
    # Copy the compiler/SDK to NTFS: Windows header lookup must be case-insensitive.
    # Only build tools and x64 SDK files are needed; no installer/registry changes.
    $localTools = "$Workspace\toolchain"
    $sourceMsvc = Get-ChildItem "$ToolchainRoot\VC\Tools\MSVC" -Directory | Sort-Object Name -Descending | Select-Object -First 1
    $sourceSdk = "$ToolchainRoot\Windows Kits\10"
    $sdkVersion = (Get-ChildItem "$sourceSdk\Include" -Directory | Sort-Object Name -Descending | Select-Object -First 1).Name
    $copies = @(
        @("$($sourceMsvc.FullName)", "$localTools\VC\Tools\MSVC\$($sourceMsvc.Name)"),
        @("$sourceSdk\Include\$sdkVersion", "$localTools\Windows Kits\10\Include\$sdkVersion"),
        @("$sourceSdk\Lib\$sdkVersion\ucrt\x64", "$localTools\Windows Kits\10\Lib\$sdkVersion\ucrt\x64"),
        @("$sourceSdk\Lib\$sdkVersion\um\x64", "$localTools\Windows Kits\10\Lib\$sdkVersion\um\x64"),
        @("$sourceSdk\bin\$sdkVersion\x64", "$localTools\Windows Kits\10\bin\$sdkVersion\x64")
    )
    foreach ($pair in $copies) {
        & robocopy $pair[0] $pair[1] /E /R:2 /W:1 /NFL /NDL /NJH /NJS
        if ($LASTEXITCODE -ge 8) { throw "Toolchain copy failed: $($pair[0])" }
    }
    $ToolchainRoot = $localTools
    $msvc = Get-ChildItem "$ToolchainRoot\VC\Tools\MSVC" -Directory | Sort-Object Name -Descending | Select-Object -First 1
    $sdk = "$ToolchainRoot\Windows Kits\10"
    $version = (Get-ChildItem "$sdk\Include" -Directory | Sort-Object Name -Descending | Select-Object -First 1).Name
    if (!$msvc -or !$version) { throw 'Portable MSVC/SDK layout is incomplete' }
    $env:PATH = "$($msvc.FullName)\bin\Hostx64\x64;$sdk\bin\$version\x64;$env:PATH"
    $env:INCLUDE = "$($msvc.FullName)\include;$sdk\Include\$version\ucrt;$sdk\Include\$version\shared;$sdk\Include\$version\um;$sdk\Include\$version\winrt"
    $env:LIB = "$($msvc.FullName)\lib\x64;$sdk\Lib\$version\ucrt\x64;$sdk\Lib\$version\um\x64"
} elseif (!(Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (!(Test-Path $vswhere)) { throw 'Run from a VS developer shell, or supply -ToolchainRoot' }
    $installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (!$installation) { throw 'No MSVC installation found' }
    $environment = & cmd.exe /c "`"$installation\VC\Auxiliary\Build\vcvars64.bat`" >nul && set"
    foreach ($line in $environment) {
        if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') }
    }
}
Set-Location $Workspace
$native = "$Workspace\build"
& "$Workspace\venv\Scripts\cmake.exe" -S . -B $native -G Ninja -DCMAKE_BUILD_TYPE=Release
if ($LASTEXITCODE) { throw 'Native configure failed' }
& "$Workspace\venv\Scripts\cmake.exe" --build $native --parallel 2
if ($LASTEXITCODE) { throw 'Native build failed' }
$env:A2ROUTER_WASAPI_DLL = "$native\a2router_wasapi.dll"
if (!$SkipTests) {
    $env:QT_QPA_PLATFORM = 'offscreen'
    if ($Headless) {
        # Hosted runners have no guaranteed audio service or hardware. Check
        # the real DLL ABI, but keep endpoint/playback tests opt-in elsewhere.
        & $python tools\windows\check_bridge.py "$native\a2router_wasapi.dll"
        if ($LASTEXITCODE) { throw 'Native bridge load/API check failed' }
        Remove-Item Env:\A2ROUTER_WASAPI_NATIVE -ErrorAction SilentlyContinue
        & "$Workspace\venv\Scripts\ctest.exe" --test-dir $native --output-on-failure -R '^native_core$'
    } else {
        $env:A2ROUTER_WASAPI_NATIVE = '1'
        & "$Workspace\venv\Scripts\ctest.exe" --test-dir $native --output-on-failure
    }
    if ($LASTEXITCODE) { throw 'Windows CTest failed' }
    & $python -m pytest -q
    if ($LASTEXITCODE) { throw 'Windows pytest failed' }
}
Remove-Item Env:\A2ROUTER_WASAPI_DLL -ErrorAction SilentlyContinue
if (Test-Path "$Workspace\dist") { Remove-Item "$Workspace\dist" -Recurse -Force }
New-Item -ItemType Directory -Force "$Workspace\dist" | Out-Null
& $python tools/windows/make_icon.py a2router/assets/a2router.svg "$Workspace/build/a2router.ico"
if ($LASTEXITCODE) { throw 'Application icon generation failed' }
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name a2router --icon "$Workspace/build/a2router.ico" --hidden-import PySide6.QtSvg --add-data "$Workspace/a2router/assets;a2router/assets" --paths $Workspace --add-binary "$native\a2router_wasapi.dll;." --distpath "$Workspace\dist" --workpath "$Workspace\build\pyinstaller" --specpath "$Workspace\build" tools\windows\portable_entry.py
if ($LASTEXITCODE) { throw 'Freezing the GUI application failed' }

if (!$SkipTests) {
    # These checks only enumerate endpoints; they never install drivers or play audio.
    $env:QT_QPA_PLATFORM = 'offscreen'
    $smokeArguments = '--self-test "' + $Workspace + '\dist\packaged-smoke.json"'
    if ($Headless) { $smokeArguments += ' --mock' }
    $p = Start-Process "$Workspace\dist\a2router.exe" -ArgumentList $smokeArguments -Wait -PassThru
    if ($p.ExitCode) { throw "Packaged GUI smoke check failed: $($p.ExitCode)" }
    if (!$Headless) {
        Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        $p = Start-Process "$Workspace\dist\a2router.exe" -ArgumentList ('--self-test "' + $Workspace + '\dist\packaged-desktop-smoke.json"') -Wait -PassThru
        if ($p.ExitCode) { throw "Packaged native desktop check failed: $($p.ExitCode)" }
    }
    Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
}
& $python "$source\tools\windows\prepare_vbcable.py" "$source\vendor\vbcable\VBCABLE_Driver_Pack45.zip" "$Workspace\dist\vendor\vb-cable"
if ($LASTEXITCODE) { throw 'VB-CABLE package verification failed' }
Copy-Item "$source\vendor\vbcable\NOTICE.txt" "$Workspace\dist\vendor\VB-CABLE-NOTICE.txt" -Force
Copy-Item "$source\tools\windows\install-vbcable.ps1" "$Workspace\dist\vendor\install-vbcable.ps1" -Force
& $python tools\windows\collect_licenses.py "$Workspace\dist"
if ($LASTEXITCODE) { throw 'Runtime license collection failed' }
Copy-Item "$source\tools\windows\PORTABLE.txt" "$Workspace\dist\README.txt" -Force
Copy-Item "$source\THIRD_PARTY_NOTICES.md" "$Workspace\dist\THIRD_PARTY_NOTICES.md" -Force
Copy-Item "$source\LICENSE" "$Workspace\dist\LICENSE" -Force
Copy-Item "$source\LICENSING.md" "$Workspace\dist\LICENSING.md" -Force
$out = "$source\dist\windows-x64"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item "$Workspace\dist\*" $out -Recurse -Force
Get-FileHash "$out\a2router.exe" -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($_.Path))" } | Set-Content "$out\SHA256SUMS.txt" -Encoding ascii
Compress-Archive -Path "$out\*" -DestinationPath "$source\dist\a2router-windows-x64.zip" -Force
Write-Host "Portable Windows artifacts: $out"
