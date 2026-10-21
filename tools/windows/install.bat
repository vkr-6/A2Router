@echo off
start "a2router guest setup" powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\OEM\bootstrap.ps1
exit /b 0
