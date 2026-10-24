# Gerçek Windows PC kabul watcher'ı

Amaç: yalnız GitHub'da **açık PR'ı bulunan** `gpt/*` dallarındaki yeni SHA'ları gerçek iş PC'sinde kabul sırasından geçirmek ve sonucu ilgili PR'a yorumlamak. Watcher yalnız ölçer ve raporlar; kod değiştirmez. Otomatik düzeltme (Terra) döngüsü 22 Ekim 2026'da kaldırıldı: hata kök nedenini ayrı bir onaylı dal/PR ile insan düzeltir, watcher yeni SHA'yı yeniden kabulden geçirir. GitHub açık PR listesi doğrulanamazsa fail-closed davranır; eski/kapalı remote dalları test etmez.

Aşamalar:
1. `.venv\Scripts\python.exe -X utf8 -m modules.validation`
2. Normal masaüstü kabulü (`--desktop --skip-suite`)
3. Ayrı haber final kabulü (`--news --skip-suite`)

Her aşama yalnız bir önceki geçtiyse başlar. Haber normal desktop turuna gömülü değildir. Basit/odak test PASS sonucu haber görevini tamamlamaz; haber final kapısı ayrıca PASS olmalıdır.

Başlatma:
- Tek tur: `.venv\Scripts\python.exe -X utf8 scripts\pc_test_watcher.py --news --once`
- Sürekli: `scripts\pc_test_watcher.bat`
- Oturum açılışında otomatik: `powershell -ExecutionPolicy Bypass -File scripts\install_pc_test_watcher_task.ps1`

Raporlar `%LOCALAPPDATA%\Jarvis\pc-acceptance` altında tutulur. Her SHA yalnız bir kez test edilir; PASS/FAIL sonrası otomatik tekrar yoktur, yeni SHA yeni kabul turu başlatır. Doğrulama yalnız gözetlenen kökteki `.venv\Scripts\python.exe` ile çalışır; bu yorumlayıcı yoksa sistem Python'una düşülmez, başlamadan "ortam eksik" sonucu kaydedilir.
