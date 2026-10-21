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
set "DESKTOP=%USERPROFILE%\Desktop"
set "DESKTOP_STARTER=%DESKTOP%\Jarvis-PC-Test-Watcher.cmd"
set "REPO_STARTER=%ROOT%\Jarvis-PC-Test-Watcher.cmd"
set "GH=gh.exe"

if not exist "%WATCHER%" (
  echo HATA: Watcher bulunamadi: %WATCHER%
  exit /b 1
)

where gh.exe >nul 2>nul
if errorlevel 1 (
  if exist "%ProgramFiles%\GitHub CLI\gh.exe" (
    set "GH=%ProgramFiles%\GitHub CLI\gh.exe"
  ) else (
    echo UYARI: GitHub CLI ^(gh^) bulunamadi. Testler calisir ama PR yorumu gonderilmez.
    goto gh_done
  )
)
"%GH%" auth status >nul 2>nul
if errorlevel 1 echo UYARI: gh oturumu acik degil. Testler calisir ama PR yorumu gonderilmez.
:gh_done

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
if errorlevel 1 goto desktop_fallback

>"%STARTER%" echo @echo off
>>"%STARTER%" echo cd /d "%ROOT%"
>>"%STARTER%" echo call "%WATCHER%"
if errorlevel 1 goto desktop_fallback

echo Kuruldu: kullanici Startup klasoru
echo Baslatici: %STARTER%
echo Windows oturumu acildiginda watcher otomatik baslayacak.
echo Sonuc: %%LOCALAPPDATA%%\Jarvis\pc-acceptance\pc_test_watcher_last.json
start "Jarvis PC Acceptance Watcher" /min "%STARTER%"
echo Ilk watcher calistirmasi baslatildi.
exit /b 0

:desktop_fallback
echo BILGI: Otomatik baslatma yollari engelli; masaustune tek tik baslatici yaziliyor.
if exist "%DESKTOP%" (
  >"%DESKTOP_STARTER%" echo @echo off
  >>"%DESKTOP_STARTER%" echo cd /d "%ROOT%"
  >>"%DESKTOP_STARTER%" echo call "%WATCHER%"
  if not errorlevel 1 (
    echo Kuruldu: masaustu tek tik baslaticisi
    echo Baslatici: %DESKTOP_STARTER%
    echo Bu PC otomatik baslangici engelliyor; Windows oturumu acildiktan sonra bu dosyayi bir kez ac.
    echo Sonuc: %%LOCALAPPDATA%%\Jarvis\pc-acceptance\pc_test_watcher_last.json
    start "Jarvis PC Acceptance Watcher" /min "%DESKTOP_STARTER%"
    echo Ilk watcher calistirmasi baslatildi.
    exit /b 0
  )
)

echo BILGI: Masaustu kokune yazma engelli; baslatici repo klasorune yaziliyor.
>"%REPO_STARTER%" echo @echo off
>>"%REPO_STARTER%" echo cd /d "%ROOT%"
>>"%REPO_STARTER%" echo call "%WATCHER%"
if errorlevel 1 (
  echo HATA: Repo baslaticisi yazilamadi: %REPO_STARTER%
  exit /b 1
)

echo Kuruldu: repo icinde tek tik baslaticisi
echo Baslatici: %REPO_STARTER%
echo Bu PC otomatik baslangici engelliyor; Windows oturumu acildiktan sonra bu dosyayi bir kez ac.
echo Sonuc: %%LOCALAPPDATA%%\Jarvis\pc-acceptance\pc_test_watcher_last.json
start "Jarvis PC Acceptance Watcher" /min "%REPO_STARTER%"
echo Ilk watcher calistirmasi baslatildi.
exit /b 0
