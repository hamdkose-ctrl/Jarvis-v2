@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0.."
chcp 65001 >nul
cd /d "%APP_ROOT%\"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" goto kurulum_gerekli

rem Kurtarma once calisir; bekleyen aday ortam yerinde onarilmaz.
"%PY%" launcher.py --check-installation
if errorlevel 2 goto kurulum_gerekli
if errorlevel 1 exit /b 1
"%PY%" launcher.py
set "JARVIS_EXIT=%errorlevel%"
if not "%JARVIS_EXIT%"=="0" pause
exit /b %JARVIS_EXIT%

:kurulum_gerekli
echo.
echo JARVIS sanal ortami eksik veya bozuk.
echo Kurulum otomatik olarak onarilacak...
echo.
call "%APP_ROOT%\kurulum.bat"
if errorlevel 1 (
    echo.
    echo Kurulum tamamlanamadi. kurulum.log dosyasini kontrol et.
    pause
    exit /b 1
)
if not exist "%PY%" (
    echo HATA: Kurulum sonrasi Python ortami bulunamadi.
    pause
    exit /b 1
)
"%PY%" launcher.py --check-installation
if errorlevel 1 exit /b 1
"%PY%" launcher.py
set "JARVIS_EXIT=%errorlevel%"
if not "%JARVIS_EXIT%"=="0" pause
exit /b %JARVIS_EXIT%
