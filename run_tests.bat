@echo off
call "%~dp0scripts\run_tests.bat" %*
exit /b %errorlevel%
