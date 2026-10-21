param(
    [ValidateSet('Debug','Release')][string]$Configuration = 'Release',
    [ValidateSet('x64','ARM64')][string]$Platform = 'x64',
    [string]$CertificateThumbprint = '',
    [switch]$UseNuGet,
    [string]$NuGetPackageRoot = '',
    [string]$KitVersion = '10.0.26100.6584'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").ProviderPath
$source = "$root\drivers\windows\a2router"
$work = "$root\build\windows-driver\source"
New-Item -ItemType Directory -Force $work | Out-Null
& robocopy $source $work /E /XD .vs x64 ARM64 Debug Release /R:2 /W:1 /NFL /NDL /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw 'Driver source copy failed' }
if (!(Get-Command msbuild.exe -ErrorAction SilentlyContinue)) {
    throw 'Run in a Visual Studio developer shell with matching WDK + SDK installed'
}
if ($UseNuGet) {
    if (!(Get-Command nuget.exe -ErrorAction SilentlyContinue)) { throw 'Install NuGet CLI or use NuGet/setup-nuget in GitHub Actions' }
    if (!$NuGetPackageRoot) { $NuGetPackageRoot = "$root\build\windows-driver\packages" }
    New-Item -ItemType Directory -Force $NuGetPackageRoot | Out-Null
    $NuGetPackageRoot = (Resolve-Path $NuGetPackageRoot).ProviderPath
    $arch = $Platform.ToLowerInvariant()
    $ids = @("Microsoft.Windows.WDK.$arch", "Microsoft.Windows.SDK.CPP.$arch", 'Microsoft.Windows.SDK.CPP')
    foreach ($id in $ids) {
        & nuget.exe install $id -Version $KitVersion -OutputDirectory $NuGetPackageRoot -Source https://api.nuget.org/v3/index.json -NonInteractive -DirectDownload -NoCache
        if ($LASTEXITCODE) { throw "NuGet restore failed: $id $KitVersion" }
    }
    # MSBuild discovers this file for all projects below the task-owned source copy.
    $xml = [System.Xml.XmlDocument]::new()
    $project = $xml.CreateElement('Project')
    [void]$xml.AppendChild($project)
    foreach ($id in $ids) {
        $leaf = if ($id -eq 'Microsoft.Windows.SDK.CPP') { 'Microsoft.Windows.SDK.cpp.props' }
                elseif ($id -like 'Microsoft.Windows.SDK.CPP.*') { "Microsoft.Windows.SDK.cpp.$arch.props" }
                else { "Microsoft.Windows.WDK.$arch.props" }
        $props = "$NuGetPackageRoot\$id.$KitVersion\build\native\$leaf"
        if (!(Test-Path $props)) { throw "NuGet build properties missing: $props" }
        $import = $xml.CreateElement('Import')
        $import.SetAttribute('Project', $props)
        [void]$project.AppendChild($import)
    }
    $xml.Save("$work\Directory.Build.props")
}
# No deployment, boot-security changes, certificate import, or tests.
# Signing must occur after all local INF/source modifications.
$properties = @('/p:SignMode=Off')
if ($CertificateThumbprint) {
    $properties = @('/p:SignMode=TestSign', "/p:TestCertificate=$CertificateThumbprint")
}
Push-Location $work
try {
    & msbuild.exe SimpleAudioSample.sln /m "/p:Configuration=$Configuration" "/p:Platform=$Platform" @properties
    if ($LASTEXITCODE) { throw 'WDK driver build failed' }
    $package = "$root\build\windows-driver\package"
    New-Item -ItemType Directory -Force $package | Out-Null
    foreach ($name in @('A2RouterAudio.inf','A2RouterAudio.sys','A2RouterAudio.cat')) {
        $file = Get-ChildItem $work -Filter $name -Recurse | Where-Object { $_.FullName -match [regex]::Escape($Platform) } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (!$file) { throw "Build did not produce $name; inspect WDK build output" }
        Copy-Item $file.FullName "$package\$name" -Force
    }
    Copy-Item "$source\LICENSE-Microsoft.txt" $package -Force
    Write-Host "Driver package: $package"
    Write-Host 'UNTESTED. An unsigned package cannot load on a normal Windows installation.'
    Write-Host 'Production use requires Microsoft-accepted signing. No certificate or boot policy was changed.'
} finally { Pop-Location }
