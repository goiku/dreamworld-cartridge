@echo off
setlocal
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0static\melonds-tuck-in.py"
) else (
    py -3 "%~dp0static\melonds-tuck-in.py"
    if errorlevel 1 pause
)
