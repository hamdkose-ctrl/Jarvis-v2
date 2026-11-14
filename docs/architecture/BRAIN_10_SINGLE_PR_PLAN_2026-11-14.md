# BRAIN-10 — doğrulanmış sonuç, cevap ve görünürlük; tek PR

Hamdi #628 temizse merge ve BRAIN-10'u aynı şekilde tek PR'da istedi. #628 kabul edilmiş3354526 kaynağı WindowsCI43572580953 + gerçekPC6874150892 PASS sonrası main `f77ecb020f44476447f39241822398f635155f38` olarak birleşti. Başlangıç açık PR listesi boş; bu main taban alınır. Brain anlamı, Core completion/izin/etkiyi yönetir; sunum yeni iş başlatmaz.

## İki seçenek ve karar

A: İkinci model-verifier/response agent, yeni store ve tamamlanma motoru. Ek model çağrısı, sahte authority ve scope karışıklığı getirir; seçilmedi.
B: Mevcut task_results/goal_tools/domain doğrulayıcıları ve canonical WorkerResult/Core kanıtı korunur; tek salt-okunur sonuç görünümü mevcut render/summary/teslim/sorgu yollarına bağlanır. Persona yalnız doğrulanmış verinin üslubunu/boyunu etkiler. Seçilen B'dir.

## Kodda doğrulanan açıklar

- task_agents.render_summary done bayrağını ve raw output'u güvenli kanıt yerine kullanabiliyor; herhangi bir empty inbox çıktısında erken return sonraki başarısız işi saklıyor. Başarısız son child tüketilmiş saydığı doğrulanmış parent çıktısını gizleyebiliyor.
- goal_executor.render/status_summary genel sonuç/dosya yollarını teslim anında yeniden doğrulamadan başarı sayabiliyor; partial_report yolu da yalnız state/file alanıyla sunuluyor.
- task_results.verify beklenen worker türünü dışarıdan bağlamıyor; metadata agent başka kind'a çevrilirse yanlış kanıt ailesi seçilebiliyor. Genel research kaynak alıntısı ve yerel PC receipt sınırları sunumda korunmalı.
- canonical_goal_flow.read_completed_result bütün accepted output'ları kontrol ediyor ama normal finished durumda dolu frozen result metnini yeniden hesaplamadan okuyabiliyor; sahte cached başarı metni kabul edilebiliyor.

## Dikey kapsam ve üretim akışı

1. Mevcut domain verifier'larına expected-kind/owner bağı, artifact/source/receipt readback. Dosya digest/kaynak, araştırma quote/tarih/claim kanıtı, Outbox accepted receipt ve PC'nin doğrulanmış native adım snapshot'ı kendi sahiplerinde kalır. Eski kanıtsız done kaydı otomatik başarı/yeniden yürütme yaratmaz.
2. Salt-okunur sonuç view'u done/partial/waiting/unknown/failed/cancelled, doğrulanmış bağımsız çıktılar, eksik/ret nedeni ve artifacts verir. GoalState/ExecutionRecord/lifecycle yazmaz; provider/native etki veya yeni model çağırmaz.
3. Mevcut task summary ve goal render/status kullanıcı akışı: geçersiz success yerine açık doğrulanamadı; bağımsız doğru çıktılar kısmi görünür; boş mail daha sonraki hatayı gizlemez; progress sayacı doğrulanmış adımdır. Teknik journal açık ayrıntı yolunda korunur, normal cevap raw dahili alan dökmez.
4. Persona-aware response deterministik; kısa/uzun tercihi kayıt/gerçek/scope değiştirmez. Kaynak URL/tarih, dosya yolu, bekleme/onay/unknown ve truncation açıklaması korunur. Aynı Core result/event kimliği ve existing notify owner kullanılır.
5. Canonical final yanıtı ve torn-after-CAS okuma aynı accepted output kanıtından yeniden üretilir; frozen style yalnız kapalı/versioned presentation metadata'sıdır. Sahte cached text, yanlış owner, değişmiş artifact/output, farklı plan ve restart boşluğu fail-closed; otomatik bildirim/worker replay yok.

## Kabul ve sınırlar

Önce RED: değişen dosya, forged/mismatched receipt, yanlış owner/kind, empty-inbox+failed-child, doğrulanmış parent partial, cached metin forgery. Sonra gerçek worker/receipt/Core/render girişleri; yalnız provider/model/cihaz sınırı fake. Required full validation + guard/Ruff/roadmap, exact-source Windows CI ve aynı kaynak gerçekPC watcher kaydedilir. #628 persona yeniden kurulmaz; Router/provider policy/Android/şifre veya gerçek gönderim değişmez. Sesin fiziksel duyulması/AEC/gerçek p95-p99 ve Brain-11 insan tanıklı final ürün kabulü mock/PC validation ile kapanmış sayılmaz.

## Kaynak dondurma öncesi kanıt

İlk exact-source tam koşum4ec368b:6402 Python,1FAIL/3ERROR/1LinuxDPAPIskip. Eski kısa-durum/araştırma fixture'ları owner/step/receipt olmadan başarı varsayıyordu; gerçek sealed kaynak/dosya kanıtına taşındı, özgün gövde/URL/ayrıntı assertion'ları korundu. İncelemede eksik legacy satırın render hatası ve orphan çıktının kaynak/dosya sayacına sızması da kapatıldı. Geçerli alternatif adımla tamamlanmış hedef eski başarısız deneme nedeniyle eksik gösterilmez. Bu üç durum ve ters sıradaki verifier zincirinde geçersiz bağımlılığın yayılması dört ek regresyonla korunur; toplam24 yeni BRAIN-10 testi vardır. Son exact-source tam koşumun sonucu PR'da ayrıca yazılır.

İlk12 regresyon10FAIL/2ERROR ile RED verdi; buna gerçek terminal Core kaydındaki cached text forgery ve dosya/owner/empty-inbox/partial açıkları dahildir. Son kapsam20 yeni regresyon, gerçek dosya ve sealed worker receipt, gerçek Outbox SQLite/provider-fake send/no-resend, mevcut Scheduler/Core accepted result ve archived/frozen query, native PC snapshot, UI query/control identity üzerinden geçer. İlgili270 Python testi PASS; Ekip merkezi JS davranışı ve syntax, Ruff F821/F822/F823, Architecture Guard, roadmap ve diff kontrolleri PASS. Eski bare fixture'lar gerçek owner/sealed receipt/dosyaya taşındı; teknik journal ve Core ret assertion'ları korunur. Son exact-source tam validation/Windows/PC sayıları ve bağlantıları PR metadata'sında ayrıca kaydedilir.

PC snapshot native yürütme anındaki doğrulanmış adımların geçmiş kanıtıdır; sonradan cihazı yeniden kontrol etmek veya başka işi iptal etmek değildir. Araştırma claim kontrolü alıntıdaki değer/kapsam sözleşmesini ve mevcut tarih/claim domain sahibini kullanır; bağımsız bilimsel doğruluk hakemi değildir. Provider accepted receipt teslim/okundu/duyuldu anlamına gelmez. View incomplete yalnız sunumdur; Core control kimliği özgün kayıttan hesaplanır. Genel external reconciliation, zorla provider kill, yeni effectful DAG veya Router politikası eklenmez.
