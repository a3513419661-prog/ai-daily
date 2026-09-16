@echo off
rem Stop the local dashboard server started by serve.py.
setlocal
for /f "tokens=2 delims=," %%p in ('tasklist /fi "imagename eq pythonw.exe" /fo csv /nh') do (
  wmic process where "ProcessId=%%~p" get CommandLine 2>nul | findstr /i "serve.py" >nul && taskkill /f /pid %%~p >nul
)
echo Dashboard server stopped.
