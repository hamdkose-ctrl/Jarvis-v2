# Jarvis Yol Haritası — Drive Fikir Deposu 0–4 Ekleri

Tarih: 27 Ekim 2026
Kaynak: Google Drive `Jarvis - Fikir Deposu`
Taban: `main@f328ba6e5f63a9cd45c54454521aed9f49f2ffbb`

Bu ek, Fikir Deposu'nda doğrulanmış ve Faz 0–4'e değen dört fikrin yol haritasındaki yerini sabitler. Buradaki maddeler mevcut fazları ikinci kez kurmaz; kodda zaten bulunan parçalar korunur, yalnız gerçek boşluklar iş olarak açılır.

## F-009 — Ücretsiz/kota-aware provider yönlendirme kuralları

**Faz:** 1 — Provider dayanıklılığı.

**Kod durumu:** KISMİ. Mevcut `smart_router.py` paid fallback'i fail-closed engeller; yalnız `openrouter/free` veya `:free` model kabul eder, ücretsiz hesap onayı yoksa cloud rotalarını atlar, cooldown/fallback uygular ve ücretsiz yollar tükenince ücretliye geçmeden durur.

**Gerçek eksik:**
- `cloud_free_confirmed` yalnız kullanıcı tarafından verilen boolean onaydır.
- Sağlayıcının gerçek kalan ücretsiz kota/eligibility bilgisi yoktur.
- Resmi free-tier evidence/catalog yoktur.
- “Şu anda kesin ücretsiz ve kullanılabilir” sonucunu süreli doğrulanmış evidence olarak tutan yapı yoktur.
- Evidence için TTL/periyodik yeniden doğrulama yoktur.
- Router seçimleri bu evidence'a göre puanlanmaz.

**Yapılacak:** Mevcut router korunarak quota/eligibility evidence, free-tier catalog, doğrulama süresi ve evidence-aware seçim eklenir. Ücretli fallback yasağı gevşetilmez.

**Durum:** AL / UYARLA — Faz 1'in sıradaki dikey işi.

---

## F-011 — Proaktif günlük briefing davranışı

**Faz:** 2 — Scheduler / RuntimeEvent / bildirim davranışı.

**Kod durumu:** BÜYÜK ÖLÇÜDE VAR. `_daily_briefing`, `_morning_brief` ve engine açılışındaki otomatik morning-brief tetikleyicisi mevcuttur; günlük plan takvim, açık/gecikmiş görevler, Gmail ve handoff bilgisini toplar.

**Yapılacak:** Yeni capability açılmaz. Önce gerçek acceptance ile mevcut davranış doğrulanır:
- kullanıcı istemeden belirlenen anda briefing gerçekten tetikleniyor mu,
- tamamlanan işler / bekleyen onaylar / hata-engeller / açık-geciken işler kapsanıyor mu,
- çıktı kısa ve eyleme dönük mü,
- aynı briefing gereksiz tekrar üretmiyor mu.

Acceptance eksik gösterirse yalnız kanıtlanan küçük gap ayrı PR olur.

**Durum:** ZATEN VAR / ACCEPTANCE BEKLİYOR.

---

## F-002 — Finance: analiz → işlem planı → risk → kullanıcı onayı

**Faz:** 3/4 — Finance veri/sözleşme tabanı + Faz 4 read-only Finance üzerinde gelişmiş karar desteği.

**Kod durumu:** KISMİ. Salt-okuma piyasa/veri analizi ve Finance worker yönü vardır; fakat disiplinli işlem-planı ve risk kapısı zinciri tamamlanmış değildir.

**Hedef kapsam:**
- piyasa / varlık analizi,
- giriş planı,
- stop seviyesi,
- hedef / çıkış planı,
- varsayımların açık yazılması,
- pozisyon boyutu,
- PASS / BLOCK risk kontrolü,
- gerekçeli kullanıcı önerisi,
- planın gerçek işleme dönüşmesinden önce açık kullanıcı onayı.

**Güvenlik sınırı:** Bu kapsam broker/emir yürütmez. Gerçek para hareketi, broker entegrasyonu, paper/live order ayrı ve daha sonraki karardır.

**PR bölünmesi:**
1. **PR 1 — Analiz → giriş/stop/hedef + varsayımlar:** mevcut Finance read-only verisinden deterministik/yapılandırılmış trade-plan taslağı; veri yoksa uydurma yok.
2. **PR 2 — Pozisyon boyutu + PASS/BLOCK risk motoru:** risk bütçesi, pozisyon boyutu ve açık blok nedenleri; belirsizlikte fail-closed.
3. **PR 3 — Kullanıcı onayı ve güvenli sunum:** plan özeti, risk özeti, explicit approval sınırı; broker/emir yok.

**Durum:** AL / UYARLA — 0–4 kapsamındaki büyük Finance derinleştirmesi.

---

## F-003 — Memory ≠ Task State ≠ Context

**Faz:** çekirdek kural Faz 0 ile ilişkili; ayrıntılı uygulama Faz 11.

**Kod durumu:** ÇEKİRDEK AYRIM BÜYÜK ÖLÇÜDE VAR. GoalState görev durumunu, learning/personalization hafızayı, çalışma context yolları ise modele verilen anlık bağlamı ayrı tutar. Memory relevance gate de kod/test tarafında mevcuttur.

**0–4 kuralı:**
- Memory, GoalState yerine geçemez.
- Hafıza bir görevi kendi başına başlatamaz, tamamlandı sayamaz veya execution authority yaratamaz.
- Context'e verilen geçici bilgi durable memory sayılmaz.
- Task State geçici konuşma/context içeriğine indirgenmez.

**Faz 11'e bırakılan ayrıntılar:** context compression, uzun görev context yönetimi, context-file referansları, daha gelişmiş memory lifecycle.

**Durum:** 0–4 için yeni capability PR'ı açma; çekirdek ayrımı invariant olarak korunur, detay Faz 11'de tamamlanır.

---

## 0–4 kapanış özeti

Drive Fikir Deposu açısından yeni kod işi olarak:
- **F-009:** Faz 1'e alınır.
- **F-002:** Faz 3/4 kapsamında alınır ve 3 PR'a bölünür.

Doğrulama/acceptance olarak:
- **F-011:** mevcut davranış acceptance ile doğrulanır; eksik kanıtlanırsa küçük gap PR'ı açılır.

İleri faza ayrıntı bırakan çekirdek kural olarak:
- **F-003:** 0–4'te invariant korunur; ayrıntılı uygulama Faz 11'e aittir.
