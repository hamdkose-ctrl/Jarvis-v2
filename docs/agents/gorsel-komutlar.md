# Görsel komutlar

## Güncel canonical akış — PR3C-6 (5 Kasım 2026)

PR #521 sohbetten gelen görsel talebinin erken `visual_chat` keyword kapısını kaldırıp isteği Brain → Core sınırına taşır. **Bu henüz model-birincil semantik anlama değildir:** mevcut PR'da Brain'in görsel tür önerisi `brain_understanding._visual_kind` ve `visual_types.match_type` içindeki bounded regex gramerine dayanır. Genel doğal dilde modelin birincil karar sahibi olması BRAIN-01 kapsamındadır.

1. modules/visual_types.py yedi kapalı görsel türü ve ortak Türkçe/İngilizce tür sözlüğünü sağlar.
2. modules/brain_understanding.py mevcut sınırlı görsel grameri eşleşirse visual.create + kind önerir. Tür adı tek başına yeterli değildir; bu PR'da kapalı action cue veya "süreç özeti" özel grameri gerekir. Bu sınırlı eşleşme, kalıp dışı doğal Türkçe desteği iddiası değildir. "infografik nedir?" gibi bilgi soruları CHAT kalır.
3. modules/brain_core_map.py kind değerini yedi türlük allowlist'e göre yeniden doğrular; engine_intents.visual_create mevcut görsel akışına dispatch eder.
4. visual_chat.begin yalnız "sohbetten mi, dosyadan mı?" kaynak sorusunu açar. Kaynak cevabı gelmeden image generation çağrısı yapılmaz. visual_chat.handle yalnız Brain tarafından sahiplenilmiş pending source cevabını ve son görsel için retry'ı yönetir; sohbet türü seçmez.
5. "sohbet" cevabı bounded geçmişi içerik yapar; "dosya" cevabı kullanıcıyı Dosyalar ekranındaki açık Görselleştir düğmesine yönlendirir. Dosyalar ekranı düğmesi kendi açık türünü verir ve bu chat sınıflandırmasından bağımsızdır.
6. Üretim mevcut image_gen/Cloudflare yapılandırmasını kullanır; yeni sağlayıcı, ücretli fallback veya yeni yetki eklenmez. Üretilen PNG mevcut Görseller klasörüne kaydedilir.

Açık PC sahibi protokolü (ör. "pc görevi: infografik çiz") görsel tür eşleşmesinden önce korunur. Core-owned `visual_create` planı eski Planner ve `_extra_commands` cascade'inin aynı isteği ikinci kez yorumlamasını engeller.

PR #521 test-first olarak açık/Draft durumundadır. Exact-head Windows CI ve aynı SHA gerçek PC watcher kabulü geçmeden cutover kabul edilmiş/merge edilmiş sayılmaz.

Aşağıdaki 25 Ekim bölümleri tasarım ve tarihsel uygulama notlarıdır; güncel sahiplik için bu bölüm ve PR #521 esas alınır.

## Tarihsel karar notu — Görsel üretimi v1 (25 Ekim 2026)

## Görsel üretimi v1 — 25 Ekim 2026

`modules/image_gen.py`: kullanıcının doğal dille istediği bir görseli
(mindmap/akış şeması/infografik/zaman çizelgesi/el yazısı/teknik çizim/
genel görselleştirme — 7 tür, Hamdi'nin kararıyla hiçbiri literal bir
komut adı değil, "süreç özeti" gibi doğal ifadeyle tetiklenecek) üretmek
için Cloudflare Workers AI'nin FLUX modelini çağıran, salt üretim/iletişim
katmanı.

**Neden Cloudflare, neden Gemini değil:** Gemini'nin güncel görsel üretim
modellerinde (Nano Banana ailesi: `gemini-nano-banana-2.1`,
`gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image`) ücretsiz katman
yok, hepsi resim başına ücretli. `AGENTS.md`'deki "ücretli sağlayıcılar
otomatik havuza girmez" kuralı nedeniyle varsayılan olarak kullanılmadı.
Cloudflare Workers AI'nin FLUX modeli (`@cf/black-forest-labs/flux-1-schnell`)
kredi kartı istemeden günlük 10.000 Neuron ücretsiz kota veriyor (resim
başına ~14 Neuron, günde kabaca birkaç yüz görsel).

**Anahtar deseni:** `modules/llm.py`'deki `user_key`/`user_groq_key` ile
birebir aynı — kullanıcıya özel, `privacy.protect` ile korumalı, ayrı
dosyalarda (`<kullanıcı>.cf_account.txt`, `<kullanıcı>.cf_token.txt`)
saklanan Cloudflare hesap kimliği + API token. Kullanıcılar arası fallback
yok; anahtarı olmayan kullanıcı için `NO_KEY` hatasıyla reddedilir.

**Kapsam dışı (bilinçli):** Bu modül hangi görselin ne zaman, hangi
prompt'la isteneceğine karar vermez — doğal dil tetikleme ve 7 görsel
türü için prompt/orkestrasyon katmanı ayrı bir iş olarak planlandı, henüz
yazılmadı. Çizimi her zaman model yapar; kod hiçbir pikseli kendisi
çizmez (Hamdi'nin açık kararı).

**Doğrulama:** `tests/test_image_gen.py` (13 test, ağa çıkmaz — sahte
`_session` ile). Ayrıca elle, gerçek bir PNG baytı (1×1 piksel) ile
uçtan uca akış (URL/Authorization header/yanıt çözümleme) çalıştırılıp
doğru PNG imzasıyla (`\x89PNG`) döndüğü doğrulandı. Gerçek Cloudflare
API'sine canlı çağrı bu sandbox'ın ağ izin listesi dışında olduğu için
yapılamadı — bu, Hamdi'nin PC'sinde ayrıca denenmeli.

## Tür tespiti ve teslim v1 — 25 Ekim 2026

`modules/visual_commands.py`: Hamdi ile konuşularak netleşen tasarım:

- **Tetikleme — hibrit:** önce ücretsiz sabit kelime kalıbı
  (`detect_type_by_keyword`); hiçbiri uymazsa modele bir kez sorulur
  (`detect_type_via_model`, kota yalnız bu durumda harcanır).
- **İçerik kaynağı:** Dosyalar ekranındaysa açık dosya/rapor otomatik
  kullanılır; sohbetteyse Jarvis "sohbetten mi, dosyadan mı?" diye
  sorar — bu soru-cevap akışı (`engine_commands.py`'ye bağlanma) henüz
  yazılmadı, `create_visual()` şimdilik içeriği hazır metin olarak alır.
- **Teslim:** üretilen PNG sohbete değil, mevcut Dosyalar ekranının
  zaten taradığı `Jarvis Dosyaları/Görseller` klasörüne kaydedilir —
  yeni bir ekran kurulmadı, var olan `PAGES.files` (nxapi.FILES_DIR)
  aynen kullanıldı.
- **Kalite:** kötü sonuçta kullanıcı yeniden deneyebilsin istendi;
  "yeniden dene" düğmesi/akışı da sohbet entegrasyonuyla birlikte
  yapılacak, henüz yok.

**Doğrulama:** `tests/test_visual_commands.py` (21 test, ağa/modele
çıkmaz). Tam paket (`modules.validation`): değişiklik öncesi/sonrası
aynı 1 failure/87 error (sandbox'ın önceden var olan `google-genai`
eksikliği) — regresyon yok. Bir gerçek hata bu PR'da bulundu ve
düzeltildi: `detect_type_via_model`'deki geniş `except Exception`
tanılama kaydı (`_record_failure`) tutmuyordu (proje kuralı:
`test_cleanup_security.test_every_broad_catch_has_diagnostic`).

## Sohbet entegrasyonu v1 — 25 Ekim 2026

`modules/visual_chat.py` (`command_manager.dispatch`'e bağlı, `desktop_agent`
gibi aynı seviyede): önceki PR'da bilinçli olarak dışarıda bırakılan
kısım tamamlandı.

- **Sohbette tetikleme:** `visual_commands.detect_type` eşleşirse
  `session.pending_visual` ile "sohbetten mi, dosyadan mı?" sorulur.
  "sohbet" → son konuşma geçmişi (`context.history_read`) içerik olur.
  "dosya" → kullanıcı Dosyalar ekranındaki "Görselleştir" düğmesine
  yönlendirilir (dosya adı çözümleme burada tekrar kurulmadı, tek
  yerde — Dosyalar ekranında — tutuldu).
- **Dosyalar ekranından tetikleme:** `nxapi.ACTIONS['gorsellestir']`
  ("dosyasını görselleştir") + `main_documents._file_command`: açık
  dosyanın `runtime.docs.summarize()` özeti içerik olur, soru
  sorulmaz (Hamdi'nin kararı: "Dosya kısmında olduğum için sohbeti
  sormaması gerekmiyormuş"). Eylem metninde tür kelimesi geçiyorsa
  ("...zaman çizelgesi olarak görselleştir") o tür zorlanır, yoksa
  `visualize` (genel) türüne düşer.
- **Yeniden dene:** `session.last_visual` son içerik+türü tutar;
  "yeniden dene"/"tekrar dene" aynı parametrelerle yeniden üretir
  (Hamdi: "tabii ki tekrar denesin, kota harcar ama sonuç olmadıktan
  sonra ne işe yarar").
- `webui/nx.js`: Dosyalar ekranına PDF/Word/Excel/Diğer satırlarına
  ve detay panelinin Yapay Zekâ sekmesine "Görselleştir" düğmesi
  eklendi; "Nasıl çalışır?" açıklamasına bir satır eklendi.

**Doğrulama:** `tests/test_visual_chat.py` (12 test — pending-soru
akışı, yeniden dene, hata yönetimi, Dosyalar ekranı eylemi; hepsi
sahte `create_visual` ile, ağa çıkmaz). Bir gerçek hata bulundu ve
düzeltildi: `detect_type_via_model`'de `from modules import llm`
import'u `try` bloğunun DIŞINDaydı — bu sandbox'ta `google-genai`
eksikliği yüzünden `ImportError` try/except'i atlayıp doğrudan
patlıyordu; import artık `try` içinde. Ayrıca `visual_chat.py`'deki
bir `except Exception`'da tanılama kaydı ilk ifade olmadığı için
proje testi (`test_cleanup_security`) yakaladı, düzeltildi.

Tam paket: `_file_command` üzerinden geçen 2 yeni test, bu sandbox'ta
zaten var olan `modules.llm`/`google-genai` eksikliğine çarpıyor
(`test_translation_regressions.py`'deki eşdeğer test de aynı şeyi
yapıyor, kontrol edildi) — gerçek bir regresyon değil, PC'de sorun
olmaz. 1 failure/89 error (87+2), öncekiyle aynı kategori.

**Hâlâ kapsam dışı:** gerçek Cloudflare API'sine canlı çağrı (sandbox
izin vermiyor, PC'de denenmeli); sohbetten "dosya" cevabında dosya
adını doğrudan chat'te yazdırıp otomatik çözme (şimdilik Dosyalar
ekranına yönlendiriliyor).

### Windows CI düzeltmesi — 25 Ekim 2026

Gerçek Windows CI'da (bu sandbox'ta değil — orada `google-genai`
gerçekten kurulu) iki gerçek hata çıktı, Hamdi'nin paylaştığı log'dan
bulundu:

1. `visual_chat.handle`, `session.pending_visual`/`last_visual`'e
   doğrudan öznitelik erişimiyle bakıyordu. `test_command_manager.py`
   gibi bazı eski testler `session`'ı hafif bir `SimpleNamespace` ile
   taklit ediyor (yalnız o testin ihtiyacı olan alanlarla) — bu
   alanlar orada yoktu, `AttributeError` fırlıyordu. Düzeltme:
   `getattr(session, "...", None)`.
2. Bu PR'ın kendi testindeki (`FileButtonGorsellestirTests._runtime`)
   sahte `runtime` nesnesinde `tr` alanı unutulmuştu;
   `_file_command` her eylemde `runtime.tr.target_from_command(act)`
   çağırıyor (üretimde `runtime.tr` her zaman var, bu yalnız test
   fixture'ının eksikliğiydi). Düzeltme: fixture'a gerçek
   `modules.translate` eklendi.

Doğrulama: bu sandbox'ta `google.genai`/`google.genai.types` sahte
modüllerle (gerçek davranış değiştirilmeden, yalnız import zincirini
açmak için) taklit edilip tüm paket (2446 test, `unittest discover`)
çalıştırıldı — her iki düzeltmeden sonra kalan tek hata ilgisiz bir
alt-süreç testiydi. Normal (taklitsiz) ortamda tam paket tekrar 1
failure/87 error'a döndü — PR açılmadan önceki orijinal baseline ile
birebir aynı, hiç fazladan hata yok.

### Sohbette gereksiz model çağrısı düzeltmesi — 25 Ekim 2026

Yukarıdaki iki düzeltmeden sonra Windows CI'da farklı, daha önemli bir
hata çıktı: `tests/developer_smoke.py` geliştirme modu testi, cevapta
beklenen `\`\`\`diff` ve `data:image/svg+xml;base64,` metinlerini
bulamayıp başarısız oldu.

Kök neden: `visual_chat.handle`, `command_manager.dispatch`'in en
başında HER sohbet mesajında çalışıyor. Sabit kelime kalıbı
(`detect_type_by_keyword`) uymazsa `detect_type` otomatik olarak
modele bir kez soruyordu ("bu bir görsel isteği mi?") —
`gorsel-komutlar.md`'nin "Tür tespiti" bölümünde bu model çağrısı
"nadiren" ve yalnız açık bir eylemde (Dosyalar ekranındaki
"Görselleştir" düğmesi) harcanması amaçlanmıştı. Ama sohbete bağlanınca
bu, kalıba uymayan HER normal cümle için (ör. geliştirme modunda model
araç çağrısı üretirken) fazladan bir Gemini isteği anlamına geliyordu
— hem `AGENTS.md`'deki "gereksiz Gemini çağrısı eklenmez (kota)"
kuralına aykırı hem de geliştirme modunun kendi model çağrı sırasını
bozup testi patlatıyordu (test, `dev.llm.ask`'i sahte sabit bir cevap
listesiyle değiştiriyor; araya giren bu ekstra çağrı listeyi kaydırdı).

Düzeltme: `visual_chat.handle`'daki otomatik sohbet tetiklemesi artık
yalnız ücretsiz `detect_type_by_keyword`'ü kullanıyor, model
fallback'ine (`detect_type_via_model`) hiç düşmüyor. Dosyalar
ekranındaki "Görselleştir" düğmesi (`main_documents._file_command`)
zaten sabit "görselleştir" kelimesiyle `visualize` türüne eşleştiği
için bu değişiklikten etkilenmedi — model çağrısı o yolda zaten hiç
tetiklenmiyordu.

Doğrulama: `tests/developer_smoke.py` gerçekten çalıştırılıp (sahte
`google.genai` ile) düzeltmeden önce başarısız, sonra geçtiği
doğrulandı. `tests/test_visual_chat.py` + `tests/test_visual_commands.py`
(33 test) hepsi geçti. Tam paket (`modules.validation`) bu sandbox'ta
görsel/ses modülleriyle ilgisiz, önceden var olan sahte-modül
eksikliklerinde (13 failure/25 error, hem düzeltme öncesi hem sonrası
birebir aynı sayı) duruyor — bu değişiklikten kaynaklı yeni bir hata
yok.

## Dosyalar ekranına açıklama sekmesi — 25 Ekim 2026

`webui/nx.js` `PAGES.files`'a "Nasıl çalışır?" düğmesi eklendi
(`ACT.fhelp`): dosya yükleme, arama, yapay zekâ araçları, dosya
listesi/detay paneli ve kategori filtrelerini düz dilde açıklayan bir
pencere açar. Saf arayüz değişikliği, backend'e dokunmadı;
`node --check webui/nx.js` ile sözdizimi doğrulandı.
