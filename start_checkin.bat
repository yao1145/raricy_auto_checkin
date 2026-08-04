@echo off
title Raricy Check-in Launcher
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Please install Python and add it to PATH, then retry.
    pause
    exit /b 1
)
"%PY%" launcher.py
if errorlevel 1 pause
exit /b 0
