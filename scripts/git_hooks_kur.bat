@echo off
setlocal
cd /d "%~dp0.."
py -3.13 -X utf8 scripts\install_git_hooks.py
if errorlevel 1 exit /b %errorlevel%
endlocal
