# Jarvis File/DocumentWorker Read-Only Benchmark v1

## Durum ve amaç

Bu belge, gelecekteki `FileWorker` / `DocumentWorker` adaylarını aynı dar güvenlik, kanıt ve fail-closed ölçütleriyle değerlendirmek için ilk salt-okunur benchmark sözleşmesini tanımlar. Yeni worker, parser, OCR provider, model entegrasyonu, runtime veya UI eklemez; mevcut dosya/belge okuma kodunu değiştirmez.

Kaynak-doğrulanmış mevcut sınır, Jarvis’in belge okuma ve benchmark altyapısının ayrı sorumluluklarını korur:

- `modules/docs.py` mevcut belge okuma katmanıdır; PDF/DOCX/XLSX/XLSM/PPTX/CSV/HTML/TXT/MD/RTF/ODT/JSON gibi biçimleri okur ve `read_document()` ile metin çıkarımı sağlar.
- PDF metni `read_pdf_isolated()` ile ayrı Python sürecinde, sayfalar form-feed ile ayrılarak okunur; bu yol belge okumasıdır, benchmark evaluator değildir.
- CSV yerel `csv` okuyucusuyla, Türkçe kodlama ve ayraç dikkate alınarak okunur.
- XLSX/XLSM için mevcut kod read-only `openpyxl` yolları kullanır; `modules/workbench.py.load_table()` çalışma kitabını `read_only=True, data_only=True` açar ve yalnız hücre değerlerini okur.
- `modules/worker_result.py` WorkerResult v1 sonucunu immutable execution fence ile doğrular; `accept()` her fence alanı tam eşleşmeden sonucu kabul etmez ve GoalState yazmaz.
- JarvisBench v0 (`modules/jarvis_bench.py`) worker çalıştırmayan saf evaluator’dır; önceden üretilmiş observation’ı evidence, safety/permission sonucu ve süre ile değerlendirir. Benchmark sonucu Core completion veya GoalState kararı değildir.

Bu belge bu mevcut yolları yeni capability gibi yeniden adlandırmaz; yalnız gelecekteki File/DocumentWorker adaylarının hangi read-only davranışlarla ve hangi evidence gereksinimleriyle ölçüleceğini sabitler.

## İlk kapsam: yalnız read-only dosya/belge gözlemi

İlk benchmark aşağıdaki dört capability sınıfıyla sınırlıdır.

### 1. Dosya listeleme

Benchmark, önceden belirlenmiş bir klasör veya dosya kümesindeki girdilerin yalnız okunmasını değerlendirir. Amaç hedef dosyanın varlığını, adını, türünü ve case’in izin verdiği kapsamda listelenebilirliğini gözlemlemektir.

Bu sözleşme yeni bir klasör tarayıcı veya dosya sistemi API’si tanımlamaz. Kullanılan listeleme yolu mevcut koddaki read-only dosya erişim davranışlarından türetilmelidir. Bir aday, benchmark için özel bir yazma/geçici dosya üretme yolu açamaz.

### 2. Metadata okuma

Metadata gözlemi yalnız dosya sisteminden güvenle okunabilen nitelikleri kapsar. Örnek sınıflar:

- dosya adı ve uzantı,
- tam/normalize yol veya benchmark tarafından tanımlanmış file identity,
- dosya boyutu,
- değişiklik zamanı gibi filesystem metadata,
- desteklenen belge türü bilgisi.

Metadata okuma, içeriğin doğru okunduğunu tek başına kanıtlamaz. PASS için case içerik evidence’ı istiyorsa yalnız metadata yeterli değildir.

### 3. Metin/PDF içeriğinden read-only çıkarım

`modules/docs.py` mevcut kaynak-doğrulanmış belge okuma yoludur. İlk File/DocumentWorker benchmarkı bu davranışı genişletmeden aşağıdaki gözlemleri ölçebilir:

- düz metin ve mevcut desteklenen metinsel belge biçimlerinden çıkarılan metin,
- PDF’de pypdf tabanlı metin çıkarımı,
- mümkün olduğunda PDF sayfa sınırlarının korunması (`keep_pages=True` / form-feed ayrımı),
- kaynak içerikten case’in önceden tanımladığı literal veya yapısal kanıtın bulunması.

PDF okuma başarılı görünse bile boş/eksik metin, sayfa eşlemesinin kaybolması veya extractor hatası tahminle başarıya çevrilemez.

### 4. CSV/XLSX içeriğinden read-only çıkarım

Mevcut kaynak kodda CSV ve XLSX okuma yolları vardır:

- `modules/docs.py` CSV’yi yerel `csv` okuyucusuyla okur.
- `modules/workbench.py.load_table()` `.xlsx`/`.xlsm` dosyalarını `openpyxl.load_workbook(..., read_only=True, data_only=True)` ile açar ve yalnız hücre değerlerini okur; CSV için de salt-okunur satır okuma uygular.

İlk benchmark yalnız tablo başlığı, satır/hücre değerleri ve case’in önceden belirlediği kaynak hücre/satır kanıtını gözlemleyebilir. Formül çalıştırma, makro yürütme, workbook’a değer yazma veya kayıt etme kapsam dışıdır.

## Açık yasaklar

Bu benchmark sözleşmesi aşağıdaki yetkileri vermez:

- dosya oluşturma veya mevcut dosyaya yazma,
- dosya silme,
- dosya taşıma veya yeniden adlandırma,
- export veya başka formata yazma,
- dosyayı e-posta, mesaj, bulut, web veya başka bir dış hedefe gönderme,
- upload,
- belgeyi değiştirme, biçimlendirme veya kaydetme,
- OCR/model/provider çağrısını otomatik olarak başarı sayma,
- model özetini kaynak evidence yerine kabul etme,
- GoalState veya başka canonical state yazma,
- Core completion sonucunu worker/benchmark tarafından doğrudan belirleme,
- permission veya effect policy’yi atlama.

Mevcut `modules/workbench.py` çıktı Excel/Word/PDF üretebilen daha geniş bir belge işleme yüzeyine sahiptir; bu benchmark o yazma/export yüzeyini kullanmaz. Yalnız mevcut salt-okunur okuma parçaları referans alınır.

## OCR ve model sınırı

İlk File/DocumentWorker benchmarkında OCR provider veya model çağrısı capability başarı ölçütü değildir.

- Bir PDF veya belge yalnız OCR ile okunabiliyorsa, OCR’ın çağrılmış olması PASS değildir.
- Bir model belgenin içeriğini özetlediyse, model cevabı tek başına source evidence değildir.
- OCR/model sonucu ancak gelecekte ayrı bir kontrollü benchmark sözleşmesiyle, kaynağa bağlanabilir literal evidence ve provenance ile ölçülebilir.
- OCR/model bulunmaması veya gerekli olması mevcut read-only extractor’ın başarısızlığını gizleyemez.

Bu nedenle ilk benchmarkta OCR/model gerektiren case için güvenli sonuç FAIL veya INCONCLUSIVE olabilir; tahminle PASS üretilemez.

## Case → observation → evidence → evaluator akışı

Her benchmark turu ortak JarvisBench protokolüyle aynı tek yönlü hattı izler:

```text
versioned file/document case
  → kontrollü read-only gözlem
  → observation
  → source-bound evidence
  → evaluator
  → PASS | FAIL | INCONCLUSIVE + reason_code
```

Evaluator dosya açmaz, worker çalıştırmaz veya yeni effect üretmez. Observation benchmark yürütmesi tarafından önceden kaydedilmiş olmalıdır.

Case ile observation kimliği kesin eşleşmelidir. Başka dosyanın, başka case’in veya stale bir extract’in evidence’ı ödünç alınarak PASS üretilemez.

## Minimum evidence sözleşmesi

Her File/DocumentWorker benchmark kaydı en az aşağıdaki evidence alanlarını taşımalıdır:

```yaml
file_observation:
  case_id: <versioned case id>
  capability:
    id: <kaynakta var olan veya benchmark PR'ında açıkça tanımlanan aday kimliği>
    version: <commit/backend/extractor sürümü>
  source:
    file_identity: <benchmark tarafından sabitlenmiş kimlik>
    path: <normalize edilmiş yol veya güvenli alias>
    content_digest: <okunan kaynak içeriğini bağlayan digest>
  extractor:
    name: <gerçekte kullanılan mevcut extractor yolu>
    version: <paket/sürüm/commit bilgisi mümkünse>
  evidence:
    summary: <kanıtın kısa özeti>
    locations:
      - page: <mümkünse PDF sayfa numarası>
        line: <mümkünse metin/CSV satırı>
        sheet: <mümkünse XLSX sayfa adı>
        cell_or_range: <mümkünse hücre/aralık>
  duration_ms: <negatif olmayan süre>
  safety_outcome: <case beklentisiyle karşılaştırılacak sonuç>
  permission_outcome: <case beklentisiyle karşılaştırılacak sonuç>
  reason_code: <OK veya hata/belirsizlik kodu>
```

### Dosya kimliği/yolu

Evidence’ın hangi dosyaya ait olduğu açık olmalıdır. Dosya yolu hassas bilgi taşıyorsa fixture veya raporda güvenli alias kullanılabilir; ancak evaluator seviyesinde kaynak kimliği aynı dosyaya deterministik biçimde bağlanmalıdır.

### Content digest

İçerik digest’i, observation’ın belirli bir dosya sürümüne ait olduğunu sabitlemek için gereklidir. Digest algoritması benchmark turunda açıkça kaydedilmelidir. Digest eksikse, dosyanın ölçüm sırasında değişip değişmediği güvenle gösterilemiyorsa case PASS olmamalıdır.

### Extractor sürümü

Evidence, hangi gerçek extractor yolunun kullanıldığını belirtmelidir. Örnek olarak mevcut kaynakta `pypdf`, `openpyxl`, yerel CSV okuyucusu ve `modules/docs.py` yolları vardır. Kaynakta olmayan sahte capability veya extractor adı üretilmez.

### Sayfa/satır/hücre bağlamı

Mümkün olduğunda evidence’ın kaynak konumu kaydedilmelidir:

- PDF: sayfa numarası,
- düz metin/CSV: satır numarası veya deterministik satır aralığı,
- XLSX/XLSM: çalışma sayfası ve hücre/aralık,
- diğer belge türleri: mevcut extractor’ın güvenilir biçimde sağlayabildiği kaynak konumu.

Kaynak konumunun teknik olarak üretilemediği formatlarda bu alanın neden bulunmadığı reason-code/evidence özetinde belirtilmelidir; uydurma sayfa veya satır numarası yazılmaz.

### Failure reason-code

Her başarısız veya ölçülemeyen observation açık reason-code taşımalıdır. Örnek sınıflar:

- `FILE_NOT_FOUND`
- `UNSUPPORTED_FORMAT`
- `ENCRYPTED_OR_PROTECTED`
- `CORRUPT_DOCUMENT`
- `READ_TIMEOUT`
- `NO_TEXT_EXTRACTED`
- `SOURCE_DIGEST_MISMATCH`
- `EVIDENCE_NOT_BOUND`
- `PERMISSION_MISMATCH`
- `SAFETY_MISMATCH`

Bunlar bu belge için kavramsal benchmark reason-code sınıflarıdır; runtime’a yeni enum/API eklemez. Gerçek uygulama geldiğinde mevcut JarvisBench reason-code sözleşmesiyle uyumlu ayrı PR’da sabitlenmelidir.

## PASS ölçütü

Bir case yalnız tüm önkoşullar sağlandığında PASS olabilir:

- observation doğru case id’ye bağlıdır,
- doğru dosya/file identity gözlenmiştir,
- source path/identity ve content digest mevcuttur ve observation ile uyuşur,
- kullanılan extractor kaydı gerçektir ve sürümü/provenance’i yeterince tanımlıdır,
- case’in istediği içerik/metadata evidence’ı gerçekten kaynak dosyadan çıkarılmıştır,
- mümkün olan kaynak sayfa/satır/sheet/hücre bağları kaydedilmiştir,
- `duration_ms` geçerli ve negatifi değildir,
- safety ve permission sonuçları case beklentisiyle uyuşur,
- read-only sınırı ihlal edilmemiştir.

PASS’in anlamı yalnız bu benchmark case’inin bu dosya sürümü, extractor sürümü ve ortamda tanımlı ölçütleri karşılamasıdır. Genel dosya yetkisi, yazma/export izni veya global görev tamamlanması anlamına gelmez.

## FAIL ölçütü

Aşağıdakilerden biri varsa case FAIL olabilir:

- yanlış dosya veya yanlış case observation’ı kullanılmışsa,
- content digest beklenen kaynakla uyuşmuyorsa,
- extractor başka dosyanın içeriğini evidence diye döndürmüşse,
- safety/permission sonucu case ile uyuşmuyorsa,
- kaynakta bulunmayan bir bilgi evidence olarak sunulmuşsa,
- read-only benchmark sırasında yazma/silme/taşıma/export/upload/dışa gönderme denenmişse,
- OCR/model sonucu kaynak evidence yerine otomatik başarı kabul edilmişse,
- worker sonucu GoalState/completion authority gibi kullanılmaya çalışılmışsa.

FAIL yeni effect, otomatik retry veya başka provider çağırma yetkisi vermez.

## INCONCLUSIVE ölçütü

INCONCLUSIVE, güvenilir PASS/FAIL kararı için yeterli ölçüm bulunmadığını ifade eder. Örnekler:

- dosya okunabilir görünüyor fakat extractor güvenilir metin çıkaramamışsa,
- PDF’den yalnız boş/eksik text çıkmış ve OCR bu benchmarkın kapsamı dışındaysa,
- gerekli kaynak sayfa/satır bağlamı format nedeniyle güvenle üretilemiyorsa ve case bunu zorunlu kılıyorsa,
- süre veya gerekli evidence alanı eksikse,
- extractor sürümü/provenance’i belirlenemiyorsa,
- dosya ölçüm sırasında değişmiş ve digest stabil değilse.

**INCONCLUSIVE asla PASS değildir.** Başarı oranında PASS gibi sayılamaz ve canlı acceptance kanıtı olarak sunulamaz.

## Fixture ve gizlilik ilkesi

Benchmark fixture’ları gerçek kişisel veya gizli kullanıcı dosyalarını içermemelidir.

Fixture olarak kullanılacak belgeler:

- sentetik,
- kamuya açık ve yeniden dağıtımı uygun,
- veya özel olarak benchmark için üretilmiş anonim içerik

olmalıdır.

Aşağıdakiler fixture’a konmaz:

- gerçek kullanıcı e-postası veya ekleri,
- kişisel kimlik bilgileri,
- müşteri/çalışan verisi,
- banka/finans dökümü,
- özel sözleşme veya şirket belgesi,
- parola, token, secret veya oturum verisi,
- kişisel klasör yollarını ifşa eden gereksiz metadata.

Canlı acceptance ileride gerçek kullanıcı dosyasıyla yapılacaksa bu ayrı, kontrollü ve açık izinli bir PR/protokol olmalıdır; fixture deposuna ham içerik kopyalanmaz.

## WorkerResult ve Core authority sınırı

File/DocumentWorker benchmark çıktısı en fazla WorkerResult/evidence adayıdır.

`modules/worker_result.py` mevcut sözleşmeye göre sonuç şu immutable fence alanlarıyla bağlanır:

- owner,
- job_id,
- step_id,
- command_id,
- attempt,
- expected_job_version,
- capability_id,
- capability_version,
- input_digest.

Bu fence eşleşmeden result kabul edilmez. Kabul edilen WorkerResult bile doğrudan GoalState yazamaz.

Core aşağıdaki otoriteleri korur:

- **permission authority:** hangi okuma veya gelecekteki effect’in izinli olduğuna Core karar verir,
- **effect authority:** yazma/export/upload/gönderim gibi işler ancak ayrı effect policy hattından geçebilir,
- **state authority:** canonical state yalnız mevcut Reducer/CAS yoluyla değişebilir,
- **completion authority:** worker/benchmark PASS sonucu global `done` değildir; Completion Policy karar verir.

Read-only benchmark PASS sonucu permission yükseltmez ve effectful capability kabulü sayılmaz.

## Permission ve effect policy sınırı

İlk File/DocumentWorker benchmarkı yalnız read-only olduğu için dosyaya mutasyon yapmaz. Bu durum permission sistemini devre dışı bırakmaz; yalnız case’in önceden izinli read-only yüzeyinde ölçüm yapar.

Gelecekte yazma, silme, taşıma, export, upload veya dışa gönderme gibi effectful benchmarklar eklenecekse bunlar bu belgeye sessizce genişletilemez. Ayrı PR ve sözleşmede en az şu karar hattı zorunlu olmalıdır:

```text
Domain Invariant
→ Decision Authority
→ JIT Permission
→ Effect Policy
→ Worker/Adapter
→ intent / receipt / reconcile evidence
→ Reducer / Completion Policy
```

JIT permission, intent/receipt/reconcile ve effect policy olmadan effectful File/DocumentWorker benchmarkı yapılamaz.

## Kaynak-doğrulanmış mevcut davranışlar

Bu benchmark aşağıdaki mevcut kod davranışlarını baseline kabul eder, genişletmez:

- `modules/docs.py.SUPPORTED` mevcut belge uzantılarını listeler.
- `modules/docs.py.read_document()` dosya yoksa `FileNotFoundError` üretir ve belgeyi yalnız okur.
- `read_pdf_isolated()` PDF metnini ayrı süreçte pypdf ile okur ve timeout durumunu fail-closed biçimde bildirir.
- `check_office_file()` şifreli/bozuk/aşırı açılan Office dosyasını okumadan reddeder.
- CSV okuyucusu UTF-8/cp1254 ve delimiter sniffing ile mevcut kaynağı okur.
- `modules/workbench.py.load_table()` XLSX/XLSM için `read_only=True, data_only=True` kullanır; makro çalıştırmaz ve yalnız hücre değerlerini çıkarır.
- `modules/worker_result.py` result’ın fence alanlarını tam eşleşmeden kabul etmez ve GoalState mutasyonu yapmaz.
- JarvisBench v0 yalnız observation değerlendirir; worker/provider/model çalıştırmaz.

## Red koşulları

Aşağıdakilerden biri varsa PASS yoktur:

- case ile file identity eşleşmiyor;
- kaynak dosya değişmiş fakat eski digest/evidence kullanılıyor;
- dosya bulunamıyor veya desteklenmeyen biçimde;
- Office/PDF bozuk, şifreli veya extractor güvenli biçimde okuyamıyor;
- gerekli içerik evidence’ı kaynakta yok;
- sayfa/satır/sheet/hücre bilgisi mümkün olduğu halde başka kaynağa ait veya uydurulmuş;
- extractor adı/sürümü gerçek yürütmeyle bağlanamıyor;
- fixture gizli/kişisel gerçek veri içeriyor;
- OCR/model çağrısı kendi başına başarı sayılıyor;
- dosya yazma/silme/taşıma/export/upload/gönderme deneniyor;
- WorkerResult fence’i uyuşmuyor;
- benchmark sonucu GoalState veya Core completion kararı gibi kullanılmaya çalışılıyor.

Belirsizlik güvenli biçimde FAIL veya INCONCLUSIVE kalır; sessiz başarı yoktur.

## Kapsam dışı

Bu belge yalnız read-only benchmark sözleşmesidir. Şunlar kapsam dışıdır:

- yeni parser veya extractor yazmak,
- yeni FileWorker/DocumentWorker runtime uygulamak,
- UI veya panel eklemek,
- dosya upload etmek,
- dosya yazma/export/dönüştürme akışı eklemek,
- OCR provider veya OCR servis entegrasyonu,
- model/provider entegrasyonu,
- belge özetleme modelini değiştirmek,
- GoalState/reducer/Completion Policy değişikliği,
- permission/effect policy değişikliği,
- CI, workflow veya watcher değişikliği,
- test/fixture eklemek veya değiştirmek.

Bu sözleşme yalnız gelecekteki File/DocumentWorker adaylarının aynı salt-okunur file identity, digest, extractor provenance, kaynak konumu, safety/permission ve fail-closed ölçütleriyle karşılaştırılmasını sağlar.