@echo off
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 scripts\pc_test_loop.py %*
) else (
  python -X utf8 scripts\pc_test_loop.py %*
)
