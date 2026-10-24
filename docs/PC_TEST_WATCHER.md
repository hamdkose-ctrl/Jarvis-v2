# Gerçek Windows PC kabul watcher'ı

Amaç: yalnız GitHub'da **açık PR'ı bulunan** `gpt/*` dallarındaki yeni SHA'ları gerçek iş PC'sinde kabul sırasından geçirmek ve sonucu ilgili PR'a yorumlamak. Watcher yalnız ölçer ve raporlar; kod değiştirmez. Otomatik düzeltme (Terra) döngüsü 22 Ekim 2026'da kaldırıldı: hata kök nedenini ayrı bir onaylı dal/PR ile insan düzeltir, watcher yeni SHA'yı yeniden kabulden geçirir. GitHub açık PR listesi doğrulanamazsa fail-closed davranır; eski/kapalı remote dalları test etmez.

Aşamalar:
1. Her açık PR'ın yeni SHA'sında `.venv\Scripts\python.exe -X utf8 -m modules.validation`
2. Yalnız desktop/PC runtime dosyaları değişmişse gerçek masaüstü kabulü (`--desktop --skip-suite`)
3. Yalnız haber runtime dosyaları değişmişse ayrı haber kabulü (`--news --skip-suite`)

Validation her zaman ilk kapıdır; seçilmiş acceptance katmanları yalnız validation geçerse başlar. Docs, hook, CI ve watcher'ın kendi değişiklikleri gerçek uygulama açmaz ve canlı haber akışı çalıştırmaz. `modules/acceptance_checks.py` iki acceptance katmanının ortak uygulama noktası olduğundan ikisini de seçer.

Operatör kapsamdan bağımsız kabul isteyebilir:

- Desktop: `scripts\pc_test_watcher.bat --desktop --once`
- Haber: `scripts\pc_test_watcher.bat --news --once`
- İkisi: `scripts\pc_test_watcher.bat --desktop --news --once`

Batch dosyası varsayılan olarak hiçbir acceptance bayrağını zorlamaz. Basit/odak test PASS sonucu haber görevini tamamlamaz; haber kapsamı seçildiğinde haber final kapısı ayrıca PASS olmalıdır.

Başlatma:
- Tek tur: `.venv\Scripts\python.exe -X utf8 scripts\pc_test_watcher.py --once`
- Sürekli: `scripts\pc_test_watcher.bat`
- Oturum açılışında otomatik: `powershell -ExecutionPolicy Bypass -File scripts\install_pc_test_watcher_task.ps1`

Raporlar `%LOCALAPPDATA%\Jarvis\pc-acceptance` altında tutulur. Her SHA yalnız bir kez test edilir; PASS/FAIL sonrası otomatik tekrar yoktur, yeni SHA yeni kabul turu başlatır. Doğrulama yalnız gözetlenen kökteki `.venv\Scripts\python.exe` ile çalışır; bu yorumlayıcı yoksa sistem Python'una düşülmez, başlamadan "ortam eksik" sonucu kaydedilir.
