param([string]$Source = '\\host.lan\Data', [string]$Workspace = 'C:\a2router-test')
$ErrorActionPreference = 'Stop'
$python = 'C:\a2router-tools\Python\python.exe'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:A2ROUTER_WASAPI_NATIVE = '1'
$computer = Get-CimInstance Win32_ComputerSystem
if ($computer.Manufacturer -match 'QEMU|Bochs' -or $computer.Model -match 'QEMU|Standard PC') {
    $env:A2ROUTER_VM_AUDIO_TEST = '1'
}
# Copy only source; never import Linux executables/caches or the VM disk itself.
& robocopy $Source $Workspace /E /XD .git .venv build third_party __pycache__ .pytest_cache .ruff_cache '*.egg-info' /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw 'Source copy failed' }
Set-Location $Workspace
& $python -m pip install -e '.[test]'
if ($LASTEXITCODE) { throw 'Editable installation failed' }
$build = "$Workspace\build"
$cmake = 'C:\a2router-tools\Python\Scripts\cmake.exe'
& $cmake -S . -B $build -G 'Visual Studio 17 2022' -A x64
if ($LASTEXITCODE) { throw 'CMake configure failed' }
& $cmake --build $build --config Release --parallel 2
if ($LASTEXITCODE) { throw 'Native build failed' }
& 'C:\a2router-tools\Python\Scripts\ctest.exe' --test-dir $build -C Release --output-on-failure
if ($LASTEXITCODE) { throw 'Native tests failed' }
& $python -m pytest -q
if ($LASTEXITCODE) { throw 'Python tests failed' }
& $python -m a2router diagnostics
if ($LASTEXITCODE) { throw 'WASAPI diagnostics failed' }
New-Item -ItemType Directory -Force "$Source\build\windows-vm\artifacts" | Out-Null
Copy-Item "$build\a2router_wasapi.dll" "$Source\build\windows-vm\artifacts\a2router_wasapi.dll" -Force
