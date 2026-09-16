@echo off
rem Start the local dashboard server (hidden console when launched by Task Scheduler).
rem usage: start-server.cmd          listen on 0.0.0.0:8765
rem        start-server.cmd --port 9000
setlocal
cd /d "%~dp0"

set PY_EXE=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY_EXE%" set PY_EXE=py

"%PY_EXE%" serve.py %*
