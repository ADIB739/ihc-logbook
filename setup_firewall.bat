@echo off
title IHC Logbook — Firewall Setup (run as Administrator)
echo.
echo This adds a Windows Firewall rule to allow workers to connect
echo to the IHC Logbook server on port 5000.
echo.

netsh advfirewall firewall add rule ^
  name="IHC Logbook Server" ^
  dir=in ^
  action=allow ^
  protocol=TCP ^
  localport=5000 ^
  profile=private

echo.
echo Done. Workers on the same Wi-Fi can now reach the server.
echo You only need to run this once.
pause
