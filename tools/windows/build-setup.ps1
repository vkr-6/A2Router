param(
    [string]$PortableDirectory = '',
    [string]$Compiler = ''
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (!$PortableDirectory) { $PortableDirectory = Join-Path $source 'dist\windows-x64' }
$PortableDirectory = (Resolve-Path -LiteralPath $PortableDirectory).Path
foreach ($name in @('a2router.exe', 'a2router.ico', 'vendor\vb-cable\VBCABLE_Setup_x64.exe', 'vendor\install-vbcable.ps1', 'LICENSE', 'LICENSING.md')) {
    if (!(Test-Path -LiteralPath (Join-Path $PortableDirectory $name))) { throw "Portable payload missing $name; build it first" }
}
if (!$Compiler) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { $Compiler = $candidate; break }
    }
    if (!$Compiler) {
        $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($command) { $Compiler = $command.Source }
    }
}
if (!$Compiler -or !(Test-Path -LiteralPath $Compiler)) { throw 'Inno Setup 6 compiler unavailable; supply -Compiler. This script never installs tools.' }
$output = Join-Path $source 'dist'
& $Compiler "/DSourceRoot=$source" "/DPortableRoot=$PortableDirectory" "/O$output" (Join-Path $PSScriptRoot 'setup.iss')
if ($LASTEXITCODE) { throw 'Setup compilation failed' }
$artifact = Join-Path $output 'a2router-windows-x64-setup.exe'
if (!(Test-Path -LiteralPath $artifact)) { throw 'Setup EXE was not generated' }
Get-FileHash -LiteralPath $artifact -Algorithm SHA256 | ForEach-Object {
    "$($_.Hash.ToLower())  $([IO.Path]::GetFileName($_.Path))"
} | Set-Content (Join-Path $output 'a2router-windows-x64-setup.exe.sha256') -Encoding ascii
Write-Host "Setup artifact: $artifact (not executed)"
