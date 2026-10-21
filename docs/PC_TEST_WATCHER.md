# Actions olmadan gerçek Windows PC kabul izleyicisi

Bu düzen GitHub Actions kullanmadan, sürekli açık Windows PC'nin `gpt/*` dallarındaki yeni commitleri görüp gerçek Jarvis testlerini çalıştırması içindir.

## Ne yapar

`scripts\pc_test_watcher.bat` arka planda `scripts\pc_test_watcher.py` çalıştırır.

1. `origin` için `git fetch --prune` yapar.
2. En yeni değişmiş `origin/gpt/*` dalını seçer.
3. Ana çalışma klasörünün branch'ini değiştirmez; commit'i geçici bir `git worktree` içine açar.
4. Önce `python -X utf8 -m modules.validation` çalıştırır.
5. Bu yeşilse gerçek Windows kabulünü `python -X utf8 -m modules.acceptance_checks --desktop --news --skip-suite` ile çalıştırır.
6. Masaüstünde gerçek Hesap Makinesi kabulünü ve canlı `hedef son dakika haberleri` akışını dener. Haberde en az iki farklı yayıncıdan tarihli makale kanıtı gerekir; dosya istenmemişken writer çalışmamalıdır.
7. Haber hedefi tamamlandıktan sonra `devam` gönderir; aynı hedefin `done` kalmasını ve kalıcı hedef kaydının değişmemesini doğrular.
8. Sonucu `%LOCALAPPDATA%\Jarvis\pc-acceptance\pc_test_watcher_last.json` dosyasına yazar.
9. GitHub CLI (`gh`) kurulu, oturum açık ve dalın açık PR'ı varsa sonuç özetini otomatik PR yorumuna gönderir. Yorum yalnız commit, genel durum, validation, `calculator` ve `news_chat_resume` durumunu taşır; yerel yapılandırma/hesap ayrıntıları gönderilmez.
10. Aynı branch head'i tekrar test etmez; yeni commit gelirse yeniden test eder.

Canlı haber kabulü gerçek ağ ve mevcut model/sağlayıcı ayarlarını kullanır, bu yüzden sağlayıcı kotası harcayabilir. Hedef kaydı geçici ayrı bir kabul klasöründe tutulur; kullanıcının gerçek son hedefini değiştirmez. Kullanıcının `.jarvis` ayarları, anahtarları veya kişisel verileri Git'e yazılmaz. Geçici test worktree'si `%TEMP%\jarvis-pc-acceptance` altındadır ve test sonunda kaldırılır.

PR yorumu için `gh` yoksa, GitHub oturumu açık değilse veya dalın açık PR'ı bulunamazsa test kesilmez. Yerel JSON yine yazılır ve `github_pr_comment` alanında neden `skipped`/`failed` olduğu kaydedilir. `gh` kimlik doğrulama bilgisi veya token değeri rapora yazılmaz.

## İlk deneme

Önce masaüstüne ve canlı habere dokunmadan watcher'ın Git/ref/worktree kısmını kontrol et:

```bat
scripts\pc_test_watcher.bat --once --no-desktop
```

Sonra gerçek masaüstü + haber kabulünü bir kez çalıştır:

```bat
scripts\pc_test_watcher.bat --once
```

Belirli bir dalı tek turda sınamak için:

```bat
scripts\pc_test_watcher.bat --once --pattern refs/remotes/origin/gpt/windows-pc-watcher
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

## Sınırlar

- Canlı haber testi dış sitelere ve seçili sağlayıcının o andaki erişimine bağlıdır. Başarısızlık gerçek PC raporunda görünür; dış kaynak sorunu testten gizlenmez.
- PR yorumu yalnız `gh` kullanılabiliyorsa gönderilir; yorum gönderilememesi gerçek test sonucunu başarılı/başarısız olarak değiştirmez.
- Bir turda bir değişmiş `gpt/*` head'i test eder; birden fazla yeni head varsa sonraki döngülerde sırayla ele alınır. `--pattern` ile tek dal hedeflenebilir.
- `main` checkout edilmez veya değiştirilmez.

Haber kabulü üç geçersiz kararda durursa `news_chat_resume.detail` içindeki `decision_diagnostics` son üç kararın action/tool bilgisini, bilinen girdi alan adlarını ve maskelemiş kısa hata nedenlerini içerir. Ham girdi değerleri veya model yanıtları bu tanıya alınmaz. Bu çıktı kök nedeni ayırt etmek içindir; haber kabulü geçmedikçe çözüm tamamlanmış sayılmaz.
