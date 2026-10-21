# Guest-only test command runner. Requests/results live in the project's ignored build directory.
$root = '\\host.lan\Data\build\windows-vm'
while ($true) {
    if (Test-Path "$root\request.txt") {
        $request = Get-Content "$root\request.txt" -Raw
        Remove-Item "$root\request.txt" -Force
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\command.ps1" *> "$root\results\command.log"
            @{ request=$request.Trim(); exit_code=$LASTEXITCODE; completed=(Get-Date).ToString('o') } | ConvertTo-Json | Set-Content "$root\results\result.json"
        } catch {
            $_ | Out-String | Set-Content "$root\results\agent-error.txt"
        }
    }
    Start-Sleep -Seconds 2
}
