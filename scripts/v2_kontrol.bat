@echo off
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 -m modules.acceptance_checks %*
) else (
  python -X utf8 -m modules.acceptance_checks %*
)
pause
