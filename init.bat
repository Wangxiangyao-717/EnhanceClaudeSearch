@echo off
echo Installing EnhanceClaudeSearch...
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0init.ps1" %*
pause
