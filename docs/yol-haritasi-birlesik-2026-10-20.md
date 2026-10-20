## Hamdi'nin kararları (2026-10-20)

1. **Tek sistem.** İkinci bir Manifest/Registry kurulmaz. Manifest = `CONTRACT`'ın genişletilmişi, registry = Harita arka ucu.
2. **Sıra.** Önce kota + Ollama'sız mesaj. Sonra sözleşme omurgası (45b, 48-50). Sonra küçük kimlik/Self Model (≤10 maddelik kimlik metni + "neleri yapabilirsin" ekranı). Tam Personality sonra.
3. **Motor birleştirme.** Ek PC deneme turu olmadan, düzeltmeler bitince seçenek A.
4. **Builder en sona.** Araç sihirbazı (54-57) ve 2 araç PC'de geçtikten sonra; yalnız insan onaylı taslak PR.
5. **Arayüz.** Kota arayüzden önce; varlık-merkezli arayüz en son.

---

# Birleşik yol planı: Hamdi'nin "V2 Birleşik Ana Yol Haritası" ile projenin mevcut planları (20 Ekim 2026)

Yalnız belge. Kod yok, PR yok. Kaynaklar: Hamdi'nin belgesi (34 bölüm), `gpt-yol-haritasi-2026-10-19`, `jarvis-genel-plan-harita-2026-10-19`, `jarvis-yol-haritasi-2026-10-17`, `jarvis-vizyon-mimari-2026-10-17-v2`, `pc-deneme-2026-10-20`, `pc-deneme-listesi-2026-10-19`; destek olarak `ortak-izin-kapisi-tasarim`, `pc-testi-haber-ve-429-bulgu`, `google-oauth-cok-kullanici`, `ollama-yollari`, `motor-birlestirme-tasarim`, `finans-takibi-plan`.

İşaretler: **[K]** raporda kodla/kanıtla yazılı, **[T]** tahmin/çıkarım. "Yapıldı" yazmıyorum: PC'de denenmeyen her şey **PC'de denenmedi**.

**Sınırlama:** GitHub MCP bu oturumda `hamdkose-ctrl/Jarvis-v2` için yapılandırılmamış (erişim reddedildi), depoyu doğrudan okuyamadım. Dosya adları (`engine_commands.py`, `goal_executor.py`, `goal_tools.py`, `permission_gate.py`, `permission_classify.py`, `team_center.py`, `capability_hub.py`, `specialist_contracts.py`) raporlardaki satır numaralı alıntılardan alındı; depoda doğrudan doğrulanmadı. Raporlarda `capability_manifest` / `registry` / `identity` / `self_model` adında modül **geçmiyor**; "yok" demek için depoda `search_code` ile teyit gerekir (öneri: depo eklenirse 1 dakikalık kontrol).

---

## 0. Tek paragraf sonuç

Hamdi'nin belgesi mimari yönü doğru koyuyor ve projenin zaten izlediği hatla örtüşüyor (önce koruma/regresyon, sonra canlı kabul, sonra genişleme). Ama iki şeyi eksik bırakıyor: (1) proje bu belgenin "Faz D" dediği şeyin **yarısını farklı adla zaten yürütüyor** (araç sözleşmesi `CONTRACT` + izin kapısı + Harita, Görev 45-57); ikinci bir paralel "Capability Manifest/Registry" sistemi kurmak aynı işi iki kez yapmak olur. (2) Kota/429, Ollama'sız çalışma, PC denemesinde çıkan 4 bozuk ve izin kapısı belgede hiç yok. Öneri: **tek kavram** (araç sözleşmesi = manifest, Harita = registry görünümü), Faz C'nin (kimlik) küçük bir sürümü hemen, "kendi kendine yetenek ekleme" (Faz D builder) ise çok sonra ve yalnız insan onaylı PR olarak.

---

## A. Belgede olup projede ZATEN olan / yürüyenler

| Belge bölümü | Projede karşılığı | Kanıt |
|---|---|---|
| §1 Mevcut temel: kalıcı görev, devam/iptal, kullanıcı izolasyonu, kuyruk, uzmanlar | `goal_executor` + `task_agents` (iki motor), `task_queue`, `team_center`, kullanıcıya özel depolar | [K] vizyon-v2 §3.2; `motor-birlestirme-tasarim` (task_agents 871 satır, goal_executor 675 satır) |
| §2 "üç riskli merkez" (engine_commands / goal_executor / goal_tools) | Aynı teşhis: 51 sıralı `if`, haber kodu çekirdekte, 10'a yakın paralel yol | [K] vizyon-v2 §3.2 a-c; yol haritası Aşama 2 |
| §3 Faz A routing regression | `tests/data/yonlendirme_cumleleri.json` (89 → 200 → 296 cümle), kalıcı CI, "bilinen_hata" işareti | [K] PR #74, #75; GPT 200 cümle seti; `pc-testi-haber-ve-429-bulgu` (296 cümle) |
| §3 Kritik dosya politikası | "tek sahip" kuralı, motor birleştirme PR'ları çekirdekte sırayla | [K] yol haritası Aşama 2 sıra kararı; GPT yol haritası "bir dosyanın tek sahibi" |
| §3 Contract regression (planner→...→verification) | Araç yürütme zinciri `classify → permission_gate.decide → onay → çalıştır → doğrula → permission_audit` | [K] genel plan §1; kapı #181/#186, masaüstü bağlı |
| §3 Legacy ayrımı | Aşama 2: ölü kod (`brain_delegate.plan/try_run/run`) silme önerisi, `task_agents` eski yol kaldırma, AGENTS.md'den tarihçe ayırma | [K] GPT raporu 26-27, 30 |
| §4 Faz B canlı kabul | `docs/kabul/<alan>.md` önerisi, `pc-deneme-listesi`, `scripts/pc_deneme_kaydi.py`, `pc_duman_testi.py` | [K] vizyon-v2 Adım 3; GPT yol haritası; yol haritası GPT 18 Ekim dalı |
| Senaryo 1 uzun görev + kesinti + devam | "devam/iptal" tek giriş (#139); PC deneme listesi A bölümü | [K] kod+test; **PC'de denenmedi** (liste). 20 Ekim denemesinde yalnız "hedef yokken devam" denendi |
| Senaryo 3 haber (7 gün, 2 yayıncı, tekil sayfa) | #60-#71 haber düzeltmeleri, GDELT'siz katalog | [K] kod; güncel sürüm **PC'de denenmedi**; 20 Ekim "son dakika haberleri" **tamamlanmadı** (bkz. C-4) |
| Senaryo 4 Gmail oku → ek işle | Ek okuma (PDF/Office) gerçek baytlarla test | [K] vizyon-v2 §2.3; gerçek Gmail **PC'de denenmedi**. 20 Ekim "mailleri özetle": 3 Gmail + 1 Outlook doğru listelendi (PC'de denendi, ek yok) |
| Senaryo 5 güvenli gönderim (alıcı sabit, çift gönderim yok) | `outbox.py`: kesin hedef izni, günlük tavan, aynı içerik tekrar engeli, digest'e bağlı onay | [K] ortak-izin-kapısı §1; Görev 46 (TR-INJ-04) hâlâ açık |
| Senaryo 6-7 PC / üçüncü taraf uygulama | `desktop_agent`: UIA, `apps.json` uygulama izni, `_NEVER_APPS`, kapı #181 | [K]; yalnız Paint/Hesap Makinesi PC'de; Gezgini/Ayarlar **denenmedi** |
| Senaryo 8 kuyruk + yeniden başlatma | `task_queue` sabit plan, checkpoint | [K] kod; **PC'de denenmedi** (liste B4) |
| Senaryo 9 sağlayıcı arızası, kör retry yok | 429'da model bekletme (60 sn / günlük 3600 sn), Groq→Ollama düşüşü, kota sayacı (#76) | [K] `pc-testi-haber-ve-429-bulgu` §2; **gerçek 429 PC'de 20 Ekim'de görüldü ve kötü davrandı** (C-4) |
| §9 Self Model "gerçek sistem durumundan" | Kısmen: `kota durumu`, `usage_meter`, Harita'nın `Bridge.map()` (tüm CONTRACT + durum + izin) | [K] genel plan §2; Görev 45b henüz yok, #187 CI bekliyor |
| §10-12 yetenek yaşam döngüsü, manifest, registry | **Araç sözleşmesi**: `CONTRACT` (id, ad, alan, eylemler, sınıf, parametre/sonuç şeması, `durum()`, `iptal()`), `tool_contract.load_all`, eksik sınıf/`iptal()` ise yüklenmez | [K] genel plan §1; GPT Görev 48-50 (mail, takvim, haber, finans, dosya, Hoca taşınıyor) |
| §13 capability runtime zinciri | Genel plan §1 yürütme sırası (aynı zincir) | [K] |
| §14 qualification gate (bir kısmı) | Sahte araç testi `tool_fake.py` (yalnız yeni dosya + test ile yüklenir, Harita'da görünür, Durdur ile durur) | [K] genel plan §1.1 |
| §12 `enabled+healthy` | Harita durum renkleri: hazır / izin bekliyor / çalışıyor / hata / bağlı değil | [K] genel plan §2 |
| §15 "ayrı dal, test, taslak PR, CI, inceleme, merge" | GPT çalışma kuralı birebir bu; "main'e doğrudan yazılmaz"; `git_publish` artık `jarvis/yukle-...` dalına PR açıyor (#78) | [K] |
| §16 Pilot 2: 3D yazıcı | `tool_printer`, `tool_slicer`, `tool_cad`, `physical` sınıfı | [K] GPT Görev 51-53; yazıcı eylemi her zaman **Sor** (Hamdi kararı 19 Ekim) |
| §16 Pilot 1: Harita (yer haritası) | **Ad çakışması:** projede "Harita" = araç/izin ekranı, belgede `maps.*` = coğrafi harita | bkz. D-5 |
| §17 analitik düşünme (deterministik hesap) | Kısmen: `domain_tools.exchange` tarihli kur, kaynak özeti; yol haritasında "analitik düşünme" GPT önerisi (Aşama 2) | [K] kısmi; `analysis.*` ailesi yok |
| §18 finans | Salt okuma plan: kur, takip listesi, alarm, BIST; GPT finans/BIST görevi | [K] `finans-takibi-plan`, `gpt-gorevi-finans-bist`; alım-satım bilerek **yok** |
| §19 görsel rapor, Hoca | Hoca sekmesi (#136), video kaynağı (#138), `hoca-modu-plan` | [K] kod; **PC'de denenmedi** |
| §20 hafıza/öğrenme | `learning.py`, kural kapsamı, not kapısı (#141) | [K]; kural kapsamı hatası vizyon-v2'de kanıtlı, #75'te düzeltildi (taklitle) |
| §21 uzman ekipleri | `team_center`, `specialist_contracts`, `specialist_orchestrator` (üretimde çağrılmıyor) | [K] GPT raporu 27 |
| §22 sağlık durumları | Harita durum renkleri; `kota durumu`; `scripts/pc_duman_testi.py` | [K] kısmen; `auth_expired`/`missing_dependency` ayrımı **[T]** yok |
| §28-34 Arayüz felsefesi | Harita: ortada Jarvis küresi, çevresinde alan düğümleri, düz HTML kartlar, sakin mod | [K] genel plan §2, §4; **büyük kısmı örtüşüyor**, fark: belge "menü yok, geçici yüzey"; proje "Harita tek sayfa + mevcut menü" (D-6) |

---

## B. Belgede olup projede HİÇ olmayanlar

(Raporlarda hiç geçmeyen; depoda `search_code` ile teyit edilmedi, **[T]** ile okunmalı.)

| # | Belge maddesi | Durum |
|---|---|---|
| B1 | **Identity Core** (§6): kimliğin hafızadan ayrı, değişmez çekirdek olarak tutulması | Raporlarda yok. `learning.py`/kişi modeli var ama "kimlik" katmanı yok [T] |
| B2 | **Personality Layer** (§7) ve **Relationship Layer** (§8) ayrı katman | Yok. Yakın: Aşama 5 "kişiye göre tavır" (Sonra) |
| B3 | **Self Model JSON** (§9) tek canlı belge (cihaz, aktif model, capability durumu, açık iş, degraded) | Parçalar var (`kota durumu`, `Bridge.map`, duman testi) ama tek model yok. Harita arka ucu (45b) buna en yakın |
| B4 | **Capability Registry yaşam döngüsü durumları** (discovered … rollback_required) | Yok. Projede araç ya yüklü ya yüklenmez (ikili) |
| B5 | **Capability Qualification Gate** (§14: manifest/contract/validation/permission/replay/verification/failure/isolation testleri **her yeni yetenek için standart paket**) | Yok. Sahte araç testi tek örnek |
| B6 | **Capability Builder** (§15): Jarvis'in kendi `capabilities/<ad>/` paketini üretmesi | Yok. Proje bunu "Kendini geliştirme (14. alan, bekliyor)" olarak ertelemiş; GPT/Claude insan eliyle yazıyor |
| B7 | **Discovery/Assess** (§10): yeni yeteneği Jarvis'in bulup değerlendirmesi | Yarım: `capability_hub` açık GET API keşfi var [K]; yerel program/cihaz keşfi yok; sihirbaz (Görev 54-56) kullanıcı tetikli |
| B8 | **"Hazır / Eklenebilir / Mümkün değil"** üçlü cevap standardı (§25) | Yok. En düşük maliyetli, en yüksek değerli madde (B-3 kalemi) |
| B9 | **Varlık katmanı** (§30-32): silüet, bakış, durum animasyonu (idle/listening/thinking/…) | Yok. Orb var; 10 durumlu varlık yok. Proje "canvas çizimi yok, 2 GB RAM'de sakin mod" ilkesinde (genel plan §2) |
| B10 | **Çalışma yüzeyinin bağlama göre kendiliğinden açılıp kapanması** (§29) | Yok (Harita tek sayfa) |
| B11 | **`analysis.*` capability ailesi** (§17) | Yok |
| B12 | **Görsel Rapor Motoru** (§19, 11 format) | Yok. Yakın: Hoca, video üretimi |
| B13 | **Coğrafi Harita pilotu** `maps.*` (§16) | Yok |
| B14 | **10 senaryolu canlı kabul bütünü ve "10/10 olmadan v2 bitmedi" kuralı** | Kısmen: kabul listesi var ama senaryolar belgedekinden farklı ve hiçbiri tam PC'de geçmedi. Belgedeki 10 senaryo daha iyi bir **çıkış ölçütü**; benimsenebilir |
| B15 | **Paralel uzmanlar / kaynak çakışması / specialist health** (§21) | Yok; yok olması doğru (D-2) |
| B16 | **CAD, CNC, drone, IoT, sosyal medya yetenek paketleri** | CAD/yazıcı planda; CNC/drone yok; ev cihazı `tool_home` "sonra" |

---

## C. Belgede EKSİK olanlar

| # | Eksik | Ne gerekiyor | İşaret |
|---|---|---|---|
| C1 | **Kota / 429 / günlük sınır** | Belge "araç/sağlayıcı arızası" senaryosu koyuyor ama Gemini kotası ana risk. Her sohbet sorusu 2 çağrı, görev yolu ~4 çağrı/58 bin karakter; kota sayacı var, günlük kullanıcı üst sınırı yok; hata metni ham "429 RESOURCE_EXHAUSTED" | **kanıtlı** (yol haritası 1b; 429 bulgu §2-3). Kimlik/self-model yeni LLM çağrısı eklerse kota artar: **[T]** her çağrıda uzun kimlik promptu Groq token sınırını zorlar |
| C2 | **Ollama'sız çalışma** | Hamdi kuralı: bulut birincil, Ollama isteğe bağlı 3. plan; yoksa "Ollama yüklemelisin". İş PC'sinde Ollama yok. 20 Ekim'de Ollama "yanıt vermedi" yazdı (kural ihlali) | **kanıtlı** (`ollama-yollari`, `pc-deneme-2026-10-20` madde 4) |
| C3 | **Düşük donanım** | 2 GB RAM hedefi, sakin mod, canvas yok. Belgenin "enerji çekirdeği / ışık / çevresel efekt" tasarımı buna aykırı olabilir | **kanıtlı** (genel plan §2); belge tarafı **tahmin** |
| C4 | **PC denemesi 20 Ekim bozukları 1-4** | (1) "hangi dosya yazıldı" ham JSON; (2) "hedef durumu" eski haber sonucunu tam metinle döktü (sonuç kartı kısa özet olmalı); (3) çıplak "iptal" açık iş yokken yeni-sohbet onayı sordu; (4) "hedef son dakika haberleri" tamamlanmadı + alakasız kaynak + Gemini kota + Groq/Ollama "yanıt vermedi" + hata satırı iki kez. Belgenin Faz B senaryo 3 (haber) tam bu | **kanıtlı** (PC'de denendi). Neden: eski iş sonraki cümleleri yutuyor (`goal_executor.latest()` yaşa bakmıyor) [K] 429 bulgu §1 |
| C5 | **Güvenlik izin kapısı ve Görev 45-57** | Belgenin "Capability Runtime / authorize" aşaması = projedeki `permission_gate` + `physical` sınıfı + politika deposu (45a) + TR-INJ-04 (46) + `file`/`system` yolları (47). Belge bunları bilmiyor; ayrıca "sınıf araç yazarının değil kapının tablosundan gelir" kuralı belgede yok | **kanıtlı** |
| C6 | **Windows / CI bütçesi** | Windows testleri bulutta yok; Actions bütçesi dolmuştu, #150/#151/#153 CI'sız girdi; Windows dakika çarpanı doğrulanmadı. Belgenin "her capability için qualification + CI" yükü bu bütçeyi yer | **kanıtlı** (pc-deneme-listesi "Eksik olabilecekler"; yol haritası) / çarpan **tahmin** |
| C7 | **Çok kullanıcı Gmail kararı** | Google OAuth: `gmail.readonly` "kısıtlı" kapsam; Testing modunda belirteç 7 günde düşer; her kurulum kendi Cloud projesini açıyor. Belge "tek ana kullanıcı" der, ama Jarvis "kullanıcı izolasyonu" iddiasında. Karar bekliyor | **kanıtlı** (`google-oauth-cok-kullanici`) |
| C8 | **Haber alanı kalitesi** | Kaynak seçimi alakasız (haber.dpu.edu.tr), kurumsal proxy riski, 7 gün güncel sürüm PC'de yok | **kanıtlı** (C4) / proxy **tahmin** |
| C9 | **Finans** | Salt okuma; kaynak çift (open.er-api vs Frankfurter); "dolar/euro" alt dize eşleşmesi yanlış yakalıyor; kaynaklar hiç canlı denenmedi; alım-satım kapsam dışı. Belge "piyasa, portföy" diyor: sınır belirsiz | **kanıtlı** (`finans-takibi-plan`) |
| C10 | **Sosyal medya / WhatsApp / Telegram ertelenenler** | Resmî WhatsApp Cloud API iş numarası+ücret ister; gayriresmî kütüphane hesap kapatma riski; X ücretli. Proje bunları "bekliyor" bırakmış. Belge F fazında "sosyal medya" listeliyor ama karar ve risk yok | **kanıtlı** (yol haritası Aşama 4) |
| C11 | **Geri alma / yedek** | Belge "rollback" diyor ama: ayar sürümleme, "son sağlam duruma dön", atomik yazma (`atomic_write`, SQLite WAL), dosya geri alma kaydının doğrudan yazılması eksik | **kanıtlı** (yol haritası Aşama 2 listesi); capability-seviyesinde rollback **tahmin** (yok) |
| C12 | **Maliyet** | Ücretli Gemini faturalandırma kararı; Exa/Firecrawl/Mem0 ücretli olabilir; belge hiç maliyet sınırı koymuyor | **kanıtlı** (kota #9, araçlar tablosu) |
| C13 | **Gizlilik** | Mail içeriği seçili buluta gidiyor; ekran görüntüsü modele gidiyor; Google/Telegram/WhatsApp belirteçleri düz JSON; DPAPI yalnız bazı anahtarlarda; enjeksiyon (web/mail metni talimat olmamalı); self model/kimlik kayıtlarına kişisel veri girmemeli | **kanıtlı** (yol haritası Aşama 2, `guvenlik-enjeksiyon-gemini`; Gemini raporu doğrulanmamış) |
| C14 | **Ses** | Belge "ses dalgası/konuşmaya tepki" diyor; ses yolu kanıtsız, Live ile yazı yolu farklı karar veriyor, mikrofon/hoparlör Linux'ta denenemez | **kanıtlı** (vizyon-v2 §2.6, yol haritası 1c) |
| C15 | **"Kalite > iş sayısı" ilkesi** | Hamdi: "iş çokluğu önemli değil, işin en iyisi olsun" (18 Ekim). Belge 10 faz sıralıyor, hangisinin kesileceğini söylemiyor | **kanıtlı** |
| C16 | **Eski kayıtların uyumu** | Eski görev kaydı yeni yapıda okunur mu; AGENTS.md ~174 KB, çelişkili maddeler | **kanıtlı** |
| C17 | **Çevrimdışı durum** | İnternet yokken ne denir? Tanımsız | **kanıtlı** (yol haritası 1c) |

---

## D. Belgedeki riskler / çelişkiler

1. **Kendi kendine yetenek ekleme vs. "Jarvis main'e yazmaz".** Belge §15 ikisini yan yana koyuyor. Çelişki yok gibi görünse de: üretilen kod Jarvis'in kendi kapı kodunu (`permission_gate`, sınıf tablosu) değiştirebilecek bir dosyaya dokunursa sorun. Gerçek risk: builder'ın ürettiği adapter **kendi eylem sınıfını ve `replay_safe` beyanını kendi manifestinde yazıyor** (belge §11 `risk`, `approval`, `replay_safe` manifest alanları). Projede kural tersi: sınıf **kapının tablosundan** gelir, araç icat edemez. Manifestteki `risk/approval` alanları beyan değil, kapıdan okunmalı. Ayrıca CI bu depoda bütçe sıkışık (C6) ve "testi geçti" ≠ "güvenli" (vizyon-v2: yeşil test ≠ çalışan özellik). Builder ancak insan incelemeli taslak PR olarak ve `physical`/`money`/`message_out` sınıflı yeteneklere **hiç** dokunmamalı.
2. **Fazla soyut fazlar.** Faz H (karakter gelişimi), I (paralel uzmanlar), J (sağlık durumları) ve §21 "kaynak çakışması" için bugün tek kullanıcı, tek PC, 2 uzman kullanımı var; `brain_delegate`/`specialist_orchestrator` zaten üretimde çağrılmayan ölü kod olarak silinmeyi bekliyor. Soyut katman eklemek yeni bozulma yüzeyi (vizyon-v2 §3: "10'a yakın paralel yol").
3. **"Kalite > iş sayısı" ve kota.** Belge sıralamayla 9 başlık açıyor. Kimlik/kişilik/self model her çağrıda prompt uzatır (kota), builder/discovery model çağrılı iş (kota), qualification testleri CI dakikası (bütçe). Hamdi'nin "en iyisi" ilkesi ancak **az sayıda, PC'de kanıtlı** işle sağlanır.
4. **Aynı şey iki adla.** Belge "Capability Manifest/Registry", proje "Araç sözleşmesi (`CONTRACT`)/Harita". İkisini paralel kurmak, vizyon-v2'nin teşhis ettiği "aynı işi yapan çok yol" sorununu yeniden üretir. Karar: manifest = `CONTRACT` genişletilmiş; registry = `tool_contract.load_all`'un kalıcı durum alanı.
5. **"Harita" ad çakışması.** Belge `maps.search/route/...` pilotu için "Harita" diyor; projede Harita ekranı = araç/izin haritası (`Bridge.map`, `tool_map.py`). Konuşmada karışır. Öneri: coğrafi olanı **"Konum/Rota"** diye anmak.
6. **UI felsefesi vs. maliyet ve test.** "Geçici çalışma yüzeyi açılır-kapanır" dinamik arayüz = `nx.js` çekirdeğine dokunmak; genel plan ilkesi "yeni araç çekirdeğe dokunmaz, Harita düz HTML kart". Ayrıca canvas/animasyon düşük RAM'de risk; arayüz testi Linux'ta yok (göz kontrolü PC'de).
7. **Identity "değişmez" ama "Gemini/Groq/Ollama kimliğim değil".** Kural tarafında doğru; ancak model değişince tavır değişmesin diye bunu test etmek gerek (yoksa kimlik promptu tek modelde işler, diğerinde sapar). Cümle setine kimlik satırları eklenmeli.
8. **Self Model "model tarafından uydurulmaz".** Doğru; ama tek JSON'u LLM'e vermek yine uydurma riski taşır. Self model **komutla modelsiz** (örn. `kota durumu` gibi) cevaplanmalı, sohbette alıntılanabilmeli.
9. **Faz sırası: Faz C (Identity) üçüncü, Faz D beşinci.** Ama Faz B (10 senaryo canlı kabul) PC'de **kimsenin zamanı yok** ve kota darlığında modelli senaryolar (3, 4, 10) güvenilir ölçülemez. "10/10 olmadan v2 bitmedi" kuralı pratikte v2'yi süresiz açık tutar. Öneri: kabulü iki kademe yap (modelsiz 6/10 önce, modelli 4/10 kota rahatlayınca).
10. **Belge "Gmail send: not_connected" örneği** ve "izin süresi" gibi hesap durumlarını self-model'e yazıyor; Google Testing modunda token 7 günde düşer (C7). `auth_expired` durumu zorunlu, belgenin ilk JSON'unda yok.

---

## E. Önerilen birleşik sıra

Lejant: **[GPT]** = GPT'ye verilebilir (ayrı dal, taslak PR, düşen test önce); **[C]** = Claude çekirdek/denetim; **[H]** = Hamdi kararı/onayı; **[PC]** = Hamdi PC'de dener (en sona).

### E.1 Hemen (yarım kalan ve PC'de çıkan bozuklar; kota ve güvenlik öncelikli)
1. **#187 (Harita arayüzü) CI sonrası birleşir.** [C] Bağımlılık: yok.
2. **PC bozukları (20 Ekim, sıra kendi raporunda):** (a) çıplak "iptal" yeni-sohbet onayı sormasın; (b) "hangi dosya yazıldı" ham JSON yerine okunur liste; (c) "hedef durumu" kısa sonuç kartı; (d) haber + hata metni (Ollama yoksa "Ollama yüklemelisin", satır tekrarı, alakasız kaynak). [GPT kartı, her biri tek dosya sahibi; (a) ve (d) `goal_executor.latest()` yaş/eski iş kuralı **[C] çekirdek**]. Bağımlılık: yok; PC listesindeki A1-A5 bunlara bağlı.
3. **Görev 45a** (politika deposu + Engelle kesin ret). [GPT], #186 sonrası. Hamdi onayı: güvenlik.
4. **Görev 46** (TR-INJ-04, giden mesaj yolunda etiketsiz gizli değer onayı). [GPT], 45a ile paralel (farklı dosya).
5. **Görev 47** (`file`, `system` yolları kapıya). [GPT], #183 sonrası; 46 ile paralel gidebilir.
6. **Kota/Ollama'sız sertleştirme (belgede eksik C1-C2):** günlük kullanıcı çağrı sınırı + kullanıcıya anlaşılır "kota doldu, X saat sonra / yedek yok" mesajı; "Ollama yüklemelisin" tek metin. [C tasarım, GPT uygulama]. Bağımlılık: yok. (Kimlik/self-model'den önce şart: yeni prompt kotayı artırır.)

### E.2 Sözleşme omurgası (belgenin Faz D'sinin çekirdeği, zaten GPT planında)
7. **45b** `Bridge.map` arka uç (`tool_map.py`; kilitli sınıf reddi). [GPT], 1'den sonra.
8. **48 → 49 → 50** mail+takvim → haber+finans → dosya+Hoca `CONTRACT`'a taşı (davranış değişmez). [GPT], sırayla (aynı sözleşme biçimi). Haber taşıması, C4(d) düzeltilmeden **yapılmaz**.
9. **Motor birleştirme adım 4** (`task_agents.execute/continue_job` → `goal_executor`) [C çekirdek]. Bağımlılık: PC deneme listesi B bölümü taban çizgisi **PC'de denenmeli** (B1-B4); Hamdi seçenek A/B kararı (F-3). Sebep: iki yürütücü olduğu sürece sözleşmeye taşımanın değeri sınırlı.
10. **Sözleşme genişletmesi = belgenin "Manifest/Registry" karşılığı** (yeni iş, küçük): `CONTRACT`'a `surum`, `bagimliliklar`, `platform`, `replay_safe`, `dogrulama` alanları ve durum alanı (`etkin/devre_disi/kullanımdan_kalktı/auth_expired/eksik_bagimlilik`). Sınıf alanı **kapıdan** okunur, araç beyan edemez. [C tasarım, GPT uygulama]. Bağımlılık: 48-50.

### E.3 Belgenin kimlik/self-model fazı (küçültülmüş)
11. **Self Model, modelsiz komut:** "yeteneklerini göster / neler yapabilirsin / bunu yapabiliyor musun?" cevabı `Bridge.map` + `kota durumu` + cihaz/oturum verisinden üretilir, LLM'siz; üçlü cevap (hazır / eklenebilir / şu an mümkün değil, eksik gereksinim) şablonu. [GPT]. Bağımlılık: 7, 10. Değer yüksek, kota maliyeti 0.
12. **Identity Core:** kısa (≤10 madde, ~600 karakter) sabit metin + test cümleleri; hafızadan ayrı dosya; tüm sağlayıcılarda aynı sistem öneki. [C yazar, GPT test]. Hamdi onayı (F-1, F-2). Bağımlılık: 6 (kota), 11.
13. **Personality + Relationship** yalnız mevcut öğrenme/kişi modeli üzerinden küçük genişleme (tavır tercihleri). Ertelenir; Aşama 5 ile birlikte. [H].

### E.4 Sihirbaz ve fiziksel araç (GPT planı korunur)
14. **51** `physical` sınıfı [GPT, Hamdi onayladı 19 Ekim]; **52** `tool_printer`; **53** slicer/cad. Bağımlılık: 45, 47, 51. Gerçek yazıcı **PC'de denenmedi** (yazıcı modeli bilinmiyor; F-5).
15. **54 → 55 → 56 → 57** araç ekleme sihirbazı (api / yerel program / HTTP cihaz / arayüz). [GPT]. Belgenin "Discovery + Builder"inin güvenli, **kullanıcı tetikli** sürümü; kullanıcı onayı olmadan hiçbir şey kurulmaz.

### E.5 Çok sonra / ayrı karar
16. **Builder (Jarvis'in kendi paketini yazması)**: yalnız 15 oturduktan ve en az 2 araç PC'de gerçek geçtikten sonra; yalnız `read`/`local_reversible` sınıfı; insan incelemeli taslak PR. [H onay, C denetim]. Şimdi başlatılmaz (D-1, D-3).
17. **Coğrafi Konum/Rota pilotu** (belge pilot 1): sihirbazın (a) açık API yoluyla ilk gerçek test olarak denenebilir, salt okuma. [GPT], 15 sonrası.
18. `analysis.*`: sayısal işlemler için mevcut `domain_tools` kalıbına 1-2 deterministik araç (karşılaştır, hesapla) olarak; "aile" olarak değil. [GPT], 10 sonrası.
19. Görsel rapor motoru, gelişmiş Hoca, sosyal medya/WhatsApp, CAD/CNC/drone, `tool_home`: kota ve PC kanıtı oturunca; sosyal/WhatsApp ayrıca resmî API kararı (C10).
20. Varlık arayüzü (belge §28-34): Harita ve durum olayları (`tool_state`) oturduktan sonra; ilk adım yalnız Jarvis küresinin 4-5 durum rengi/yavaş animasyonu (CSS, canvas yok). İlerisi PC performansı ölçülünce. [H].

### E.6 PC'de denenecekler (en sona, tek liste)
(Hiçbiri henüz denenmedi, aksi belirtilmedikçe.)
- A: "devam / iptal" 5 senaryo, yarım iş + yeniden açma (liste A1-A5).
- B: eski yol taban çizgisi (görev akışı, zamanlı iş, Gmail ek, kayıtlı iş geri gelme).
- C: Hoca sekmesi/video kaynağı, finans kaynak testi, söyleniş kümeleri, not kapısı, enjeksiyon maskeleme, arayüz göz kontrolü.
- Durdur şeridi (Gemini çalışırken göründü: PC'de denendi; Durdur'un görevi gerçekten kesmesi **denenmedi**), görev sonuç kartı, kur/kripto uyarıları, masaüstü/tarayıcı/gönderim kapıları, gizli değer maskeleme, Harita sayfası.
- Belgenin 10 senaryosu: 2 (dosya), 5, 6, 7, 8 modelsiz-sağlam kısımlar önce; 3, 4, 9, 10 kota rahatken.
- Betik: `scripts\pc_deneme_kaydi.py`; sonuç biçimi: madde numarası + çalıştı/yarım/bozuk + gördüğün cümle.

### E.7 Claude'un denetim listesi (GPT PR'larında, hafta içi)
Diff yalnız izinli dosyalar; yerel `python -X utf8 -m modules.validation` tam geçiyor ("Tüm test grupları başarılı."); CI yeşil; `_record_failure`, `JS_GROUPS`, AGENTS.md madde sayısı, tek sahip; hata-kapalı ve yanlış pozitif kontrolü. Güvenlikle ilgili her şey (45a, 46, 47, 51) Hamdi onayından sonra birleşir.

---

## F. Hamdi'nin karar vermesi gereken sorular (en fazla 5)

1. **Belgenin "Capability Manifest/Registry"si ile projedeki "Araç sözleşmesi/Harita" tek sistem mi olsun?**
   - **(a) Evet, tek sistem: manifest = `CONTRACT`'ın genişletilmişi, registry = Harita arka ucu** (ÖNERİ)
   - (b) Hayır, ayrı yeni Manifest/Registry kurulsun
2. **Kimlik/Self Model ne zaman?**
   - **(a) Küçük sürüm hemen sözleşme omurgasından sonra (8-12 numara): modelsiz "yeteneklerini göster" + ≤10 maddelik sabit kimlik metni** (ÖNERİ)
   - (b) Önce Faz B canlı kabul, kimlik sonra
   - (c) Tam Personality/Relationship katmanı şimdi
3. **Motor birleştirme (iki yürütücüyü tek yapma, adım 4) hangi seçenekle?** Seçenek A / B (`motor-birlestirme-tasarim`). **Öneri: önce PC'de B-bölümü taban çizgisini dene, sonra seçenek A (task_agents işçi olarak kalsın, yaşam döngüsü goal_executor'a geçsin)** [T: raporun tamamını burada yeniden özetlemedim, gerekirse oradaki öneri esas alınsın]; Hamdi onayı bekliyor.
4. **"Jarvis kendi yeteneğini yazar" (Builder) şimdi planda mı?**
   - **(a) Hayır, en erken araç sihirbazı (54-57) oturduktan ve 2 araç PC'de geçtikten sonra; yalnız insan onaylı taslak PR, yüksek riskli sınıflar yasak** (ÖNERİ)
   - (b) Evet, Harita pilotuyla birlikte başlasın
5. **Kota ve donanım önceliği:** günlük kullanıcı çağrı sınırı + anlaşılır "kota doldu" mesajı + Ollama'sız mesaj (E.1 madde 6) kimlik/arayüz işlerinden **önce** mi?
   - **(a) Evet, önce** (ÖNERİ; kota PC'de 20 Ekim'de fiilen iş durdurdu)
   - (b) Sonra, Gemini faturalandırma açılırsa gerek kalmaz (maliyet kararı: ücretli kota açma)

Ek not (karar değil): yazıcı modeli/OctoPrint var mı bilgisi yalnız Görev 52'ye gelince sorulacak (genel plan §6).
