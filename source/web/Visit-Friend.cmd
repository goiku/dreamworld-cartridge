@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.visit_friend %*
pause
