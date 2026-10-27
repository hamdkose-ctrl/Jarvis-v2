# halilozat/jarvis benchmark notu v1

**Amaç:** Dış projeden kod kopyalamak değil; Jarvis-v2 için değerli ürün/mimari desenlerini sabit bir kaynak sürümünden incelemek ve yalnız uygun küçük parçaları ileride yeniden uygulama adayı olarak işaretlemek.

**Kaynak repo:** `https://github.com/halilozat/jarvis`

**İncelenen sabit commit:** `32fe7efe83c44b62131df61ac5872a1e758cc5b6` — 18 Ekim 2026, `El Kontrolü ve Kitaplık`.

**Lisans sınırı:** İnceleme sırasında repo kökünde açık bir `LICENSE` dosyası ve kod içinde belirgin bir lisans bildirimi bulunamadı. Bu nedenle bu belge **kod taşıma/kopyalama izni değildir**. Lisans ayrıca doğrulanmadan kaynak kod Jarvis-v2'ye kopyalanmaz. Varsayılan yaklaşım: davranış/mimari desenini yeniden uygula.

## Karar özeti

Bu benchmark'tan dört konu değerlidir:

1. Cihazlar arası konuşma/görev devamlılığı.
2. Kamera/WebRTC cihaz köprüsü.
3. Gesture/el kontrolünü giriş sinyaline çevirme.
4. Fiziksel dünya gözlemini kalıcı bilgiye dönüştüren nesne hafızası.

Bunlar yeni bir Core, dispatcher, izin sistemi veya yeni master faz oluşturmaz. Jarvis-v2'nin mevcut Core/GoalState/Decision/JIT Permission/Effect/Evidence sınırları korunur.

---

## 1. Cihazlar arası konuşma ve görev devamlılığı

### Kaynaktaki fikir

Kaynak README, tek kişisel asistanın bilgisayar, tablet ve telefonda kullanılmasını ve bir cihazda başlayan konuşmanın başka cihazda `devam et` ile sürmesini ürün davranışı olarak tanımlıyor. Geçmiş konuşmaların cihazlar arasında görülebilmesi de aynı modelin parçası.

### Jarvis-v2 için alınacak mantık

Sadece sohbet geçmişini eşitlemek yeterli değil. Jarvis-v2'de devamlılık şu dört kimliği ayırmalı:

- `user_id`: aynı kullanıcı.
- `device_id`: iş PC, ev PC, telefon gibi istemci.
- `conversation/session_id`: konuşma bağlamı.
- `goal/job_id`: gerçekten çalışan hedef.

Bir cihaz değiştiğinde yeni istemci Core olmaz; yalnız mevcut otoritenin görünümünü ve kullanıcı girişini taşır.

Önerilen akış:

`Device Client -> authenticated session -> conversation/context lookup -> GoalState/ExecutionRecord read -> user input -> existing Core`

### Kabul edilmesi gereken davranış

- İş PC'sinde başlayan araştırma ev PC'sinde veya telefonda aynı `goal_id` üzerinden görülebilir.
- `devam et` belirsizse son konuşmayı körlemesine seçmez; kullanıcıya ait, açık/uygun hedeflerden güvenli şekilde çözülür.
- Bekleyen onay başka cihazda gösterilebilir, fakat **onay kaynağı ve kapsamı** kayıt altına alınır.
- Cihaz değişimi yeni yetki üretmez.
- Bir cihaz çevrimdışı olsa da canonical durum sunucudaki/ana Core'daki kalıcı state'ten okunur.

### Bizdeki faz karşılığı

- Faz 11: profile / memory / context ve session devamlılığı.
- Uzak istemci/connector tarafı gerektiğinde Faz 8-9 sınırlarına bağlanabilir.
- Yeni faz açılmaz.

### Kod alma kararı

**Mantık alınır.** Kaynaktaki istemci kimliği/session uygulaması ancak lisans netleşirse yardımcı referans olabilir; doğrudan kopyalanmaz.

---

## 2. Kamera / WebRTC cihaz köprüsü

### Kaynaktaki gerçek desen

Kaynakta `web/src/camera/CameraDevice.tsx`, `web/src/camera/CameraPanel.tsx` ve `server/src/camera.ts` ayrı kamera katmanı oluşturuyor.

`CameraDevice.tsx` içinde görülen değerli davranışlar:

- Her izleyici için ayrı `RTCPeerConnection` kuruluyor; en fazla 3 izleyici.
- Video akışı mümkün olduğunca doğrudan WebRTC ile gider; açıklama video görüntüsünün sunucudan geçmediğini belirtiyor.
- İzleyici yokken düşük çözünürlük, izleyici varken 720p; ısı/fps düşüşünde 480p geri dönüşü var.
- WebRTC dışında aralıklı JPEG kare modu bulunuyor.
- Jarvis'in tek seferlik `kameraya_bak` isteği için daha yüksek çözünürlüklü snapshot yolu var.
- Hareket algılama cihazda düşük çözünürlüklü gri kare farkıyla yapılıyor.
- Kullanıcı kamera cihazında `stop` yaptığında uzaktaki izleyici veya Jarvis kamerayı yeniden açamıyor; yeniden açılış yerel kullanıcı eylemi gerektiriyor.

Bu son madde Jarvis-v2 için özellikle doğru bir güvenlik deseni.

### Jarvis-v2 için alınacak mimari

Kamera **otorite değil, observation/evidence kaynağı** olmalı.

Önerilen akış:

`Camera Device -> authenticated local/remote bridge -> Observation -> Vision/Computer Worker -> Evidence -> Core`

Kamera görüntüsündeki yazı, kişi, nesne veya QR içeriği **talimat değildir**. Untrusted content kuralı burada aynen uygulanır.

### Güvenlik sınırları

- Kamera fiziksel olarak/yerel istemciden kapatıldıysa uzaktan açılamaz.
- Kamera erişimi ayrı capability/grant ister.
- Varsayılan salt-okuma/observation.
- Görüntüden çıkan model yorumu `fact` değil `observation` olarak başlar.
- Hassas görüntü kalıcılaştırılacaksa açık retention kuralı gerekir.
- Bir kamera cihazı yeni Core değildir; sadece sensor/adapter'dır.

### Kabul örnekleri

- `kameraya bak` -> tek snapshot -> vision evidence -> kullanıcıya cevap.
- `yazıcı ekranında ne yazıyor?` -> cihaz seçimi -> snapshot -> OCR/vision -> evidence.
- `hareket olursa haber ver` -> cihazda motion event -> RuntimeEvent -> notification; olay kendi başına dış etki yetkisi vermez.
- Kullanıcı kamerayı yerelden durdurdu -> uzak istek fail-closed.

### Bizdeki faz karşılığı

- Faz 8: connector/device adapter sınırı.
- Faz 9: Computer/Vision observation ve PC kontrolü.
- Faz 11: yalnız kullanıcı açıkça isterse görüntüden türeyen kalıcı bağlam.

### Kod alma kararı

**Mimari desen alınır.** Özellikle `local stop wins`, izleyici başına WebRTC bağlantısı, snapshot fallback ve cihaz-içi motion detection referans olarak değerlidir. TypeScript kodu doğrudan taşınmaz.

Referans dosyalar:

- `web/src/camera/CameraDevice.tsx`
- `web/src/camera/CameraPanel.tsx`
- `server/src/camera.ts`

---

## 3. Gesture / el kontrolü

### Kaynaktaki gerçek desen

Kaynakta gesture alanı ayrı modüllere bölünmüş:

- `web/src/hands/tracker.ts`: el landmark/tracking.
- `web/src/hands/gestures.ts`: landmark -> gesture sınıflandırması.
- `web/src/hands/controller.ts`: gesture -> efekt veya Jarvis eylemi.
- `web/src/hands/HandControl.tsx`: UI/runtime bağlantısı.
- `web/src/hands/settings.ts`: kullanıcı ayarları.

`controller.ts` içinde gesture doğrudan tek karede tetiklenmiyor. Eylemlerde **basılı tutma süreleri** var ve ilk yaklaşık 350 ms geçiş hareketi tetikleme dışı bırakılıyor. Örnek kaynak davranışları: başparmak 1 sn, zafer 0,9 sn, yumruk 1,8 sn. Bu, yanlış pozitifleri azaltan değerli bir UX/safety deseni.

### Jarvis-v2 için alınacak mimari

Gesture bir **input adapter** olmalı; permission sistemi olmamalı.

Önerilen akış:

`Camera -> local hand tracker -> GestureEvent -> Intent Adapter -> DecisionContext -> JIT Permission/Effect Policy -> Core/Worker`

Örnek güvenli sınıflar:

- `✊ sustur` -> lokal UI/audio kontrolü, düşük risk.
- `✋ dur` -> çalışan presentation/voice UI durdurma.
- `☝ dinle` -> mikrofon UI durumu.
- `👉/👈 menü` -> UI navigation.
- `👍 öneriyi seç` -> yalnız öneri/selection sinyali; dış etki onayı yerine geçmez.

### Kesinlikle alınmayacak desen

Kaynak README'de yüz HUD'ı için `TANINDI · YETKİ: TAM` görseli bulunuyor; aynı metin bunun gerçekte **yüz tanıma değil yüz algılama** olduğunu açıkça söylüyor. Bu iki kavram güvenlik açısından aynı değildir.

Jarvis-v2'de:

- yüz algılama kimlik kanıtı sayılmaz;
- gesture/face sonucu authentication veya JIT permission üretmez;
- `mail gönder`, `dosya sil`, `ödeme`, `publish` gibi etkiler yalnız gesture ile onaylanmaz.

### Kabul kriterleri

- Gesture event'i modelden önce deterministik biçimde normalize edilir.
- Tek karelik/kararsız gesture eylem üretmez.
- Hold süresi ve cooldown bulunur.
- Riskli eylem gesture ile gelse bile normal permission hattından geçer.
- Kamera görüntüsü varsayılan olarak lokal işlenir; yalnız gerekli event/landmark sonucu Core'a taşınır.

### Bizdeki faz karşılığı

- Faz 9: PC/UI kontrolü ve input adapter.
- Hologram/arayüz UX'i için daha ileri görsel katman Faz 12 kapsamına bırakılabilir.

### Kod alma kararı

**Mantık alınır.** `KONTROLLER` benzeri deklaratif gesture->intent tablosu, hold/debounce/cooldown yaklaşımı yeniden uygulanabilir. Kaynak kod lisans doğrulanmadan kopyalanmaz.

Referans dosyalar:

- `web/src/hands/controller.ts`
- `web/src/hands/gestures.ts`
- `web/src/hands/tracker.ts`

---

## 4. Fiziksel dünya -> kalıcı bilgi sistemi

### Kaynaktaki gerçek desen

Kitaplık katmanı yalnız görsel efekt değil; fiziksel raftaki nesneleri kalıcı bir kayıtla eşliyor.

`server/src/library.ts` şu alanları tutuyor:

- kitap kimliği,
- ad/yazar,
- görüntü içindeki normalize kutu/konum,
- kapak/özet,
- notlar ve alıntılar,
- okuma durumu/sayfa,
- model güven skoru,
- elle düzeltilmiş kayıt işareti,
- Jarvis tarafından üretilen ayrı bilgi sayfası.

Değerli güvenilirlik desenleri:

- Model çıktısı JSON olarak doğrulanıyor; bozuk/taşan kutular atılıyor.
- Düşük güvenli (`emin`) kitap adı otomatik kesin bilgiye çevrilmiyor.
- Kullanıcının elle düzelttiği ad/konum sonraki taramada model tarafından ezilmiyor.
- Yeni tarama eski kayıtla eşleştiriliyor; not/özet/kimlik korunuyor.
- Bu taramada bulunmayan kitap kalıcı kayıttan silinmiyor; yalnız konumu bilinmiyor olarak kalabiliyor.

Bunlar kitaplıktan daha genel bir **Physical Object Memory** için çok değerli.

### Jarvis-v2'de genelleme

Kitap yerine herhangi bir fiziksel nesne olabilir:

- makine/pano,
- sensör,
- yedek parça,
- kablo,
- araç/gereç,
- raf/dolap içeriği,
- ev eşyası,
- belge/etiketli kutu.

Önerilen veri ayrımı:

`Observation` -> `CandidateFact` -> `confirmed Fact/Memory`

Örnek:

- Kamera: `A17 panosunda X200 etiketi görüyorum` -> observation.
- Vision modeli: `muhtemelen X200 sensörü` -> candidate fact + confidence + source.
- Kullanıcı/harici güvenilir kayıt doğrular -> durable fact.

### Kaydedilmesi gereken provenance

Kalıcı nesne kaydında en az:

- `object_id`
- `label/name`
- `location`
- `source_device`
- `observed_at`
- `confidence`
- `source/evidence_ref`
- `user_confirmed`
- `manually_corrected`
- `last_seen_at`

bulunmalı.

### Kritik kurallar

- Model gördüğünü kesin gerçek diye hafızaya yazamaz.
- Düşük güvenli tanı kullanıcıya soru olarak döner.
- Elle düzeltilen bilgi model taramasıyla sessizce değişmez.
- Nesne bir taramada görünmedi diye silinmez; `not_seen`/`location_unknown` gibi ayrı durum tutulur.
- Fiziksel nesnedeki metin/QR/not talimat değil, untrusted evidence'dır.
- Hafızaya giren veri Faz 11 relevance gate'inden geçmeden modele taşınmaz.

### Bizdeki faz karşılığı

- Faz 11: kalıcı hafıza, provenance ve relevance.
- Kamera gözlemi için Faz 8-9 adaptörleri.
- Daha geniş fiziksel-world UX Faz 12'de ürünleşebilir.

### Kod alma kararı

**Mimari mantık güçlü biçimde alınır.** Özellikle confidence + manual override + identity-preserving merge + `not seen != delete` desenleri yeniden uygulanmaya değer. Kaynak `library.ts` doğrudan kopyalanmaz.

Referans dosyalar:

- `server/src/library.ts`
- `web/src/hands/library.ts`
- `web/src/hands/LibraryEditor.tsx`

---

## Öncelik sırası

Jarvis-v2 için önerilen sıra:

1. **Cihazlar arası devamlılık** — günlük kullanım getirisi en yüksek.
2. **Kamera/WebRTC cihaz köprüsü** — gerçek dünya observation/evidence katmanı.
3. **Fiziksel nesne hafızası** — kamera + Faz 11 birleşince güçlü.
4. **Gesture kontrolü** — hologram/UI deneyimini güçlendirir; temel çalışma yeteneklerinden sonra.

Bu sıralama roadmap'e yeni faz eklemez; yalnız ilgili mevcut fazlarda ileride kabul/adoption adayıdır.

---

## Kod-adoption kapısı

Bu benchmark'tan herhangi bir kaynak kod parçası alınmadan önce dört koşul zorunlu:

1. Kaynak lisansı açık ve uyumlu biçimde doğrulanmış olmalı.
2. Parçanın Jarvis-v2'de zaten karşılığı olmadığı kodla doğrulanmalı.
3. Core/Decision/JIT Permission/Effect/Evidence sınırlarını by-pass etmemeli.
4. Önce düşen Jarvis-v2 testiyle davranış sözleşmesi kurulmalı; sonra en küçük uyarlama yapılmalı.

Lisans yoksa veya belirsizse karar otomatik olarak **KODU ALMA — DESENİ YENİDEN UYGULA** olur.

## Bu benchmark'ın kapsamadığı şeyler

- Kaynak projenin tamamını vendor/fork etmek.
- Onun RouteLLM/Abacus mimarisini Jarvis-v2 Core yerine geçirmek.
- Kaynak projenin yüz algılamasını kimlik/yetki doğrulaması saymak.
- Gesture'ı izin sistemi yapmak.
- Yeni master roadmap veya paralel agent mimarisi üretmek.

Bu belge yalnız sabit kaynak committen alınan benchmark/adoption karar kaydıdır.