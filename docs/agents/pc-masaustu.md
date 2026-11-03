# PC ve masaüstü kontrolü (AGENTS.md alan notları)

Bu dosya AGENTS.md'den taşındı; bölümler olduğu gibi, sırası korunarak buradadır. Tarihli bölümler geçmiş kararı anlatır; bir bölüm başka bir bölümle çelişirse tarihi daha yeni ve "son karar" yazan geçerlidir. Kod değişince ilgili bölüm burada güncellenir.

## Altyapı tamamlama ve kabul paketi — 14 Ekim 2026

- `pc_contracts` mevcut 11 mutasyon girişine tür ve istek sahibi denetimi, son 200 işlem için argümansız kullanıcı kaydı ve ortak sonuç sınıfı ekler. `system_control` girişleri aynı sınırdan geçer; `pc_steps` çift kayıt üretmez. Pencere/odak/izin korumaları aynı kalır. Kayıt başta saklanamazsa fiziksel işlem başlamaz; son kayıt saklanamazsa işlem kendiliğinden tekrarlanmaz. Kapatmada yalnız komut iletimi kanıtlanır; gerçek kapanış veya klavye işleminin uygulamadaki sonucu garanti edilmez.
- `Profile.edit_fact` kesin eski metin ve indeksle, profil kilidi içinde düzeltme/silme yapar; disk hatasında belleği geri alır. `fact_update` ortak araca bağlıdır. Modelsiz `hafızamı göster`, `hafıza düzelt: eski | yeni`, `hafıza unut: tam kayıt` yalnız onaylı facts alanını etkiler. Diğer veri alanlarını topluca silmez.
- `task_workflows` rapor, mail taslağı, kod taslağı ve yerel video için mevcut worker'larla sabit üretici/doğrulayıcı zincirleri kurar. Planlayıcı çağrısı yoktur; üretici çağrıları ve mevcut geliştirme/hesap izinleri korunur. Dış gönderim veya ücretli üretim eklenmez.
- `acceptance_checks` ve `scripts/v2_kontrol.bat` kaynak/sürüm testi ve yerel önkoşul raporu üretir. Gmail, Hesap Makinesi ve WAV denemeleri ancak ilgili CLI bayrağıyla çalışır; varsayılan gerçek hesap/donanım çağrısı yoktur. Yeni masaüstü görevine UUID eklenir; kabul yalnız bu çağrının yeni kimlikli kaydını kullanır, eski done kaydı başarı sayılmaz. Gönderim, mikrofon kaydı ve kamera açılmaz. Elle yapılacak kabul pending kalır; rapor Gmail içerik/kimlik veya anahtar saklamaz ve Git kapsamı dışındadır. Ayrıntı: `docs/V2_TAMAMLAMA_VE_PC_KABUL.md`.
- Salt-okunur gözlem: `desktop_agent.run(..., read_only=True)` yalnız açık hedef pencereyi gözlemler; model çağırmaz, uygulama açmaz, UIA action göndermez ve görev kaydını değiştirmez. Sonuçta değer alanları çıkarılmış, gizli etiketleri maskelenmiş pencere/kontrol evidence'ı döner. `desktop_uia.DesktopUI.act(..., read_only=True)` fail-closed `NotSent` üretir; normal masaüstü görev akışı değişmez.
## Gerçek PC kabul geri bildirimi — 14 Ekim 2026

Ekran paylaşım komutu ASCII ş/i yazımını da mevcut `set_share` yolunda tanır; uygulama açmaya düşmez. İlk mailin ek komutları yalnız bir mail seçer ve sonuçlarını sade gösterir; hash/adım günlükleri kayıt ve açık görev durumunda korunur. Boş ek, okunacak ek yok şeklinde anlatılır. Kuyruk durumu işin adını, bekleme süresini ve açık iptal/sonuç komutlarını gösterir; bildirimi de sonuç özeti taşır. Masaüstü görevleri her mevcut kaydetme noktasında çalışma turu süresini ölçer; yeni UIA çağrısı/model çağrısı yoktur. Normal sonuçta ham kontrol kanıtı gizlenir; `PC görevi ayrıntıları` ile istenir.

## Durable PC yürütme sınırı — 25 Ekim 2026

- `goal.desktop`, mevcut `desktop_agent` adapter'ının Capability Manifest görünümüdür; yeni bir desktop dispatcher veya ikinci UIA motoru değildir. Durable hedef içindeki masaüstü işi, native UIA/CUA/C# backend'i başlatmadan önce Core'un Decision/Permission/Effect hattından geçer.
- İlk Core onayı owner/job/step/capability-version/input-digest alanlarına bağlı prepare artifact'idir. Bu artifact doğrudan UIA tıklama onayı değildir. Native adapter daha sonra somut bir kontrol için ayrı onay isterse bu ikinci onay WorkerResult başarısı veya global completion sayılmaz.
- Başarılı masaüstü sonucu yalnız doğrulanmış native görev geçmişiyle `desktop_uia:<desktop_id>` receipt'i taşır; ardından WorkerResult fence ve mevcut Reducer/CAS evidence hattına girer. Crash/restart sonrası recovery yalnız aynı owner/target/goal için doğrulanmış `done` native görevini okur; yeni pencere açmaz ve kör tıklama/tekrar yapmaz.

## Salt-okunur pencere gözlemi — 25 Ekim 2026

- Mevcut `observe` goal aracı `kind=window` ile açık bir uygulamanın sınırlı UIA görünümünü alabilir. Bu, yeni bir PC motoru veya ikinci tool catalog değildir; `desktop_agent.run(..., read_only=True)` yolunu kullanır.
- Bu yol pencere açmaz, model çağırmaz, tıklama/yazma/klavye girdisi göndermez ve masaüstü görev kaydı oluşturmaz. Hedef pencere yoksa ya da korunan bir uygulamaysa başarı uydurmaz.
- Gözlemde yalnız pencere kimliği ile redakte edilmiş/sınırlı kontrol metadatası vardır; değer alanları ve şifre alanları dışarı verilmez. Gizli ve yalnız-yerel modlarda ekran gizlilik kapısı geçerlidir.

## Doğrulanmış açık uygulamayı yeniden kullanma — 25 Ekim 2026

- `system_control.open_application`, hedef uygulamanın gerçek penceresi zaten doğrulanmışsa ikinci `start` çağrısı yapmaz. Bu, tekrar eden PC kabul koşularında Hesap Makinesi gibi UWP uygulamalarının pencere biriktirmesini önler.
- Mevcut pencere yalnız “açık” isteğinin kanıtıdır; Jarvis pencereyi zorla öne getirmez veya kullanıcı odağını çalmaz. Pencere yoksa eski başlatma ve gerçek pencere doğrulama yolu değişmeden sürer.

## Doğrulanabilir ses durumu için durable Core hattı — 25 Ekim 2026

- `system` aracının `volume`, `mute` ve `brightness` işlemleri, istenen sonucun işletim sisteminden kesin geri okuması bulunduğu için mevcut Core prepare onayı, WorkerResult fence, effect intent/receipt ve Reducer/CAS evidence hattına katılır. Core onayı owner/job/step/capability/version/input digest alanlarına bağlıdır.
- Recovery yeni ayar göndermez: yalnız mevcut ses/mute ya da her okunabilir ekrandaki parlaklık değeri istenen değerle aynıysa doğrulanmış receipt üretir; aksi durumda sonuç belirsiz kalır ve kör retry yoktur.
- Medya tuşları eşdeğer bir gerçek geri-okuma receipt sözleşmesi olmadığı için durable hatta alınmaz; başarı kanıtı uydurulmaz.
- Aynı geri-okuma şartı hedef yürütücüsü dışındaki hızlı doğal dil parlaklık komutlarında da kullanılır; sürücü çağrısı tek başına kullanıcıya “ayarladım” yanıtı verdirmez.
- Hızlı doğal dilde uygulama kapatma da mutasyondur: pencereye `WM_CLOSE` göndermeden önce açık uygulama adıyla onay alınır. Bu yalnız var olan hızlı yolu güvenli kılar; native masaüstü işlerinin Core hattını değiştirmez. Çıplak `kapat` sorusunun typed cevabı ve `<uygulama> kapat` grameri tek ortak onay sahibini (`command_execution.request_close_app`) kullanır; cevap doğrudan kapatmaz, mevcut onay ve permission/effect kapısından geçer. **PR3A (3 Kasım 2026):** bu grameri seçen `<uygulama> kapat` regex'i `engine_commands.handle`'dan fiziksel olarak silindi; hedefi yalnız `brain_understanding._app_request` tipli `app.close` olarak seçer, zincir cümleleri (`ve`, `-ıp`, virgül — `_APP_CHAIN`) tek uygulamaya bağlanmaz ve bütün cümle yürütücüye kalır, `ses`/`müzik`/`ekran`/`bilgisayar` gibi yasaklı hedefler kendi sahiplerindedir. Motor yüzeyinde `close_application` tek çağrı noktasıdır ve `pending_confirm` + `pending_answer_owned('pending_confirm')` kapısının içindedir. Test: `tests/test_brain_pr3_raw_text_authority.py`, `tests/test_system_runtime_gate.py`.
- Onaylı toplu klasör düzenlemesinin geri alma kaydı kullanıcıya özeldir; başka kullanıcının son düzenlemesi geri alınamaz. Plan/önizleme, açık onay ve çakışmasız geri alma davranışı korunur.

## Doğal dil PC görevi tek yürütme hattı — 25 Ekim 2026

- Router'ın `desktop_task` kısayolu native `desktop_agent.handle` çağrısı yapmaz. Açık hedef/iş metnini mevcut `goal_executor`a devreder; böylece masaüstü işi Core prepare onayı, identity/fence, receipt ve Reducer/CAS kabulünden ayrı ikinci bir yoldan başlayamaz.
- Bu yönlendirme yeni PC motoru değildir ve uygulama içi UIA davranışını değiştirmez. Eksik/hedefi belirsiz PC isteği önceki gibi netleştirme sorusuna gider.


## PC Worker sınırı — 26 Ekim 2026

- Tam PC kontrolü (genel tıklama, yazma, kaydırma, sürükleme, kısayol, görüntü tabanlı yedek, C# Windows-native yürütücü) ayrı PC Worker'ın işidir; kodu bu depoda değildir. Mimari belgedeki `ComputerWorker` / "C# PC Worker" ile aynı worker'dır.
- Jarvis-v2 yalnız Core tarafını yapar: capability manifesti, izin ve etki politikası, IPC sözleşmesi ve sürüm uzlaşması, lease, WorkerResult sınırı, makbuz ve salt-okunur benchmark (`docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md` §16–17).
- `desktop_agent` ve `desktop_uia` UIA temeli olarak kalır, genel girdiye genişletilmez; PC Worker bu temele karşı ölçülür. `_NEVER_APPS` yalnız bu temelin listesidir. PC Worker için Core politikası (mimari §16): Jarvis penceresi ve uzak erişim uygulamaları yasak; terminal, kod editörü, tarayıcı, şifre yöneticisi ve sistem araçları hassas sınıftadır (her eylemde ayrı onay, kalıcı izin yok, makbuz zorunlu, şifre alanı değeri okunmaz).
- IPC yalnız yerel ve aynı kullanıcıdır (ACL'li named pipe veya stdio); ağ portu açılmaz. Girdi modu `uia_pattern` (odak/imleç çalmaz, pencere lease'i) ve `physical_input` (masaüstü geneli lease, kullanıcı girdisinde durur) olarak ayrılır; Worker modu kendiliğinden yükseltmez. Yönetici yetkili hedefte Worker kendini yükseltmez, `elevated_target` ile reddeder.
