@echo off
title SpectraFlow
cd /d "%~dp0"

:: Try local venv first, then system python
if exist "%~dp0..\.venv\Scripts\python.exe" (
    "%~dp0..\.venv\Scripts\python.exe" main.py
) else if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" main.py
) else (
    python main.py
)
pause
