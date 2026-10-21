# Gerçek Windows PC kabul watcher'ı

Amaç: `gpt/*` dallarındaki yeni SHA'ları gerçek iş PC'sinde test etmek, başarısızlıkta GPT-5.6 Terra follow-up çalıştırmak ve yeni SHA'yı tekrar kabulden geçirmek.

Aşamalar:
1. `.venv\Scripts\python.exe -X utf8 -m modules.validation`
2. Normal masaüstü kabulü (`--desktop --skip-suite`)
3. Ayrı haber final kabulü (`--news --skip-suite`)
4. FAIL ise Terra kök nedeni düzeltir, commit/push yapar; PASS ise yalnız mevcut onaylı görev tamamlanır ve sonraki onaylı roadmap maddesine geçilebilir.

Haber normal desktop turuna gömülü değildir. Basit/odak test PASS sonucu haber görevini tamamlamaz; haber final kapısı ayrıca PASS olmalıdır.

Windows'ta Terra çağrısı `gpt-5.6-terra`, `windows.sandbox='unelevated'` ve `danger-full-access` ile çalışır; bunun nedeni `.git` yazımının workspace-write altında engellenmesidir. Prompt main'e doğrudan yazmayı, force kullanımını, `android/` ve `.venv` değişikliğini yasaklar.

Başlatma:
- Tek tur: `.venv\Scripts\python.exe -X utf8 scripts\pc_test_loop.py --once`
- Sürekli: `scripts\pc_test_watcher.bat`
- Oturum açılışında otomatik: `powershell -ExecutionPolicy Bypass -File scripts\install_pc_test_watcher_task.ps1`

Raporlar `%LOCALAPPDATA%\Jarvis\pc-acceptance` altında tutulur. Aynı hata imzası tekrar ederse Terra yeniden çağrılmaz; kota koruması devreye girer.
