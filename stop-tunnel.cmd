@echo off
rem Stop the tunnel process (both the python wrapper and cloudflared).
setlocal
taskkill /f /im cloudflared.exe >nul 2>&1
for /f "tokens=2 delims=," %%p in ('tasklist /fi "imagename eq pythonw.exe" /fo csv /nh') do (
  wmic process where "ProcessId=%%~p" get CommandLine 2>nul | findstr /i "tunnel.py" >nul && taskkill /f /pid %%~p >nul
)
echo Tunnel stopped.
