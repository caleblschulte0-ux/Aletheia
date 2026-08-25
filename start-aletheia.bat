@echo off
REM Double-click to start Aletheia after the first setup.
cd /d "%~dp0"
git pull --ff-only
start "" http://127.0.0.1:8777/command.html
py -m aletheia.core || python -m aletheia.core
pause
