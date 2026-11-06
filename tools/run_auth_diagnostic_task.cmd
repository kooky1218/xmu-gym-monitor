@echo off
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
".venv\Scripts\python.exe" -m tools.run_auth_diagnostic --scenario D --target-date 2026-11-03 --output "logs\auth_diagnostic.jsonl"
exit /b %ERRORLEVEL%
