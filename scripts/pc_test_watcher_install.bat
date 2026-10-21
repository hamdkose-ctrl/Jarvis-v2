@echo off
setlocal
cd /d "%~dp0.."

set "TASK=Jarvis PC Acceptance Watcher"
set "ROOT=%CD%"
set "WATCHER=%ROOT%\scripts\pc_test_watcher.bat"
set "AUTODIR=%LOCALAPPDATA%\Jarvis\pc-acceptance"
set "AUTOSTART=%AUTODIR%\pc_test_watcher_start.cmd"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTER=%STARTUP%\Jarvis-PC-Acceptance-Watcher.cmd"

if not exist "%WATCHER%" (
  echo HATA: Watcher bulunamadi: %WATCHER%
  exit /b 1
)

where gh.exe >nul 2>nul
if errorlevel 1 (
  echo UYARI: GitHub CLI ^(gh^) bulunamadi. Testler calisir ama PR yorumu gonderilmez.
) else (
  gh auth status >nul 2>nul
  if errorlevel 1 echo UYARI: gh oturumu acik degil. Testler calisir ama PR yorumu gonderilmez.
)

where schtasks.exe >nul 2>nul
if not errorlevel 1 (
  schtasks.exe /Create /TN "%TASK%" /SC ONLOGON /TR "\"%WATCHER%\"" /RL LIMITED /F /IT >nul 2>nul
  if not errorlevel 1 (
    echo Kuruldu: %TASK%
    echo Windows oturumu acikken watcher otomatik baslayacak.
    echo Sonuc: %%LOCALAPPDATA%%\Jarvis\pc-acceptance\pc_test_watcher_last.json
    schtasks.exe /Run /TN "%TASK%" >nul 2>nul
    if errorlevel 1 (
      echo UYARI: Gorev kaydedildi ama ilk calistirma baslatilamadi. Sonraki oturum acilisinda yeniden denenecek.
      exit /b 0
    )
    echo Ilk watcher calistirmasi baslatildi.
    exit /b 0
  )
)

echo BILGI: Gorev Zamanlayici bu hesapta kullanilamiyor; kullanici Run kaydina geciliyor.
if not exist "%AUTODIR%" mkdir "%AUTODIR%" >nul 2>nul
if errorlevel 1 goto startup_fallback

>"%AUTOSTART%" echo @echo off
>>"%AUTOSTART%" echo cd /d "%ROOT%"
>>"%AUTOSTART%" echo call "%WATCHER%"
if errorlevel 1 goto startup_fallback

powershell.exe -NoProfile -NonInteractive -Command "$p='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'; New-ItemProperty -Path $p -Name 'Jarvis PC Acceptance Watcher' -Value ('cmd.exe /d /c ""' + '%AUTOSTART%' + '""') -PropertyType String -Force ^| Out-Null" >nul 2>nul
if not errorlevel 1 (
  echo Kuruldu: kullanici Run kaydi
  echo Windows oturumu acildiginda watcher otomatik baslayacak.
  echo Sonuc: %%LOCALAPPDATA%%\Jarvis\pc-acceptance\pc_test_watcher_last.json
  start "Jarvis PC Acceptance Watcher" /min "%AUTOSTART%"
  echo Ilk watcher calistirmasi baslatildi.
  exit /b 0
)

:startup_fallback
echo BILGI: Run kaydi kullanilamiyor; kullanici Startup klasorune geciliyor.
if not exist "%STARTUP%" mkdir "%STARTUP%" >nul 2>nul
if errorlevel 1 (
  echo HATA: Otomatik baslatma kurulamadı. Gorev Zamanlayici, HKCU Run ve Startup erisimi engelli.
  exit /b 1
)

>"%STARTER%" echo @echo off
>>"%STARTER%" echo cd /d "%ROOT%"
>>"%STARTER%" echo call "%WATCHER%"
if errorlevel 1 (
  echo HATA: Startup baslaticisi yazilamadi: %STARTER%
  exit /b 1
)

echo Kuruldu: kullanici Startup klasoru
echo Baslatici: %STARTER%
echo Windows oturumu acildiginda watcher otomatik baslayacak.
echo Sonuc: %%LOCALAPPDATA%%\Jarvis\pc-acceptance\pc_test_watcher_last.json
start "Jarvis PC Acceptance Watcher" /min "%STARTER%"
echo Ilk watcher calistirmasi baslatildi.
exit /b 0
