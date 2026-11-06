@echo off
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m src.monitor.miniprogram_reader --no-cache > "work\miniprogram_scan.json" 2> "work\miniprogram_scan.err"
exit /b %ERRORLEVEL%
