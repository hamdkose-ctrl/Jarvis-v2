@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0.."
cd /d "%APP_ROOT%\"
set "PY=.venv\Scripts\python.exe"
if not "%~1"=="" set "PY=%~1"
if not exist "%PY%" (
  echo Python ortami bulunamadi. Once kurulum.bat calistir.
  pause
  exit /b 1
)
"%PY%" -X utf8 -m modules.validation
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" goto son
rem Guvenli baslangic kontrolu: yalniz bagimlilik importu; kurtarma, temizlik, mikrofon ve servis yok.
echo.
echo Baslangic kontrolu: bagimliliklar yukleniyor...
"%PY%" -X utf8 -c "import launcher; exec(launcher.DEPENDENCY_IMPORTS)"
if errorlevel 1 (
  echo Baslangic kontrolu BASARISIZ. kurulum.bat calistir.
  set "RESULT=2"
) else (
  echo Baslangic kontrolu basarili.
)
:son
if "%~1"=="" pause
exit /b %RESULT%
