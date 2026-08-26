@echo off
REM Double-click to start Aletheia after the first setup.
REM The supervisor keeps the Core alive: crash -> relaunch, merged code
REM update -> restart onto it. Close this window (or Ctrl+C) to stop.
REM For always-on with no window:  py -m aletheia.supervisor install
cd /d "%~dp0"
git pull --ff-only
start "" http://127.0.0.1:8777/
py -m aletheia.supervisor || python -m aletheia.supervisor
pause
