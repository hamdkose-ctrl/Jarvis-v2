# AGENTS.md · Jarvis'te çalışan ajanlar için kısa rehber

Bu dosya Jarvis kodunda değişiklik yapan her yapay zekâ ajanı (Claude, Codex vb.) içindir. Kod değiştiğinde bu dosya da aynı PR'da güncellenir. Alana özgü ayrıntı `docs/agents/` altındadır.

## Çalışma kuralları

- **Ponytail yaklaşımı:** Önce mevcut kodu oku. Küçük, kararlı ve geri alınabilir değişiklik yap. Gereksiz katman veya bağımlılık ekleme.
- **Önce plan:** Yeni özellikte önce yapılacakları ve en az iki seçeneği Hamdi'ye sun. Hamdi "Tamam" demeden kod yazma.
- **Ayrı dal:** Her iş ayrı bir dalda yapılır, PR ile onaya sunulur. `main`'e doğrudan yazılmaz, `--force` kullanılmaz.
- **"Bitti" kuralı:** Bir faz ya da madde ancak dördü birden sağlanınca "tamamlandı" sayılır: (1) sözleşme / arayüz yazıldı, (2) eski kod göçü tamamlandı, (3) yeni kod kullanıcı akışına bağlandı (yalnız testten çağrılması yetmez), (4) eski kod / legacy kısım kaldırıldı. Merge edilmiş PR tek başına "bitti" değildir. PR açıklaması hangi koşulları kapattığını yazar; durum `docs/Jarvis_Yol_Haritasi.md`'de bu koşullara göre işaretlenir.
- **Program ledger:** Yeni işe başlamadan önce `docs/architecture/JARVIS_PROGRAM_LEDGER_V1.md` ve güncel açık PR durumunu oku; merge edilmiş işi yeniden açma.
- **PC watcher:** Gerçek PC kabulü dal önekine değil açık PR'a bağlıdır; `gpt/*`, `codex/*`, `claude/*` ve bakım dalları desteklenir. Sonuç yorumu başarısızsa arşivlenen exact-SHA raporu tekrar yayımlanır, test tekrarlanmaz; tanı: `scripts/pc_test_watcher.py --status`. Ayrıntı: `docs/PC_TEST_WATCHER.md`.
- **Android'e dokunma:** `android/` ayrı bir sohbette geliştirilir.
- **Kişisel veri depoya girmez:** `%USERPROFILE%\.jarvis` (ayarlar, kullanıcılar, anahtarlar, günlük), `.venv` ve model dosyaları depoya eklenmez.
- **Anahtarlar kullanıcıya özeldir:** Her kullanıcı kendi Gemini/Groq anahtarını kullanır, kullanıcılar arasında yedeğe düşülmez (`docs/MIMARI_KURALLAR_v5.7.md`). Ücretli sağlayıcılar otomatik havuza girmez.
- **Ses değişikliklerinde temkinli ol:** Gürültü, TV/YouTube ve hoparlör yankısı gerçek ortamda kolay ters teper. Yeni davranış ayarla açılır olmalı. Gereksiz Gemini çağrısı eklenmez (kota).
- **Kota çalışma tercihleri:** Model kotasını gereksiz harcama; aşağıdakiler yukarıdaki kuralların yerine geçmez, onlarla birlikte uygulanır.
  - İlgili dosyalara odaklan.
  - Uzun çıktılarda hataları ve başarısız adımları göster, başarıları kısa özetle.
  - Başarılı bir kontrolü yeni bir neden (kod değişti, hata düzeldi) olmadan tekrarlama.
  - Alt ajanları yalnız ihtiyaç olduğunda kullan. `jarvis-kural-denetcisi` yalnız Hamdi açıkça isterse veya PR öncesi son incelemede çalışır (`docs/GELISTIRME_ORTAMI.md`).
  - İş sonunda kısa bir durum kaydı bırak: yapılanlar, doğrulananlar, doğrulanmayanlar (açık işler `docs/BEKLEYEN_ISLER.md`'de tutulur).
  - Gerekli testleri ve güvenlik kontrollerini atlama; tasarruf bunların pahasına yapılmaz.

- **Model rotası:** `ModelRequest` → `RoutePlan` → adapter; Router retry/fallback için en çok iki fiziksel deneme yetkisidir. Gemini SDK retry/continuation kapalı tutulur, başarısız fiziksel deneme de sayılır; Core yetkiyi korur.

- Haber zamanı: “son dakika” varsayılanı son 1 saattir; açık saat aralığı üstündür. Saat hassasiyetli istekte yalnız yayın günü yeterli değildir. Olayın geçerlilik tarihi yayın tarihinden ayrı, özgün istek zamanı ve kapsamına bağlı kanıtla doğrulanır.
- Not arama/özetleme sahibi: `docs/agents/mail-takvim.md`.

## Alan notları

Alana özgü ayrıntılar `docs/agents/` altındadır. İlgili alanı değiştirirken önce ilgili dosyayı oku, değişince aynı PR'da orayı güncelle:

- `docs/agents/dosya-belge.md`: Dosya, belge ve klasör (15 bölüm)
- `docs/agents/guncelleme-ci-kota.md`: Güncelleme, CI, model ve kota (23 bölüm)
- `docs/agents/pr-test-bekleme.md`: PR/test sonucu bekleme kuralı (3 bölüm)
- `docs/agents/mail-takvim.md`: Mail, takvim ve hatırlatma (23 bölüm)
- `docs/agents/haber.md`: Haber araştırması ve kaynaklar (18 bölüm)
- `docs/agents/gorev-cekirdegi.md`: Görev çekirdeği, hedef yürütücüsü ve araçlar; şehir tercihinde koşul/soru ve kibar reset sınırları ve BRAIN-05 Goal Resolver (25 bölüm)
- `docs/agents/arayuz.md`: Arayüz, ana ekran ve ayarlar (10 bölüm)
- `docs/agents/ses-video.md`: Ses ve video (11 bölüm)
- `docs/agents/pc-masaustu.md`: PC ve masaüstü kontrolü (9 bölüm)
- `docs/agents/yerel-git-emniyet-kemeri.md`: Yerel Git commit/push emniyet kemeri (3 bölüm)
- `docs/agents/hoca.md`: Hoca çalışma alanı (ders/dönem/takvim, eski "Çalışma" sayfasının yerini alıyor) (17 bölüm)
- `docs/agents/finans.md`: Finans takibi, kur, kripto ve gram altın (5 bölüm)
- `docs/agents/gorsel-komutlar.md`: Görsel üretimi ve Brain/Core sınırı (7 bölüm)

## Klasör haritası

| Yer | Ne var |
|---|---|
| `baslat.bat` → `launcher.py` → `gui.py`/`web.py` | Açılış, gözetimli başlatma, yerel web sunucusu ve Edge/Chrome uygulama penceresi |
| `main.py` + `modules/engine_*.py` | Komut motoru. `EngineContext` (`engine_runtime.py`) tüm bağımlılıkları taşır. Komut sırası `engine_commands.handle` içindedir. |
| `web.py` + `web_*.py` | Arayüz köprüsü (`/api/<ad>` → `Bridge` metotları) ve `/events` SSE olay akışı (`Hub`) |
| `webui/nx.js`, `nx.css`, `icons.js` | Masaüstü arayüzü. Sayfalar `PAGES.*`, düğmeler `ACT.*`, sunucu olayları `onEvent` içinde işlenir. |
| `modules/system_control.py` | Windows ses, parlaklık, medya, uygulama ve pencere kontrolü |
| `modules/pc_steps.py` | Motorun `system_control` çağrılarını sohbete "adım" olarak raporlayan ince sarmalayıcı |
| `modules/llm.py`, `smart_router.py` | Model çağrıları ve otomatik model seçimi; yerel sunucu Ollama, LM Studio veya llama.cpp (`local_backend`) |
| `modules/model_free_delivery.py` | Planlayıcı model yokken haber dışı hedeflerde doğrulanmış çıktıların modelsiz teslimi |
| `modules/image_gen.py` | Görsel üretimi (Cloudflare Workers AI/FLUX, kullanıcıya özel anahtar) — yalnız üretim/iletişim katmanı |
| `modules/visual_commands.py` | Görsel prompt/PNG üretim ve kayıt worker'ı; intent seçmez |
| `modules/visual_chat.py` | Core onaylı görsel isteğinin kaynak sorusu, cevabı ve retry akışı |
| `modules/docs.py`, `document_conversion.py`, `kb.py` | Belge okuma, dönüştürme ve bilgi tabanı |
| `modules/workbench.py` | Belge masası: belgeden tablo, karşılaştırma, Excel/CSV birleştirme ve gruplama |
| `modules/watcher.py` | Klasör izleme kuralları ve 20 saniyelik arka plan taraması |
| `modules/runtime_subscription.py` | Tek kalıcı RuntimeEvent abonelik sistemi; kaynak takibi/webhook olaylarını Reducer/CAS ile GoalState evidence'ına ekler. Takibi ekleyen hedef `bind_job` ile sahibi olur |
| `modules/hoca_workspace.py` | Hoca çalışma alanı: ders, kaynak, ödev/deadline, oturum hafızası (domain sözleşmesi) |
| `modules/finance_domain.py` | Finance domain sözleşmesi: veri/alarm/analiz/kaynak doğrulama dalları, Communication sınırı, kod göçü planı ve statik sınır denetimi (FIN-001..004) |
| `modules/requests_state.py` | İstek kimliği (`rid`), iptal ve arşiv |
| `tools/claude/`, `docs/GELISTIRME_ORTAMI.md` | Claude Code ajanı (`jarvis-kural-denetcisi`), kurulum betiği ve geliştirme ortamı rehberi |
| `tests/` | Python `unittest` ve Node.js davranış testleri |

- **B07-FINAL-A (#610 DRAFT):** Core CAS–ExecutionRecord kesintisinde sonuç yalnız Core ve exact WorkerResult kanıtıyla sahibine okutulur. Bildirim/replay tekrar edilmez. Kabul: #584 ve aynı SHA CI+PC; PASS/merge değil.

## BRAIN-04 action_batch

- `clarify` ve 2–5 typed action birlikte benimsenir. Core doğrular; bağımlılık domain başarısı ister. Ayrıntı: `docs/agents/gorev-cekirdegi.md`.

- **BRAIN-03 final accepted-plan boundary (henüz kabul değil):** Geçerli Core planı raw ses/kamera/paylaşım, planner veya extra cascade üzerinden ikinci bir effect seçtiremez. Kayıtlı tam makro, explicit tırnaklı dosya UI ve `reminder` için Core-bağlı eski note-add sözleşmesi korunur. Kalan doğal-dil domain parser'ları #545 kapsamındadır; full cutover ve dört Bitti koşulu sağlanmadan faz kapanmaz. `tests/test_brain_03_final_authority_cutover.py` / `tests/test_visual_chat.py` CI/PC kabulü gerektirir.
- **BRAIN-03 hatırlatma sınırı:** Doğrulanmış `reminder` planı yalnız oluşturur; alıntıdaki not/etkinlik silme veya erteleme sözleri mevcut kayıtları değiştirmez. Plansız eski komutlar, açık `not al:` ve pending cevapları korunur. Ayrıntı: `docs/agents/mail-takvim.md`; test: `tests/test_brain_03_reminder_core_fence.py`.

## Testler

- Finance alarm fiyatları `finance.quote` ortak girişini kullanır; watcher kaynak sağlayıcıların özel fonksiyonlarını çağırmaz. Göç durumu `docs/agents/finans.md` içindedir.
- Finance alarm turu ve kurtarması `modules/finance_alert_tick.py` içindedir; watcher yalnız mevcut döngüden çağırır.

- JarvisBench v0 (`modules/jarvis_bench.py`, `docs/architecture/JARVIS_BENCH_V0.md`): yeni worker/planner/model/hesap çalıştırmayan, `goal_executor`/GoalState/Completion Policy'ye dokunmayan saf bir değerlendiricidir; versiyonlu, salt-okunur bir case kataloğunu (`tests/data/jarvis_bench_v0.json`) daha önce üretilmiş bir gözleme (evidence + safety/permission sonucu + duration_ms) karşı PASS/FAIL/INCONCLUSIVE + reason_code olarak sınıflandırır. Bilinmeyen sürüm/alan, yinelenen case id ve effect-içeren case fail-closed reddedilir; duration_ms tek başına PASS üretmez. Test: `tests/test_jarvis_bench.py` (26 test, ağ/model/hesap gerektirmez).

- Ağ hata sınıflandırma testleri çevrimiçi/çevrimdışı durumunu açıkça taklit eder; yayın toplu işlem testi durumunu geçici klasöre yazar. Gerçek ağ ve kullanıcı ev dizini birim test önkoşulu değildir.

- Calculator operatör kanıtı: UIA ham ağaç gezintisi 500 öğeyle sınırlıdır. Yalnız gerçek Calculator sürecinin `CalculatorExpression` Text kontrolü ekran dışındayken salt okunur olarak dahil edilir; patterns boş ve işlem hedefi değildir. Ekran dışı kanıt tamamlanma/işlem başarısı sayılmaz. Operatör sonrası görünür ifade adı değişimi doğrulanır; mevcut sonuç ekranı kanıt sayılmaz.

- Açık `PC görev`/`PC görevi` ve `PC onayla` komutları model/rehber/geliştirme yorumundan önce sahiplik kontrolü yapan masaüstü motoruna gider. Görev kontrolünde fazla boşluk ve son noktalama temizlenir; iptal kalıcı görev kaydını kapatır. Telefon/aktif kullanıcı sınırı korunur.

- Hesap Makinesi pencere seçimi `calc`, `calculator`, `calculatorapp`, Türkçe belirtme eki ve `uygulaması` söylenişlerini tanır. UWP çerçevesi yalnız tam Calculator/Hesap Makinesi başlığıyla aday olur; açılış başarısı için UIA gerçek Calculator uygulama PID'sini doğrular. Genel `ApplicationFrameHost` veya tarayıcı başlığı açılış kanıtı değildir.

- UIA işlem yolunda pencereyi öne getirmek zorunlu değildir: Invoke/Value/Selection/Toggle doğrudan doğrulanan kontrole gider, genel fare/klavye girdisi gönderilmez. Taze HWND/ağaç imzası, uygulama/kök PID, gerçek kontrol kimliği ve sonuç geri okuması korunur. Birden fazla ilk hedefin seçiminde öndeki pencere hâlâ kullanılır; mevcut `window_shortcut` klavye yolunun odak kontrolü değişmez.
- Hesap Makinesi kimliği: `calc`, `calculator`, `calculatorapp` kabul edilir. `ApplicationFrameHost` genel olarak yetkili değildir; UIA ağacında `CalculatorResults` kontrolünün gerçek Calculator süreci bulunursa yalnız o uygulama PID'si seçilir. Her hedef kontrolün PID'si, gözlem ve işlem sırasında tekrar doğrulanır; devam kaydındaki uygulama PID'si değişirse görev durur. Tanınmayan uygulama adı hata mesajında görünür.
- Sonuç doğrulaması (`desktop_agent.expected`): kontrol ADI (`name`) karşılaştırılırken görünmez karakterler (ör. LRM), NBSP, baştaki/sondaki ve ardışık boşluklar yok sayılır (UIA `İfade değeri 12 + ` gibi sonda boşluklu ad verir); metin kesin aranır. Yazılan değer (`value`) ve `{'text'}` biçiminin `value` tarafı kesin eşitlikte kalır, şifre/ekran dışı/özel kontroller hiç eşleşmez.
- Hedef sayı denetimi (`desktop_agent._check_goal_numbers`): Hesap Makinesi'nde modelin beklediği ekran sayıları hedefteki sayılarla (girilen sayı/öneki ya da farklı hedef sayılarından işlem sonucu) açıklanamıyorsa işlem gönderilmeden reddedilir (ör. "15 ile 5 topla" için 19). Hedefte sayı yoksa, sayı sözcüğü ("beş") ya da mevcut sonuca gönderme ("sonuç", "ekran", "devam") varsa denetim kapalıdır. Yalnız model planı denetlenir; onay ve devam yolları değişmez. Sınır: ondalık ayracı ve işaret atlandığı için −1,5 ile 15 aynı sayılır.
- Hesap Makinesi görevi ilk kez başlarken (`history` boş) ekranda önceki işlemden kalan sıfırdan farklı bir sayı varsa model planlamadan önce `clearButton` (C) bir kez çağrılır ve `Ekran değeri 0` doğrulanır (`desktop_agent._clear_step`, denetimle aynı koşullar: hedefte sayı var, sayı sözcüğü/"sonuç"/"ekran"/"devam" yok). Temizleme doğrulanamazsa görev `waiting` olur ve hiçbir rakama basılmaz; devam eden görev yeniden temizlemez.
- Rakam düğmesi tutarlılığı (`desktop_agent._check_digit_entry`): `numNButton` düğmesine basan adımın beklediği ekran, düğmenin gerçekten üreteceği değerle uyuşmalıdır (işlem/eşittirden sonra yeni sayı rakamla başlar, aksi hâlde mevcut sayıya eklenir: 1 yazılıyken 7 ⇒ 17). Uyuşmazsa adım gönderilmeden reddedilir.
- Basit Hesap Makinesi aritmetiği koddan sürülür (`desktop_agent._arithmetic_script`): "12 ile 7 topla", "15'ten 5 çıkar", "6 x 7" gibi tek işlemli, üç haneye kadar tam sayı görevlerinde rakam ve işlem tuşları modele sorulmadan sırayla basılır, her adım UIA ekran kanıtıyla doğrulanır (işlem tuşu için ifade satırı, `automation_id` + olası adlar listesiyle: `+`, `−`/`-`/`Eksi (`, `×`, `÷`). Ekran temiz değilse, tuş yoksa, arayüz Türkçe değilse, ekranı değiştirmeyen bir adım varsa (7 ile 7, 0 ile 5), sonuç tam sayı değilse/negatifse/1000 ve üstüyse betik üretilmez ve görev eskisi gibi modele gider. Betik adımı doğrulanamazsa görev `waiting` olur.
- Güncelleme ZIP'indeki `.gitignore` ve `.gitattributes` kaynak dosyaları kapsam içindedir; klasör atlama listesi bunları düşürmez. Aday testleri sırasında asıl kaynak değişirse kurulum durmaya devam eder; bu kontrol gevşetilmez.
- Masaüstü pencere düzeltmesi: DWM tarafından gizlenmiş UWP pencereleri listelenmez. Aynı adlı birden çok gerçek pencerede yalnız hedefe uyan öndeki pencere seçilir; işlem seçilmiş HWND içindeki gerçek UIA kontrolüne gider. Önde hedef yoksa kullanıcı hedefi öne getirip devam eder. `PC görevi hesap makinesi 12 ile 7'yi topla` sesli biçimi `:` ve `|` olmadan tanınır; diğer doğal ifadeler bağlamlı yönlendiriciye bırakılır.
- Görev yaşam döngüsü: yeni açık `PC görevi: …` yarım kalmış (blocked/waiting/paused/question/approval) eski görevin yerine geçer, elle iptal gerekmez; gerçekten çalışan görev varsa (`_BUSY`) ikinci görev başlamaz. Sesli yanıt (`desktop_agent.spoken`) görevin gerçek durumunu söyler; başarısız görev için "sohbet ekranında hazır" denmez.
- UIA hızı: `desktop_uia._call` tek uzun ömürlü PowerShell sürecini kullanır (`desktop_uia.ps1` satır satır JSON okur/yazar); okuma ~0,55 sn'den ~0,2 sn'ye indi. Zaman aşımı, iptal veya hata olursa süreç öldürülür ve sonraki çağrıda yeniden başlar; tazelik, kimlik ve sonuç doğrulama kontrolleri değişmedi.
- Masaüstü uygulama izinleri ve kapsamı: bkz. `docs/agents/pc-masaustu.md` (onay, engelli uygulamalar, UIA güvenliği).
- Windows/Jarvis sayfaları model önerisi → Core kapalı allowlist → mevcut adapter yolundan açılır. `selfctl.execute` typed eylem alır; eski doğal dil page selector sahibi değildir.
- Windows Ayarlar yalnız `system_control.open_windows_settings` ve sabit `ms-settings:` kimlikleriyle açılır; pencere doğrulanmadan başarı iddiası yoktur. Yerel Jarvis ayarı Core şemasıyla kontrol edilir.
- Tek dosya işlemleri (`modules/file_ops.py`): kanonikal yürütme `files.mutate` → `engine_intents` → `file_ops.execute_typed`; kalan ham dil yolu `engine_commands._file_command` → `main_documents` (BRAIN-03 borcu). `engine_tools._extra_commands` artık `file_ops.handle` çağırmıyor. Yalnız Masaüstü, İndirilenler, Belgeler, Resimler ve Jarvis Dosyaları üst düzeyinde çalışır; silme ve üzerine yazma yoktur, eksik/belirsiz dosya sorulur, geri alma kullanıcıya özeldir; ayrıntı `docs/agents/dosya-belge.md`. Sembolik bağ ve `.lnk` işlenmez.
- Jarvis çalışırken kod değişirse yeni sesli yönlendirmeler ancak Jarvis yeniden başlatılınca devreye girer (çalışan süreç eski kodu bellekte tutar).
- Not Defteri yerel aracı yalnız belge metni alanına `fill` uygular; dosya adı/diyalog/menü ve açma/kaydetme adımları bu araçta çalışmaz. Kullanıcı düz metni kendisi kaydeder; kaynak değişikliği şifreli geliştirme yolunda kalır.

- Masaüstü kaynak koruması: yerel işlem motoru Hesap Makinesi ve Not Defteri'ne her zaman, diğer uygulamalara yalnız kullanıcı bir kez izin verirse açıktır (aşağıdaki "Uygulama izinleri" maddesi). Not Defteri yalnız adsız veya `.txt` başlıklı belgelerde çalışır; kaynak/ayar dosyası başlıkları engellenir. Tarayıcı işleri mevcut tarayıcı motorunda, kaynak değişiklikleri şifreli geliştirmede kalır. Yayın/güncelleme filtresi yalnız `modules/desktop_uia.ps1` betiğini özel olarak taşır; diğer `.ps1` dosyalarının kapsamı değişmez.
- Masaüstü görevleri (2026-10-11): `desktop_agent` kullanıcıya ait hedef/iş/geçmiş kaydını tutar; `desktop_uia` Windows UI Automation ile gerçek kontrol kimliklerinde invoke/fill/select/toggle çalıştırır. Koordinat tahmini veya rastgele klavye/shell yürütme eklenmez. Gönderilen işlem sonucu yeni kontrol ağacında doğrulanır; doğrulanmayan işlem körlemesine tekrarlanmaz. Onay eski ekran veya 120 saniye süre dolunca geçersizdir. Aynı fiziksel masaüstünde yalnız bir görev çalışır.
- Masaüstü kaynak düzenleme, terminal, şifre, ödeme ve gönderme işlemleri bu araçta kapalıdır. Kaynak değişiklikleri şifreli geliştirme akışında kalır. Görev turu 12, toplam görev 50 adımla sınırlıdır; yarım görevi sürdürmek yeni ekran okuması gerektirir. Windows UI Automation gerçek cihazda ayrıca sınanır.

- Komut yürütme (2026-10-11): uygulama açma/kapatma `ApplicationResult.ok` ile gerçek pencere kanıtı taşır. Hata metninin dolu olması başarı değildir. Belirsiz uygulamalar kullanıcıya seçtirilir; seçimin süresi 120 saniyedir ve oturuma özeldir. Doğrulanmamış uygulama adımından sonra çok adımlı komut durur.
- Niyet yönlendirici son konuşma ve bekleyen soruyu kullanıcıya özel, hassas bilgiler temizlenmiş bağlamla alır. `clarify` işlem yapmaz; `task` mevcut sınırlı görev motorunu çalıştırır. Normal sohbet işlemi gerçekleştirmiş gibi anlatmamalıdır.
- Şifreli geliştirmede `test` aracı aday kopyayı sınar; uygulama izni vermez. Tur başına en çok üç test çalışır, hata modelin düzeltmesi için geri döner. Taslağın içerik imzası değişince önceki test geçersiz olur. Kaynağa uygulama ve yeniden başlatma korumaları devam eder.

- Tek pencere: `web_window.open_window` açılışı `_window_lock` ile seri hale getirir; pencere başlığı/SSE henüz oluşmadan tepsi/küçük Jarvis tekrar çağırırsa 15 saniyelik açılış rezervasyonu ikinci tarayıcı penceresini engeller. Görünür pencereye "show" başarı döndürür ve öne getirir. İşletim sistemi süreç kilidi `instance.py` içinde ayrıca korunur.

- Tek paket kurulum: `scripts/kurulum.bat`, çekirdek kilit + `requirements-bundle.txt` eklerini aynı pip çözümlemesinde kurar; Chromium, Hey Jarvis ve Whisper small hazırlanıp doğrulanmadan çalışan `.venv` değişmez. Ek paket kilidi çalışan PC'den üretilir. `scripts/kurulum_ekleri.py` ayar/anahtar değiştirmez, özel Python eklentilerini import etmeden raporlar.
- Temizlik yalnız bilinen eski arayüz/atölye dosyaları ve kaynak ağaçlarının Python/linter önbelleklerini kaldırır. `.venv`, Android, `.claude`, kullanıcı verileri, anahtarlar, modeller ve günlükler korunur. Kurulum başında Jarvis kapalı olmalıdır.

- İsteğe bağlı yerel STT: `modules/local_stt.py`, `local_stt_enabled` (kapalı), `local_stt_model` (small/base). İlk sürüm yalnız masaüstü Konuş düğmesinde; etkinleşme/değişen mikrofon akışı yeniden başlatma gerektirir. Yerel denemede VoiceSession Gemini Live ve arka plan uyandırmayı başlatmaz. Whisper'ın sessizlikte uydurduğu cümleler (ör. "Altyazı M.K.") `local_stt._fabricated` ile süzülür (kalıp listesi + `no_speech_prob`/`avg_logprob`/`compression_ratio` eşikleri); süzülünce sonuç boştur, komut gitmez. Kayıt bitince arayüz "thinking" durumuna geçer (`voice.listen(on_captured=)`); anlaşılmazsa Gemini yolundaki gibi "Anlayamadım" söylenir, ses yine buluta gitmez. Ayarlar › Özel kelimeler (`stt_words`) yerelde de Whisper'a `initial_prompt` olur (`local_stt.hint_prompt`, en çok ~200 karakter); modelin ipucunu çıktıya geri yazması süzülür. `local_stt_beam` (1-5, varsayılan 5; Ayarlar › Ses › Yerel ses hızı) hız/doğruluk dengesidir ve yeniden başlatma gerektirmez. Açılışta `local_stt.preload` yalnız ayar açık ve model zaten inmişse modeli arka planda belleğe alır; indirme ve ağ yoktur.
- Model yalnız Ayarlar › Ses › Modeli indir çağrısıyla, Normal modda indirilir; tanıma yerel dosya/tokenizer kullanır, hiçbir hatada buluta geçmez. faster-whisper isteğe bağlıdır, kilit dosyası ancak çalışan PC ortamından güncellenir. Kurulum/PC testleri: `docs/YEREL_SES.md`.

- Windows'ta `run_tests.bat` çalıştırılır (`python -X utf8 -m modules.validation`). Bu komut tüm Python testlerini, `node --check webui/*.js` kontrolünü ve `JS_GROUPS` içindeki Node testlerini çalıştırır. Testler geçerse güvenli başlangıç kontrolü olarak yalnız `launcher.DEPENDENCY_IMPORTS` içe aktarılır (kurtarma, temizlik, mikrofon ve servis başlatılmaz; hata kodu 2). Python yolu argüman verilirse (`run_tests.bat .venv\Scripts\python.exe`) sonda `pause` beklenmez.
- Yeni bir Node testi eklenince adı `modules/validation.py` → `JS_GROUPS` listesine yazılır.
- Linux test ortamı (bulut/CI, 14 Ekim 2026): `bash scripts/linux_test_kurulum.sh [--test] [venv]` (varsayılan `.venv`; içinde `Scripts/` olan Windows ortamına dokunmaz). `requirements.lock.txt` değiştirilmez: yalnız Windows'a özgü `comtypes`, `pycaw`, `pypiwin32`, `pywin32`, `WMI` atlanır, kalan sabit sürümler `--no-deps` ile birebir kurulur; `requirements-bundle.txt` ekleri (python-pptx dahil markitdown[docx,xlsx,pptx], faster-whisper, playwright) kilit kısıtıyla dolaylı bağımlılıklarıyla kurulur; pystray/pyautogui'nin yalnız Linux'ta istediği `python-xlib`/`python3-xlib` eklenir. Ardından kilit sürümleri, `pip check` (yalnız openwakeword'ün Linux `tflite-runtime` isteği bilinen eksik) ve ana içe aktarmalar doğrulanır; `--test` ile `modules.validation` çalışır. Eksik paket test atlanarak gizlenmez; bu ortamda testlerin "import" hatası vermesi paket kurulmadığı anlamına gelir. Windows kurulumu (`kurulum.bat`) değişmedi.
- Geliştirme ortamı (Claude Code ajanı, kurulum betiği, Headroom, kota tercihleri) `docs/GELISTIRME_ORTAMI.md` dosyasındadır. `jarvis-kural-denetcisi` asıl dosyası `tools/claude/agents/` altındadır; `tools/claude/kur-ajanlar.ps1` onu Git dışındaki `.claude/agents/` klasörüne kurar. Denetçi yalnız açık istekle veya PR öncesinde çalışır, dosya değiştirmez.
- Testler gerçek mikrofon, hoparlör, Windows ses aygıtı ve canlı model denemesinin yerini tutmaz. Bunlar Hamdi'nin PC'sinde ayrıca denenir.

- Tek kurulum temizliği: eski ayrı uyandırma ve tarayıcı kurulum BAT dosyaları paketten kaldırıldı; mevcut PC kurulumundaki kopyaları kurulum_temizligi.py temizler. Rehber ve hata mesajları kurulum.bat yönlendirir.

- Git eşitleme: .venv_install/.venv_backup, modeller, kişisel veri ve .claude kaynak yayınlama ve karşılaştırma dışında kalır; .gitignore/.gitattributes kaynak takibine dahildir. Yerel günlükler depoya gönderilmez.

- İzin politikası (`modules/permission_policy.py`): kullanıcıya özel `yol:sınıf` → Sor/İzin ver/Engelle. Varsayılan Sor (kapının kararı). Engelle masaüstü, tarayıcı ve gönderim yollarında kesin ret olur (izin veya onay ezemez); İzin ver yalnız yıkıcı yerel işte sorulanı açar, gönderim izni ve yayın onayı değişmez; para/kimlik ve sistem ayarı sınıfları kilitlidir. Politika hatası işlemi yapmaz.

- Haber konu terimleri: “son dakika” genel haber ifadesidir; “haberleri” konu üretmez. Bağımsız “dakika” ve gerçek konu sözcükleri korunur; ilgisiz makale reddi devam eder. Bu ayrım kaynak seçiminin veya canlı haber kabulünün kanıtı değildir.

- Hedef durum özeti hem goal_executor.handle hem engine_queue.submit girişinde kullanılır; açık ayrıntılar komutu render kullanır. Gerçek arayüz kabulü ayrıca ölçülür.

- Hedef planlama turu toplam 120 sn bütçeyi model beklemesinde ve yeni planlama turundan önce denetler; doğrulanmış yeni çıktı olmadan üç geçersiz karar duraklatır. Kayıt/çıktı korunur, yeni açık devam yeni tur bütçesi alır. Devam eden senkron dış işlem zorla kesilmez; bu sınır fiziksel işlem iptali garantisi değildir.

- Açık hedef komutu öneki görev metnine dahil edilmez: hedef … ve hedef: … kontrol komutlarından sonra, eski soru cevabından önce ayrılır. Görev içindeki gerçek hedef sözcükleri korunur; kaynak/konu/izin doğrulaması gevşetilmez.

- Genel haber keşfi isteğe göre AA/BBC Türkçe/DW Türkçe/Euronews Türkçe dizinlerini, kurum araştırması mevcut kurum kataloğunu kullanır. Kayıtlı adres canlı erişim kanıtı değildir; genel haber tamamlanması iki yayıncıdan tarihli tekil makale ister.

- DPÜ kullanıcı isteğiyle otomatik haber kataloğundan çıkarıldı; açık kullanıcı adresinin güvenli okunması ve eski makale ayrıştırıcıları korunur.
- Mynet Haber ve Investing Türkçe genel kataloğa eklendi; dört varsayılan dizin (Mynet/Investing/AA/BBC) ve DW/Euronews alternatifleri mevcut toplam adım/zaman ve makale kanıtı sınırları içinde kalır. Katalog kaydı canlı erişim kanıtı değildir.
- Hamdi'nin seçtiği NTV, T24, Bloomberg HT, Ekonomim, KAP, DonanımHaber, Webtekno ve TRT Haber Türkçe keşif alternatifleridir. KAP şirket açıklaması kaynağı olarak etiketlenir; katalog kaydı haber okuma/işlem yetkisi veya canlı kabul kanıtı değildir.
- Genel web araştırması ve tarihli haber okuması ortak anlamsal gövde temizliğini kullanır. Sonuçta bulgu varsa keşif listesi ayrıca dökülmez; kaynak URL'si kısaltılmaz, haber başlık/tarih/kısa alıntıyla gösterilir. Bu sunum değişikliği yeni tamamlanma veya kaynak doğruluğu garantisi değildir.
- VideoObject sayfasının yazılı açıklaması yalnız tek video kimliği, tam canonical/URL/başlık, ortak main içindeki tek makale/tek bölüm ve kendi uploadDate tarihiyle okunur. Video izlenmiş veya ses dökümü alınmış sayılmaz; sohbet ve rapor bunu açıkça belirtir.
- Dosya istemeyen haber hedefinde yanlış writer seçimi yazma başlamadan sohbet teslimine yönlendirilir; yeterli kanıtla tamamlanır, eksik kanıt kısmi gösterilir. Gerçek dosya istekleri ve diğer iş türleri korunur. Mevcut haberlerle modelsiz toparlanan hedef yeniden planlayıcı beklemez.

- 28 Ekim 2026 haber keşfi: HTML bağlantıları bulunsa da sayfanın açıkça ilan ettiği aynı-host RSS/Atom önce denenir (en çok mevcut iki feed); hata/boş sonuçta HTML korunur. HTML haber kartı/başlık bağlantıları gezinme bağlantılarından önce sıralanır; bilinmeyen adresler atılmaz. Tekil makale/tarih/konu/iki yayıncı kanıtı ayrıca zorunludur. Dört taşıyıcı-taklitli regresyon eklendi; canlı kabul bekliyor.

- 28 Ekim haber/araştırma kapanışı (PR #439): haber completion eşiği `news_pipeline.enough_evidence` içindedir; dosyalı kurtarmanın ayrı tohum/katalog sayım hattı kaldırıldı. Mühürlü pipeline snapshot'ı normal runtime gate ve WorkerResult fence üzerinden teslim edilir. Araştırma claim'inde değer, ölçüm kapsamı ve referans dönemi kaynakla bağlanır; model hatasında ek claim çağrıları kesilir. Ayrıntı/kalan canlı kabul: `docs/agents/haber.md` ve `docs/BEKLEYEN_ISLER.md`. Tam Windows ve normal Jarvis kabulü olmadan kapanmış sayılmaz.

- PR #439 tam Windows doğrulaması 0785750'de 3.287 testte 1 FAIL/2 ERROR verdi: kaldırılan geography bypass argümanı, eski HTTP taşıyıcı taklidi ve haber devamında gereksiz model beklentisi. Regresyonlar yeni gerçek sözleşmeye bağlanır; coğrafya/HTTPS/kota korumaları geri alınmaz. Yeni head'in Windows ve PC sonucu ayrıca beklenir.

- PR #439 haber keşfi: query sıralaması generic haber/komut sözcükleriyle HTML makale önceliğini bozamaz; domain_tools ortak model_free_news.terms kullanır. Pipeline ret nedenlerini sınırlı özet olarak saklar; kabul raporu aday/okunan/pencere-dışı sayısını, makale retlerini ve kaynak hata nedenlerini gösterir. Bu tanı alanları completion veya retry yetkisi değildir.

- PR #439 --news kabulü artık üç zorunlu gerçek akışı çalıştırır: genel sohbet, Türkiye AI sohbeti ve Türkiye AI dosyası. Ortak news_chat_resume ancak üçü de geçerse passed olur. Model denemeleri bloke edilip sayılır; kota yolu zorlanır; hedef ve dosya deposu geçici/yöreye yalıtılır. Hiçbiri ücretli/model çağrısı veya gerçek kullanıcı dosyası yazımı başlatamaz.

- PR #439 konu keşfi: query puanlaması public_sources.entries içinde 50-link kesiminden önce yapılır; domain_tools ikinci/sonradan sıralama otoritesi taşımaz. Generic haber isteği HTML makale önceliğini korur. Pipeline kaydı en fazla 12 redakte URL/ret çifti ve ayrı anahtarsız keşif durumunu saklar; tanı alanları başarı veya ek retry yetkisi değildir.

- PR #439 gerçek sayfa teşhisi: farklı SEO/H1 başlığı olan NewsArticle ancak açık URL kimliği + tek eşleşen canonical + DOM'da gerçek articleBody çıpası ile bağlanır. mainEntityOfPage nesnesindeki url/@id tanınır; çelişkili/yabancı referans reddedilir. meta name=datePublished yayın tarihi kabul edilir; dateModified yayın yerine geçmez. Tam sayfa HTML/izleme verileri depoya alınmaz.


- PR #439 yayıncı taraması takip düzeltmesi: URL kontrol karakterleri reddedildikten sonra yalnız çevre ASCII boşlukları temizlenir. Galeri/dizin yolları ilk adaylardan geriye sıralanır; konu skoru ve bilinmeyen yollar korunur. HTTP şema kimliği yalnız HTTPS nihai yanıt adresiyle host/standart port/path/query eşitliğinde metadata olarak karşılaştırılır, HTTP indirilmez. Geçerli çelişkili canonical reddedilir; farklı başlık için eski canonical+gövde çıpası şartı sürer. Kota/model/okuma bütçesi artırılmaz.


- PR #439 ajans okuyucuları: ANKA aynı metinli yinelenen H1'leri yalnız tek şema başlığı ve nihai HTTPS adresine bağlı kimlikle birleştirir. İHA tek haber widget'ı, eşleşen canonical, tek H1/gövde ve widget içindeki tek yayın tarihini ister; bozuk JSON'u onarmaz. İLKHA tek haber kapsayıcısı içindeki h3/gövde/tarih ve nihai URL ile eşleşen paylaşım adresini kullanır. CMS'nin System.String[] og:url alanı kimlik sayılmaz; diğer çelişkili açık og:url reddedilir. Model/okuma/kota bütçeleri değişmez.


- PR #439 --news: news_external_discovery ayrı canlı tanıdır. Katalog sayısı sıfıra zorlanır; gerçek anahtarsız arama/üretim makale okuyucusu kullanılır. Katalog dışı en az bir doğrulanmış makale yoksa failed olur. Bu tek kaynak keşif kanıtıdır, iki yayıncı tamamlanma kabulü değildir. Mevcut üç senaryolu news_chat_resume korunur. Yeni head için Windows/PC sonucu beklenir.


- PR #439 dış arama tanısı: DDG challenge/engel ve tanınmayan HTML artık gerçek sonuç-yok sayılmaz; sabit public_search_blocked/public_search_unrecognized nedeni üretilir. Açık no-results işareti boş sonuç kalır. news_external_discovery kalıcı raporunda redakte pipeline reason görünür. Yeni sağlayıcı/retry/model çağrısı/kota artışı yok. 4 yeni taşıyıcı-taklitli test + 105 odaklı test geçti; gerçek PC yanıtının engel mi şema değişimi mi olduğu henüz doğrulanmadı, yeni head kabulü beklenir.


- PR #439 Windows #855: 3321 testte tek FAIL, RecoveryPipelineEvidenceTests sabit 2026-10-21 haberi 29 Ekim'de 7 günlük pencereden çıktığı için düşmüştür. Bu wiring testi istanbul_today() tarihli feed ve receipt kullanır; üretim freshness kuralı değiştirilmez. Sözdizimi kontrol edildi; yeni exact-head tam CI/PC kabulü beklenir.


- PR #439 haber dış keşfi: search_news_public önce DDG'yi dener; hata halinde yalnız bir Bing News RSS fallback yapar. Gerçek boş DDG sonucu, PermissionError ve Cancelled fallback başlatmaz. Bing wrapper yalnız www.bing.com/news/apiclick.aspx üzerindeki tek url parametresini açar; hedef public_sources.address ve gerçek makale doğrulamasından geçer. RSS başlık/tarihi kanıt değildir; DTD/entity/büyük RSS reddedilir. Genel search_public değişmez. Proxy tanısı canlı taşıyıcı kabulü değildir.


- PR #439 Windows #858 tek FAIL: broad-catch diagnostic ilk işlem olmalı. search_news_public except bloğunda kayıt iptal kontrolünün önüne taşındı; izin/iptal propagation ve fallback bütçesi korunur. AST diagnostic kontrolü ve 4 fallback regresyonu geçti; yeni exact CI/PC sonucu beklenir.


- PR #439 haber dış keşfi: DDG gerçek boş sonucu da tek Bing yedeğini çalıştırır; aynı sağlayıcı retry yoktur. Bing kullanılabilir URL üretmezse public_news_rss_empty içinde RSS item sayısı raporlanır; sessiz empty/neden=yok durumu kaldırılır. İzin/iptal ve makale kanıtı şartları değişmez. 5 fallback testi geçti; canlı neden henüz ayrılmadı, yeni exact kabul beklenir.


- PR #439 haber arama sorgusu: news_search_query yalnız haber araması için son-N-zaman penceresini ve rapor/dosya komut sözcüklerini ayırır. Konu/coğrafya ve açık tarih yılı korunur; konu yoksa güncel haberler kullanılır. Asıl kullanıcı isteği doğrulama/completion otoritesi olarak değişmez. Aynı RSS ucunda görev cümlesi 0, güncel haberler 10, Türkiye yapay zeka 12 öğe verdi (proxy tanısı, iş-PC transport kabulü değil). Önce 4 eksik-helper regresyonu düştü; sonra 9 sorgu/fallback testi + 105 mevcut odaklı test geçti. Yeni exact Windows ve PC kabulü beklenir.


- PR #439 dış keşif kabul ayrıntısı en fazla 8 adayın redakte URL, canonical publisher_key ile katalog içi/dışı, verification ve ret nedenini gösterir. Acceptance eşiği korunur; üretim arama/okuma sayısı artmaz. Yerel taklitli ret-sınıflandırma kontrolü geçti; a80e1db iş PC sonucunda 8 aday/8 deneme/0 katalog-dışı doğrulama görüldü, kök ret nedenleri henüz bilinmiyor. Yeni exact kabul beklenir.


- PR #439 dış aday seçimi: external_candidates açık kategori/etiket/haberleri yollarını okuma öncesi ayırır; canonical publisher_key başına en fazla bir aday, toplam en fazla 8 seçer. MSN alan adı tümden engellenmez. Arama sonucunun provider alanları public_discovery ve kabul ayrıntısında görünür. Tarih/kimlik/gövde doğrulaması değişmez. 3 yeni seçim regresyonu + 105 odaklı test geçti. 1e4db51 canlı örnekleri 3 dizin/2 eski haber/2 HTTP429/1 gövde reddiydi; yeni exact Windows/PC kabulü beklenir. Arama tarih filtresi henüz eklenmedi.


- PR #439 Bing haber keşfi orijinal istek penceresi <=7 gün ise qft zaman ipucu (gün/hafta) ve sortbydate=1 gönderir. Bu filtre destek/etkinliği henüz canlı doğrulanmadı; proxy denemesi timeout verdi. RSS pubDate açıkça pencere dışındaysa aday atlanır; tarih eksik/geçersizse makale okuyucu karar verir, RSS kanıt değildir. Tarihsel yıl isteğine yakın-zaman filtresi eklenmez. Yalnız news_external_discovery kabulünün searcher adaptörü katalog içi yayıncıları dışlar; production araştırma katalog içini dışlamaz. 8 fallback testi + 105 odaklı test geçti; yeni exact Windows/PC sonucu beklenir.

- Haber kabul tanısı: son-rapor dosyası başka PR ile değişebilir. Watcher reports/<exact-sha>.json arşivini silmeden korur; arşiv yazılamazsa worktree silinmez. --news kabulü eski watcher altında da LOCALAPPDATA/Jarvis/pc-acceptance/news-reports içine yalnız redakte haber kontrollerini zaman damgası ve kod parmak iziyle yazar. Kod parmak izi commit SHA kanıtı değildir. PR tanısı 300 karakterde kesilmez; başarısız dış keşif kontrolü de gösterilir. Bu kayıt iyileştirmesi Türkiye AI canlı arızasını çözülmüş saymaz; yeni exact kabul beklenir.

- Hoca açık web araştırması ilk okunamayan kaynağı atlar; aynı ortak research_providers araması/okuyucusu kullanılır. En fazla 10 aday okunur; izin ve iptal hataları başka adaya geçmez. Ek model veya arama sağlayıcısı çağrısı eklenmez.

- Yerel model seçimi ve kabul kuralları: `docs/agents/guncelleme-ci-kota.md` (#434).


- Yerel model kabulü gerçek kurulu listeye bağlıdır; belirli bir model adı veya boyutu şart değildir.

- Provider/Hoca tanısı: yerel timeout, sunucu yokluğundan ayrılır; Hoca güvenli exhausted nedeni ve reason-code/recovery bilgisini korur. Router tablosu backend effective modelini gösterir; çağrı özeti tablodan önce gelir. Tanı düzeltmesi canlı model kabulü değildir.

- Hoca arama hata sınırı: `docs/agents/hoca.md`.

- Brain model kararı, çıktı/teşhis, learning/Git/update: `docs/agents/gorev-cekirdegi.md`. Kullanıcı/makro: alan notu.

- BRAIN-05: goal_intent CAS asıldır. BRAIN-07: Core/journal bağlanır; tam kanıtlı sonuç kurtarılır; Gmail indeksli okuma yalnız Core-kabul+project edilmiş listeye bağlanır.

