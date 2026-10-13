@echo off
setlocal
echo Jarvis video araclari kurulumu - FFmpeg ve FFprobe
echo Bu adim istege baglidir. Jarvis'i once kapatin.
where winget >nul 2>&1
if errorlevel 1 (
  echo WinGet bulunamadi. Microsoft App Installer gereklidir.
  echo Alternatif: ffmpeg.org/download.html uzerinden Windows araclarini kurun.
  pause
  exit /b 1
)
echo Gyan.FFmpeg paketi winget kaynagindan kullanici kapsaminda kurulacak.
choice /C EH /N /M "Kurulsun mu? E=Evet H=Hayir: "
if errorlevel 2 exit /b 0
winget install --id Gyan.FFmpeg --exact --source winget --scope user
if errorlevel 1 (
  echo Kurulum tamamlanamadi. Yukaridaki WinGet mesajini kontrol edin.
  pause
  exit /b 1
)
echo Kurulum adimi tamamlandi. Yeni terminal veya Jarvis acilisi PATH'i yeniler.
echo Jarvis'i yeniden acip video araclarini kontrol et yazin.
pause
exit /b 0
