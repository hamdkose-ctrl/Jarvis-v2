# Jarvis ComputerWorker Read-Only Benchmark v1

## Durum ve amaç

Bu belge, gelecekteki `ComputerWorker` backend seçeneklerini aynı dar güvenlik ve kanıt sınırında karşılaştırmak için ilk salt-okunur PC gözlem pilotunun benchmark sözleşmesidir. Runtime, worker veya backend kurmaz; mevcut masaüstü davranışını genişletmez.

Kaynak-doğrulanmış mimari sınır şudur: yeni capability hattı `Jarvis Core → DecisionContext / Permission / Effect Policy → Worker veya Adapter → WorkerResult + Evidence / Receipt → Core State Reducer / Completion Policy` içinde kalır ve worker başarısı tek başına global `done` değildir. Mevcut capability intake de `UIA Computer observation` için Calculator/Notepad odaklı dar pilotu baseline kabul eder ve ilk acceptance'ı pencere/UIA/screenshot gözlem benchmark'ı olarak tarif eder.

## Pilot sınırı: yalnız gözlem

Pilot bir hedef Windows penceresi hakkında yalnız aşağıdaki kanıtları okuyabilir:

1. **Hedef pencere / uygulama kimliği.** Pencere handle'ı (`hwnd`), pencerenin process kimliği (`pid`), çözümlenmiş uygulama adı ve gerekiyorsa uygulama process kimliği (`app_pid`) gözlenir. Mevcut `DesktopUI.observe()` önce açık pencereleri hedefe göre seçer; tek pencere seçilemezse ilerlemez. UIA katmanı da seçilen HWND altındaki gerçek process sahipliğini çözer.
2. **Pencere başlığı.** Seçilen pencerenin gerçek başlığı snapshot evidence'ının parçasıdır. Aynı hedef için birden fazla pencere varsa mevcut gözlem yolu yalnız tek aktif eşleşme belirlenebildiğinde devam eder; aksi durumda belirsizliği reddeder.
3. **UIA control gözlemi.** Mevcut UIA adapter görünür native kontrolleri okur; kontrol kimliği, ad, tür, `automation_id`, process kimliği, enabled/password/offscreen bilgisi, güvenli okunabilen value/selected alanları ve desteklenen UIA pattern listesini snapshot'a taşır. PowerShell UIA worker'ı ham ağaç taramasını 500 öğeyle sınırlar; uzun value ve name alanlarını da sınırlar.
4. **Ekran / kanıt okuma.** Benchmark yalnız zaten okunmuş snapshot/evidence'ı değerlendirir. Görsel ekran kanıtı kullanılacaksa bu da salt-okunur kanıt girdisi olarak ele alınır; benchmark sözleşmesi ekran görüntüsü üretmek, diske kaydetmek veya yeni bir capture mekanizması kurmak için yetki vermez. Mevcut `desktop.py.screenshot()` dosyaya yazar; bu nedenle bu pilotun read-only yürütme yüzeyinin parçası değildir.

Bu pilotta **mouse veya klavye işlemi yoktur**. UIA `invoke`, `fill`, `select` ve `toggle` çağrıları yapılmaz. Dosya yazma yoktur. Ayar değiştirme, mesaj/gönderim, terminal veya shell çalıştırma, browser action, URL açma ve başka herhangi bir yan etki yoktur. C# worker, dış CUA backend veya Hermes kurulmaz ve çalıştırılmaz.

Mevcut `desktop_agent.py` Calculator/Notepad'i desteklenen dar uygulamalar arasında tutsa da aynı modül UIA üzerinden işlem yapabilen daha geniş bir görev yürütücüsüdür; bu benchmark o yürütme yüzeyini genişletmez. `desktop_uia.py` içindeki `act()` ve PowerShell tarafındaki işlem op'ları benchmark kapsamı dışındadır. Benchmark'ın güvenli referansı yalnız gözlem davranışıdır.

## Benchmark case sözleşmesi

Her benchmark case en az şu dört alanı taşır:

```yaml
case:
  id: pc-observe-001
  owner: <beklenen görev sahibi>
  target_app: <beklenen uygulama/pencere kimliği>
  expected_evidence:
    - <kimlik, başlık, UIA veya ekran kanıtı beklentisi>
  reject_if:
    - <yanlış/belirsiz pencere veya yetersiz kanıt koşulu>
```

`owner` boş veya belirsiz olamaz. `target_app`, case'in hangi uygulama/pencereyi gözlemlediğini sabitler; benchmark başka bir pencerenin kanıtını hedef yerine kabul etmez. `expected_evidence`, PASS için gereken somut gözlem türlerini önceden tanımlar. `reject_if`, özellikle yanlış pencere, birden fazla belirsiz hedef, kimlik uyuşmazlığı, eksik/zayıf evidence, read-only sınır ihlali veya gözlem sonucunun güvenle bağlanamadığı koşulları içerir.

Case sonucu tahminle PASS'e çevrilmez. Hedef pencere tekil değilse, kimlik hedefle uyuşmuyorsa veya gereken evidence yoksa case fail-closed sonuç üretir. Mevcut UIA gözlem yolu da hedef pencere bulunmadığında `WindowMissing`, birden fazla belirsiz hedefte hata üretir; işlem tarafında ise process/app kimliği değişimini ve başka uygulamaya ait elementi açıkça reddeder. Benchmark bu kimlik disiplinini gözlem karşılaştırmasına taşır, yeni işlem yetkisi çıkarmaz.

## Ölçümler

Her case için en az şu ölçümler kaydedilir:

| Ölçüm | Tanım |
|---|---|
| Doğru kimlik | Gözlenen HWND/process/app kimliği ve hedef uygulama case beklentisiyle doğru ve tekil eşleşiyor mu? |
| Evidence kalitesi | Beklenen başlık/UIA/ekran kanıtı mevcut, hedefe bağlanabilir ve kararı destekleyecek kadar somut mu? |
| Yanlış pencere reddi | Benzer başlıklı, başka process'e ait veya belirsiz pencere hedef diye kabul edilmeden reddediliyor mu? |
| Süre | Gözlemin başlatılmasından evidence adayının elde edilmesine kadar geçen süre; tek başına PASS nedeni değildir. |
| Fail-closed oranı | Belirsiz, eksik veya uyuşmayan vakaların güvenli biçimde reddedilen vakalara oranı. Belirsizlik başarı sayılmaz. |

Süre ölçümü güvenlik veya evidence koşulunun yerine geçmez. Depodaki JarvisBench v0 da `duration_ms` değerini zorunlu gözlem alanı olarak değerlendirir fakat evidence ve safety/permission beklentileri sağlanmadan süreyi PASS için yeterli saymaz; gözlem yoksa fail-closed davranır. Bu belge mevcut JarvisBench şemasını değiştirmez, yalnız ComputerWorker pilotunun ileride ona veya eşdeğer bir değerlendiriciye vereceği benchmark anlamını sabitler.

## Evidence ve sonuç sınırı

Pilotun çıktısı yalnız **WorkerResult/evidence adayıdır**. Örnek anlam:

```yaml
candidate_result:
  outcome: success | partial | blocked | permanent_failure
  evidence:
    - window_identity
    - window_title
    - uia_observation
    - optional_screen_evidence
```

Bu aday global Job/GoalState completion kararı değildir. Mevcut execution architecture'a göre WorkerResult Core'a geri döner; fencing, invariant ve Completion Policy değerlendirmesinden bağımsız olarak global state yazamaz. `success` yalnız gözlem capability'sinin kendi sözleşmesini karşıladığını ifade eder; `done` anlamına gelmez.

## Baseline: Calculator ve Notepad

Calculator ve Notepad bu pilotta yeni yetenek hedefleri değil, mevcut dar PC sözleşmelerinin örnek kanıtıdır.

- `desktop_agent.py` mevcut destek kümesini `calc`, `calculator`, `calculatorapp`, `notepad` ile sınırlar; terminal, kod editörü, browser, parola yöneticisi, uzak erişim ve sistem yönetimi uygulamalarını ayrı reddetme kümelerinde tutar.
- `DesktopUI.observe()` hedef pencereyi mevcut Windows pencere listesi üzerinden seçer, `hwnd/title/app/pid/app_pid/controls` snapshot'ı döndürür ve belirsiz çoklu pencereyi reddeder.
- `desktop_uia.ps1` Calculator'ın UWP host durumunda gerçek Calculator process'ini yalnız aynı HWND altındaki gerçek `CalculatorResults` kontrolünden çözer; tekil güvenilir sahiplik yoksa host adı tek başına izin veya kimlik kanıtı değildir.

Benchmark bu mevcut davranışları **genişletmez**. Calculator/Notepad üzerinde yeni click, type, fill, toggle, dosya kaydı veya uygulama açma akışı eklenmez. Amaç, gelecekteki backend adaylarının aynı salt-okunur gözlem case'lerinde bu baseline'a karşı ölçülebilmesidir.

## Red koşulları

Aşağıdakilerden biri varsa case PASS olamaz:

- owner case ile bağlanamıyor veya uyuşmuyor;
- hedef pencere bulunamıyor ya da tekil seçilemiyor;
- pencere/application/process kimliği hedefle uyuşmuyor;
- evidence başka pencereye, overlay'e veya başka process'e ait;
- beklenen başlık/UIA/ekran kanıtı eksik veya hedefe bağlanamıyor;
- gözlem sırasında mouse/klavye, UIA action, dosya yazma, ayar değişikliği, gönderim, terminal/shell veya browser action deneniyor;
- sonucu güvenli biçimde sınıflandırmaya yetecek evidence yok.

Belirsizlikte güvenli sonuç `FAIL`, `INCONCLUSIVE` veya eşdeğer blocked/rejected sınıfıdır; sessiz başarı yoktur. Kesin sonuç etiketi ileride kullanılacak benchmark evaluator sözleşmesine bağlıdır, fakat fail-closed ilkesi değişmez.

## Kapsam dışı

Bu belge yalnız benchmark sözleşmesidir. Aşağıdakiler bu değişikliğin kapsamı dışındadır:

- Hermes lisans veya uyumluluk değerlendirmesi;
- gerçek `ComputerWorker` kodu veya IPC uygulaması;
- C# worker, CUA ya da Hermes kurulumu/entegrasyonu;
- mevcut desktop worker veya UIA davranışında değişiklik;
- Permission, GoalState, reducer veya Completion Policy değişikliği;
- CI, PC watcher, `AGENTS.md` veya test değişikliği;
- browser action, terminal/shell, dosya yazma veya başka effect-bearing benchmark case'i.

Bu sözleşme backend seçmez. Yalnız ilerideki backend adaylarının aynı read-only PC gözlem sınırında, aynı evidence ve red ölçütleriyle karşılaştırılmasını sağlar.
