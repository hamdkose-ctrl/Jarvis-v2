# Ekip yönetimi çalışma koordinasyonu

Dal: `codex/team-orchestration-20261015`. Henüz main'e birleştirilmedi.

Başlangıç tabanı `6513bef6`; diğer çalışmanın `2cecfa93` rapor/video ve kilitli coder düzeltmeleri çalışma tabanına alınmıştır. Bunlar bu özelliğin yaptığı iş olarak sayılmaz.

Değişen çalışma dosyaları: `modules/team_center.py`, `modules/goal_executor.py` (uzman bağlamı/etiketi), `modules/task_agents.py` (etiket), `web_tasks.py` (yerel köprü), `webui/team-center.js`, `webui/nx.js` (menü bağlantısı), `webui/nx.html` (yerel betik), `webui/nx.css` (yalnız ekip ekranı), test ve durum belgeleri.

Güncelleyici, Android, hologram ve ses motoruna dokunulmadı. `goal_executor.py` diğer çalışmayla ortak dosyadır: son upstream düzeltmeleri korunarak yalnız uzman bağlamı/etiketi eklenir.

Uygulananlar: uzman kaydı, mevcut görev ve teslim görünümü, mevcut kuyruk üzerinden kaynak takibi, kuyruk iptali ve yerel kanıt kontrolü. Yeni uzman bir hesap bağlantısı/model/adaptör kurmaz. Finans ve mağaza servisleri ayrıca bağlantı gerektirir. Gerçek sürekli çalışan ofis veya bütün dış servislerin hazır olduğu iddia edilmez.

Test durumu: güncel 2cecfa93 tabanı ve son düzeltmeyle 1203 Python testi (2 mevcut atlama), 23 Node grubu ve 6 smoke grubu geçti. Tarayıcıda hedef gönderme, uzman ekleme, takip/iptal, XSS kaçırma, yeniden giriş ve 320/390/768/1280 taşma kontrolleri geçti. Salt okunur kural denetiminde bulunan eski running kaydının yanlış canlı görünmesi görev kimliği eşleştirmesiyle giderildi; yeniden denetim geçti. Canlı API, hesap ve Windows kabulü yapılmadı.

Kullanıcı talimatı: birlikte kontrol et, birleştirmeden raporla; Windows testlerini en sonda tek listede ver. Bu not diğer sohbetin okuyabileceği ortak kayıttır, sohbetler arasında doğrudan mesaj kanalı yoktur.
