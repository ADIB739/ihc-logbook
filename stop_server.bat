@echo off
title IHC Logbook — Stop Server
taskkill /F /IM pythonw.exe >nul 2>&1
if %errorlevel%==0 (
    echo Server stopped.
) else (
    echo Server was not running.
)
timeout /t 2 >nul
