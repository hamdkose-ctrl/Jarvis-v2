# Actions olmadan gerçek Windows PC kabul izleyicisi

Bu düzen GitHub Actions kullanmadan, sürekli açık Windows PC'nin `gpt/*` dallarındaki yeni commitleri görüp gerçek Jarvis testlerini çalıştırması içindir.

## Ne yapar

`scripts\pc_test_watcher.bat` arka planda `scripts\pc_test_watcher.py` çalıştırır.

1. `origin` için `git fetch --prune` yapar.
2. En yeni değişmiş `origin/gpt/*` dalını seçer.
3. Ana çalışma klasörünün branch'ini değiştirmez; commit'i geçici bir `git worktree` içine açar.
4. Önce `python -X utf8 -m modules.validation` çalıştırır.
5. Bu yeşilse gerçek Windows masaüstü kabulünü `python -X utf8 -m modules.acceptance_checks --desktop --skip-suite` ile çalıştırır.
6. Sonucu `%LOCALAPPDATA%\Jarvis\pc-acceptance\pc_test_watcher_last.json` dosyasına yazar.
7. Aynı branch head'i tekrar test etmez; yeni commit gelirse yeniden test eder.

Kullanıcının `.jarvis` ayarları, anahtarları veya kişisel verileri Git'e yazılmaz. Geçici test worktree'si `%TEMP%\jarvis-pc-acceptance` altındadır ve test sonunda kaldırılır.

## İlk deneme

Önce masaüstüne dokunmadan watcher'ın Git/ref/worktree kısmını kontrol et:

```bat
scripts\pc_test_watcher.bat --once --no-desktop
```

Sonra gerçek masaüstü kabulünü bir kez çalıştır:

```bat
scripts\pc_test_watcher.bat --once
```

Sürekli izleme:

```bat
scripts\pc_test_watcher.bat
```

Varsayılan kontrol aralığı 30 saniyedir. Örnek 60 saniye:

```bat
scripts\pc_test_watcher.bat --interval 60
```

## Windows oturumu

Gerçek UI Automation / Calculator kabulü için watcher interaktif Windows oturumunda çalışmalıdır. Windows Görev Zamanlayıcı kullanılacaksa "Kullanıcı oturum açtığında çalıştır" biçimi tercih edilmelidir; kullanıcı oturumu olmayan servis oturumu masaüstü GUI kabulü için uygun değildir.

## Sınırlar — ilk sürüm

- İlk sürüm yalnız mevcut `modules.acceptance_checks --desktop` gerçek PC kabulünü otomatikleştirir; haber sohbeti için ayrı canlı kabul senaryosu henüz eklenmemiştir.
- PR yorumuna/check API'sine sonuç yazmaz; sonuç yerel JSON ve konsoldadır.
- Bir turda bir değişmiş `gpt/*` head'i test eder; birden fazla yeni head varsa sonraki döngülerde sırayla ele alınır.
- `main` checkout edilmez veya değiştirilmez.
