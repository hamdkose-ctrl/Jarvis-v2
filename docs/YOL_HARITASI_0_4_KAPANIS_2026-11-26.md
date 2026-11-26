# Yol haritası 0–4 — kapanış (26 Kasım 2026)

Bu dosya, kullanıcının 10 maddelik listesinin **ilk beş maddesini** (0–4) kapatır.
Her madde: ne yapıldı, hangi kanıt, hangi dürüst sınır.

## 0 — Dosya işlemleri (yerel)
- **Yapıldı:** `modules/file_ops_local.py` — `list_folder` (en çok 50, klasörler önce), `read_file`
  (200 KB / 50 satır, kesilirse söyler), `open_file` (içeriğe dokunmaz), `write/delete YOK`.
  Yalnız ev klasörü; `C:/Windows` reddedilir; kısa yol adı (`HAMDI~1.KOS`) `os.path.realpath` ile çözülür.
- **Ek (26 Kasım):** ilişkilendirilmemiş türler (`md/json/log`) **Not Defteri** ile açılır, tanınmayan tür
  açılmaz — Windows'un "birlikte aç" penceresi Jarvis'i kilitlemesin diye (#838).
- **Kanıt:** `test_file_ops_local` + `OpenFileTypes` (19 test), canlı: dosya listeleme/okuma.

## 1 — Arama sonucuna tıklama
- **Yapıldı:** `pc_hands.click_search_result(query)` — OCR ile eşleşmeyi bulur, soldan-yukarıdan ilk sonuca
  tıklar, önce/sonra ekranı karşılaştırır; yazı yoksa **tıklamaz**.
- Sesli yol: `pc_click_result` ("youtube sonucuna tıkla").
- **Kanıt:** canlı ("jira" ekranda yokken "göremedim; tıklamadım"), `test_pc_hands`.

## 2 — Kopyala / yapıştır
- **Yapıldı:** `read_clipboard`, `write_clipboard`, `copy_selection`, `paste_text` (+ `_text_visible` teyidi).
- **Kanıt:** canlı Not Defteri'ne yapıştırma → done; `test_pc_hands`.

## 3 — Form doldurma (çok alan)
- **Yapıldı (ayrı özellik değil, zincir):** tek komutla çok alan `pc_task` zinciriyle çalışır:
  "… ad alanına Ahmet yaz, sonra telefon alanına 0555 yaz" → **2 adım `pc_type`** (ölçüldü, 26 Kasım).
- **Sınır (dürüst):** her alan ayrı `pc_type` adımıdır; alanlar arası geçiş (Tab/odak) otomatik değildir,
  pencere devralma ilk adımdan sonra kullanılır. Alan odaklanmadıysa yazma **doğrulanmaz ve "done" denmez**
  (`_text_visible` kuralı).

## 4 — Zamanlı iş
- **Yapıldı:** `modules/autonomy_when.py` — "yarın / bugün / öbür gün / saat HH:MM / N dakika sonra";
  `parse_when` zaman yoksa **tahmin etmez**, "saat söylenmediyse 09:00 kabul ettim" notu verir;
  "25:00" reddedilir. `fast_commands` → `autonomy_schedule` → `pc_autonomy_queue.enqueue`.
- **Kanıt:** `test_autonomy_when` (8), canlı kuyruk kaydı; özyineleme koruması ayrıca eklendi (canlı kusur).

## Ortak kanıt (bu PC, 26 Kasım)
- Zor görev karnesi temiz ortamda **6/6 beklenen davranış** (#842).
- `modules.validation` → **exit 0**, tüm gruplar yeşil.
- Canlı semantik kabul: holdout `state=passed`, **%95**, yanlış işlem 0.

## Kapanış hükmü
**0–4 kapandı.** Açık kalan tek davranış boşluğu: form alanları arasında otomatik odak geçişi (3. maddenin
sınırı) — istenirse ayrı iş olarak açılır; bugünkü hâli **yanlış başarı üretmiyor**, sadece daha yavaş.
