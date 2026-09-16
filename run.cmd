@echo off
rem Daily AI hotspot collector - used by Task Scheduler or double-click.
rem usage: run.cmd              scrape + rebuild page
rem        run.cmd --open       scrape then open the page
rem        run.cmd --render     rebuild page only, no network
setlocal
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist "data" mkdir "data"

set PY_EXE=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY_EXE%" set PY_EXE=py

"%PY_EXE%" collect.py %* >> "data\run-history.log" 2>&1
exit /b %errorlevel%
