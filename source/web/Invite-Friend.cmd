@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.create_visit_invite
pause
