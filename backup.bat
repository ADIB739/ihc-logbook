@echo off
REM IHC Engineering Logbook — Daily Database Backup
REM Schedule this with Windows Task Scheduler to run once per day.

set BACKUP_DIR=backups
set DB_FILE=instance\logbook.db

REM Create backup filename with date (YYYY-MM-DD)
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set dt=%%I
set DATESTAMP=%dt:~0,4%-%dt:~4,2%-%dt:~6,2%

set DEST=%BACKUP_DIR%\logbook_%DATESTAMP%.db

if not exist %BACKUP_DIR% mkdir %BACKUP_DIR%
copy /Y %DB_FILE% %DEST%

echo Backup saved: %DEST%

REM Keep only the last 30 backups (delete older ones)
forfiles /p %BACKUP_DIR% /m logbook_*.db /d -30 /c "cmd /c del @path" 2>nul

echo Done.
