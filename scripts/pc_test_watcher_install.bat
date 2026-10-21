@echo off
setlocal
cd /d "%~dp0.."

set "TASK=Jarvis PC Acceptance Watcher"
set "ROOT=%CD%"
set "WATCHER=%ROOT%\scripts\pc_test_watcher.bat"

if not exist "%WATCHER%" (
  echo HATA: Watcher bulunamadi: %WATCHER%
  exit /b 1
)

where schtasks.exe >nul 2>nul
if errorlevel 1 (
  echo HATA: Windows Gorev Zamanlayici araci bulunamadi.
  exit /b 1
)

where gh.exe >nul 2>nul
if errorlevel 1 (
  echo UYARI: GitHub CLI ^(gh^) bulunamadi. Testler calisir ama PR yorumu gonderilmez.
) else (
  gh auth status >nul 2>nul
  if errorlevel 1 echo UYARI: gh oturumu acik degil. Testler calisir ama PR yorumu gonderilmez.
)

schtasks.exe /Create /TN "%TASK%" /SC ONLOGON /TR "\"%WATCHER%\"" /RL LIMITED /F /IT >nul
if errorlevel 1 (
  echo HATA: Gorev olusturulamadi. Bu Windows hesabinda Gorev Zamanlayici izni kontrol edilmeli.
  exit /b 1
)

echo Kuruldu: %TASK%
echo Windows oturumu acikken watcher otomatik baslayacak.
echo Sonuc: %%LOCALAPPDATA%%\Jarvis\pc-acceptance\pc_test_watcher_last.json

schtasks.exe /Run /TN "%TASK%" >nul
if errorlevel 1 (
  echo UYARI: Gorev kaydedildi ama ilk calistirma baslatilamadi. Sonraki oturum acilisinda yeniden denenecek.
  exit /b 0
)

echo Ilk watcher calistirmasi baslatildi.
exit /b 0
