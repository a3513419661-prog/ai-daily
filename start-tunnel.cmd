@echo off
rem Start the public tunnel (quick tunnel, no account needed).
rem usage: start-tunnel.cmd          keep running in this window
setlocal
cd /d "%~dp0"

set PY_EXE=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY_EXE%" set PY_EXE=py

"%PY_EXE%" tunnel.py
