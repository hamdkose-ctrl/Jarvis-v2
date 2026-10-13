@echo off
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (set "JARVIS_PY=.venv\Scripts\python.exe") else (set "JARVIS_PY=python")
"%JARVIS_PY%" -X utf8 scripts\tarayici_oturumu.py
if errorlevel 1 pause
