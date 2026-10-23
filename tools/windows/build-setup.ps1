param([string]$Compiler = '')
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path "$PSScriptRoot\..\..").ProviderPath
$dist = "$source\dist\windows-x64"
if (!(Test-Path "$dist\a2router.exe")) { throw 'Build the portable application first' }
if (!(Test-Path "$dist\vendor\vb-cable\VBCABLE_Setup_x64.exe")) { throw 'The verified VB-CABLE payload is missing' }
if (!$Compiler) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $Compiler = $command.Source }
    else {
        $candidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
        )
        $Compiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
}
if (!$Compiler -or !(Test-Path -LiteralPath $Compiler)) { throw 'Install Inno Setup 6.3+ or provide -Compiler PATH_TO_ISCC' }
$signature = Get-AuthenticodeSignature "$dist\vendor\vb-cable\VBCABLE_Setup_x64.exe"
if ($signature.Status -ne 'Valid') { throw "VB-CABLE installer signature verification failed: $($signature.Status)" }
$out = "$source\dist\setup"
New-Item -ItemType Directory -Force $out | Out-Null
& $Compiler "/DAppDist=$dist" "/DOutputDir=$out" "/DNoticeFile=$source\vendor\vbcable\NOTICE.txt" "$PSScriptRoot\setup.iss"
if ($LASTEXITCODE) { throw 'Windows setup compilation failed' }
Get-FileHash "$out\A2Router-Setup-x64.exe" -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLower())  A2Router-Setup-x64.exe" } | Set-Content "$out\SHA256SUMS.txt" -Encoding ascii
Write-Host "Setup created: $out\A2Router-Setup-x64.exe"
