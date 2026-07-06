@echo off
title IHC Logbook Server
cd /d "%~dp0"
call venv\Scripts\activate
set FLASK_DEBUG=0
python start_server.py
pause
