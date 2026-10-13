@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0.."
chcp 65001 >nul
cd /d "%APP_ROOT%\"

title JARVIS Kurulum
set "LOG=%APP_ROOT%\kurulum.log"
set "NEWVENV=%APP_ROOT%\.venv_install"
set "VENV=%APP_ROOT%\.venv"
set "OLDVENV=%APP_ROOT%\.venv_backup"

>"%LOG%" echo ===== JARVIS KURULUM LOGU =====
>>"%LOG%" echo Tarih: %date% %time%
>>"%LOG%" echo Klasor: %cd%

echo.
echo ========================================
echo          JARVIS KURULUM
echo ========================================
echo.

echo Jarvis aciksa once kapat. Ayarlarin ve anahtarlarin korunacak.
echo Internetten paket ve model indirilecek; ilk kurulum uzun surebilir.
echo [1/8] Python kontrol ediliyor...
set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD goto python_yok

%PY_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >>"%LOG%" 2>&1
if errorlevel 1 goto python_eski
for /f "delims=" %%V in ('%PY_CMD% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%V"
echo       OK - Python %PYVER%
>>"%LOG%" echo Python: %PYVER%

echo [2/8] Temiz sanal ortam hazirlaniyor...
if exist "%NEWVENV%" rmdir /s /q "%NEWVENV%" >>"%LOG%" 2>&1
%PY_CMD% -m venv "%NEWVENV%" >>"%LOG%" 2>&1
if errorlevel 1 goto hata_venv
if not exist "%NEWVENV%\Scripts\python.exe" goto hata_venv
echo       OK

echo [3/8] pip hazirlaniyor...
"%NEWVENV%\Scripts\python.exe" -m pip install --upgrade pip >>"%LOG%" 2>&1
if errorlevel 1 goto hata_pip
echo       OK

echo [4/8] JARVIS, yerel ses, belge ve tarayici paketleri kuruluyor...
if not exist "%APP_ROOT%\requirements.lock.txt" goto hata_paket
if not exist "%APP_ROOT%\requirements-bundle.txt" goto hata_paket
"%NEWVENV%\Scripts\python.exe" -m pip install -r "%APP_ROOT%\requirements.lock.txt" -r "%APP_ROOT%\requirements-bundle.txt" >>"%LOG%" 2>&1
if errorlevel 1 goto hata_paket
"%NEWVENV%\Scripts\python.exe" -m pip check >>"%LOG%" 2>&1
if errorlevel 1 goto hata_paket
echo       OK

echo [5/8] Tarayici ajani icin Chromium hazirlaniyor...
"%NEWVENV%\Scripts\python.exe" -m playwright install chromium >>"%LOG%" 2>&1
if errorlevel 1 goto hata_ekler
echo       OK

echo [6/8] Hey Jarvis ve yerel Turkce ses modelleri hazirlaniyor...
echo       Ilk indirme uzun surebilir. Internet ve bos disk alani gerektirir.
"%NEWVENV%\Scripts\python.exe" -X utf8 "%APP_ROOT%\scripts\kurulum_ekleri.py" models >>"%LOG%" 2>&1
if errorlevel 1 goto hata_ekler
echo       OK

echo [7/8] Kurulum dogrulaniyor...
"%NEWVENV%\Scripts\python.exe" -c "from google import genai; import speech_recognition, sounddevice, psutil, pypdf, docx, openpyxl, reportlab, requests, PIL, numpy, faster_whisper, markitdown; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); from pathlib import Path; assert Path(p.chromium.executable_path).is_file(); p.stop(); print('core and bundled imports OK')" >>"%LOG%" 2>&1
if errorlevel 1 goto hata_dogrulama

echo [8/8] Dogrulanan ortam devreye aliniyor...
rem Yeni ortam tamamen dogrulanmadan mevcut calisan .venv'e dokunulmaz.
if exist "%OLDVENV%" if not exist "%VENV%" (
    move "%OLDVENV%" "%VENV%" >>"%LOG%" 2>&1
    if errorlevel 1 goto hata_degistir
)
if exist "%OLDVENV%" rmdir /s /q "%OLDVENV%" >>"%LOG%" 2>&1
if exist "%OLDVENV%" goto hata_degistir
if exist "%VENV%" (
    move "%VENV%" "%OLDVENV%" >>"%LOG%" 2>&1
    if errorlevel 1 goto hata_degistir
)
move "%NEWVENV%" "%VENV%" >>"%LOG%" 2>&1
if errorlevel 1 goto hata_degistir
"%VENV%\Scripts\python.exe" -X utf8 "%APP_ROOT%\scripts\kurulum_ekleri.py" report >>"%LOG%" 2>&1
if errorlevel 1 goto hata_rapor
rem Onceki ortam .venv_backup altinda geri donus icin korunur.
"%VENV%\Scripts\python.exe" -X utf8 "%APP_ROOT%\scripts\kurulum_temizligi.py" >>"%LOG%" 2>&1
if errorlevel 1 echo UYARI: Temizlik tamamlanamadi. kurulum.log dosyasina bak.

echo       OK
echo.
echo ========================================
echo      JARVIS KURULUMU TAMAMLANDI
echo ========================================
echo.
echo Baslatmak icin baslat.bat dosyasina cift tikla.
echo Kurulum kaydi: kurulum.log
>>"%LOG%" echo KURULUM BASARILI
pause
exit /b 0

:python_yok
echo.
echo HATA: Python bulunamadi.
echo Python 3.10 veya daha yeni bir surum kur ve kurulumda
echo "Add python.exe to PATH" secenegini isaretle.
goto hata_son

:python_eski
echo.
echo HATA: Python 3.10 veya daha yeni bir surum gerekli.
goto hata_son

:hata_venv
echo.
echo HATA: Temiz sanal ortam olusturulamadi.
goto hata_son

:hata_pip
echo.
echo HATA: pip hazirlanamadi.
goto hata_son

:hata_paket
echo.
echo HATA: JARVIS paketlerinden biri kurulamadi.
echo Ayrinti kurulum.log dosyasinda.
goto hata_son

:hata_ekler
echo.
echo HATA: Tarayici veya ses modeli hazirlanamadi. Eski ortam korunuyor.
echo Interneti ve bos disk alanini kontrol et. Ayrinti kurulum.log dosyasinda.
goto hata_son

:hata_rapor
echo.
echo HATA: Yeni ortam raporu yazilamadi; eski ortama geri donuluyor.
if exist "%VENV%" move "%VENV%" "%NEWVENV%" >>"%LOG%" 2>&1
if exist "%OLDVENV%" if not exist "%VENV%" move "%OLDVENV%" "%VENV%" >>"%LOG%" 2>&1
goto hata_son

:hata_dogrulama
echo.
echo HATA: Paket kurulumu tamamlandi ancak cekirdek modullerden biri eksik.
echo Ayrinti kurulum.log dosyasinda.
goto hata_son

:hata_degistir
echo.
echo HATA: Yeni sanal ortam devreye alinamadi.
echo JARVIS veya Python aciksa kapatip tekrar dene.
if exist "%OLDVENV%" if not exist "%VENV%" move "%OLDVENV%" "%VENV%" >>"%LOG%" 2>&1
goto hata_son

:hata_son
>>"%LOG%" echo KURULUM BASARISIZ - %date% %time%
echo.
echo Calisan eski .venv varsa korunmustur.
echo Log dosyasi: %LOG%
echo.
pause
exit /b 1
