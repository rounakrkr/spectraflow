@echo off
title SpectraFlow
cd /d "%~dp0"

:: Prefer this project's own venv, then a sibling venv, then system Python
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" main.py
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    "%~dp0..\.venv\Scripts\python.exe" main.py
) else (
    python main.py
)
if errorlevel 1 pause
