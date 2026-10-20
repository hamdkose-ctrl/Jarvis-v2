# Merkezi ayrım — mevcut motor içinde aşamalı geçiş tasarımı

20 Ekim 2026. Durum: tasarım; kaynak kodu uygulanmadı. Taban main `7563161`; açık #213 (62-B) goal_executor.py sahibidir ve GitHub ödeme/Actions harcama engeli nedeniyle CI başlamamıştır. Bu belge CI engelini veya tek dosya sahibi kuralını aşmaz.

## Hedef ve kapsam

Ses/yazı isteği, kullanıcı ve geçerli bağlamla tek karar sözleşmesine çevrilir. Bir istek bir kez yürütülür; alan içi ayrıştırıcılar korunur. Her araç adımı mevcut izin kapısından geçer. Hesap Makinesi/video açma gibi tek örnekler bir alanın tam kabulü sayılmaz. 14 alanın hedef kapsamı [birleşik plandadır](yol-haritasi-birlesik-2026-10-20.md).

Seçenek A (önerilen): mevcut motorun önüne yan etkisiz karar üretimi, gözlem, sonra alan alan geçiş. Mevcut finance.parse ve diğer saf eşleştiriciler yeniden kullanılır; ikinci yürütücü/depo açılmaz.

Seçenek B: bütün handler sırasını tek seferde yeni bir yönlendiriciyle değiştirmek. Geniş regresyon ve eski bağlam kaybı riski nedeniyle seçilmez. Bu belge seçenek A için incelemeye hazır tasarımdır; yeni kaynak kodu kartını kendiliğinden başlatmaz.

## Koddan doğrulanan mevcut sınırlar

| Yer | Bugünkü davranış | Geçiş için sonuç |
|---|---|---|
| engine_commands.handle | engine_control → job_front → belirli goal kontrolleri → command_manager.dispatch → tekrar goal.handle → pending/alan yolları → finance.answer → model yönlendirme | Handler sırası davranışın parçası; yalnız “önüne classify koymak” yeterli değil |
| command_manager.dispatch | PC/görev akışı/pending_action ve başka yolları gerçekten çalıştırabilir | Gölge sınıflandırıcı dispatch çağırıp “hangi handler?” diye deneyemez |
| goal_executor.handle | Taze question kaydı sonraki cümleyi cevap sayabilir; hızlı komut istisnaları var | #213 finans için dar düzeltme; genel bağlam sahipliği bunun ötesinde |
| command_manager.PENDING_INPUT_FIELDS ve job_front._PENDING | Farklı listeler; _pending_photo runtime üzerinde, hedef sorusu kalıcı kayıtta | Tek listede birleştirmeden önce sahiplik ve geçerlilik farklılıkları belgelenir |
| engine_tools.route | Son konuşma ve pending_request maskelenerek router.classify'a gider; sonrasında pending_request temizlenir | Gölge sınıflandırmada çağrılamaz: model maliyeti ve durum değişikliği var |
| router.classify | Bazı hızlı kurallar, sonra model intent/args; work_modes ve outcome_contracts davranışları var | Yeni INTENT isimleri mevcut handler intent adlarını toptan değiştirmez; eşleme adaptörü gerekir |
| engine_voice._live_command | owner/rid yakalar, source=ses ile runtime.handle çağırır | Ortak girişe bağlanabilecek mevcut yol |
| engine_voice.prepare_live_tool | Yakalanan owner/rid altında verilen fn'i doğrudan çağırır | Ses/yazı eşliği yalnız handle testinden çıkarılamaz; doğrudan araç envanteri ayrıca gerekir |
| permission_classify / permission_gate / permission_policy | Eylem sınıfı, allow/ask/deny ve kullanıcı politikası | Giriş sınıflandırması bunların yerine geçmez |

Bu okuma bütün ses araçlarının envanteri veya mevcut yolların tamamının güvenlik denetimi değildir. Özellikle doğrudan ses araçları için kayıt noktaları ve çağıranlar uygulama kartında tek tek çıkarılmalıdır.

## Karar sözleşmesi (öneri, henüz API değil)

- request: mevcut owner, rid, source, özgün kullanıcı metni ve normalleştirilmiş metin. Rid korunur; yazım düzeltmesi ikinci yürütme oluşturmaz. Metin yalnız işlem belleğinde; karar günlüğünde ham metin tutulmaz.
- intent: SESSION_CONTROL / CHAT_QUESTION / TASK / RESEARCH_LONG_TASK / CLARIFY. SESSION_CONTROL için ayrıca cancel/continue/approve/reply gibi control_kind.
- domain: GENERAL / PC / WEB / FILE / FOLDER / MAIL / CALENDAR / NEWS / FINANCE / MESSAGING / LEARNING / SELF_CONTROL. Karma görevde üst domain GENERAL olabilir; alt adımlar kendi alanını taşır.
- effect_hint: mevcut izin sınıfı veya UNKNOWN; karma görevde adım bazında çözülmek üzere bekler. Bu alan izin değildir. Metinden belirsiz “read” çıkarılıp bütün plana yapıştırılmaz.
- route_key: sınırlı izinli hedef adı; key üzerinden import/eval/getattr ile modelin keyfi kod seçmesi yok. Legacy intent ile eşleme açık tabloda yapılır.
- binding: bekleyen işlemin türü, mevcut kimliği/sürümü, beklenen cevap türü ve geçerliliği; yoksa None.
- decision_kind: MATCH / CLARIFY / NO_MATCH; bilinmeyen ifade NONE/read etiketiyle otomatik yürütülmez. NO_MATCH yalnız mevcut izinleri koruyan eski sınıflandırma yoluna devredilebilir; gölge sonuç yürütmeyi yönetmez.
- reason_code: sınırlı sabit gerekçe (explicit_control, independent_query, matching_reply, ambiguous_binding vb.); modelin serbest gerekçesi güvenlik kararı olmaz.

Saf karar üreticisi profil kaydetmez, pending tüketmez, model/ağ/ekran/cihaz çağırmaz, görev başlatmaz. Girdi anlık görüntüsünü giriş adaptörü hazırlar; sınıflandırıcı aynı girdide aynı sonucu üretir. Sağlık yoklaması sınıflandırma değildir. Bekleyen kayıt tam bir kopya olmak zorunda değil; karar, tüketim anındaki kimlik/sürüm/tazelik denetimine referans taşır.

## Bekleyen bağlamın sahipliği

Yeni paralel pending deposu kurulmaz. Mevcut session/pending_photo/goal/app kayıtlarından sınırlı salt okuma görünümü üretilir. Her tür için mevcut süre ve iptal kuralları korunur; tek genel timeout icat edilmez. Süresiz eski kayıt açık onay gibi kullanılamaz; uyumluluk kartı gerekir.

1. Bağlam mevcut kullanıcı ve giriş kaynağının yetkileriyle sınırlandırılır. PC sahibinin yakalanması ve telefon/konuk sınırları korunur.
2. Açık kimlikli kontrol ilgili kayda bağlanır; yanlış kullanıcı/kimlik/hash/süre hiçbir işlem doğurmaz.
3. İptal/devam/onay bağlam denetiminden geçer. Bağlamsız iptal yeni görev oluşturmaz. Genel “onayla” dış gönderimin mevcut kimlikli onay şartını aşamaz.
4. Açık bağımsız komut (kur, plan, mail listesi) eski soru tarafından yutulmaz. “6 dolar” alıcı adresi cevabı değildir.
5. Cevap türü doğrulanmış eşleşme ise ilgili kayda gider. “Ankara” şehir sorusuna, e-posta adresi alıcı sorusuna uygundur; her kelime her soruya cevap değildir.
6. “6 dolar” bir tutar sorusuna cevap da olabilir: hem geçerli cevap hem bağımsız istek adayıysa belirsizlik sorulur veya açık kimlikli yanıt kullanılır. Bu gelecek davranış #213'ün genişletilmesi sayılmaz; #213 finans sorusuna öncelik veren dar karttır.
7. Birden fazla eşit derecede geçerli bağlam varsa sessizce ilki seçilmez. Kullanıcıya gizli içerik göstermeyen kısa seçim sorulur. Bağlamlar arası onay devri yoktur.
8. Tüketim yürütme sınırında yeniden doğrulanır; karar ile yürütme arasında iptal/değişim olduysa eski karar uygulanmaz. Gölge karar pending temizleyemez.

## Güvenlik ve dış etki

INTENT, DOMAIN ve EFFECT bağımsızdır. “Mail nasıl gönderilir?” açıklama sorusudur; mail sözcüğü gönderim niyeti değildir. “Ali'ye raporu gönder” görevdir fakat kesin alıcı/içerik çözülmeden gönderim yetkisi oluşmaz. “Bu maili taslaklara kaydet, gönderme” talimatındaki olumsuzluk korunur.

Giriş effect_hint tahmindir. Her adım eylem ve parametreleriyle mevcut sınıflandırıcı/kapı/politika üzerinden yeniden değerlendirilir. Kaynak web/mail/dosya metni kullanıcı niyeti veya alıcı onayı olamaz. allow/ask/deny, kilitli money_credential/system_config ve her seferinde onaylı physical kuralları değişmez. Kullanıcı “yap” dedi diye yeni mali işlem desteği açılmaz.

Tıklama/araç dönüşü başarı kanıtı değildir. Sonuç verify/evidence ile doğrulanır; belirsiz dış etki reconcile gerektirir. İstek tekrarında ikinci gönderim/yayın yoktur. Gözetimsiz kuyruk ve doğrudan ses araçları mevcut izin/işlem sınırlarını korur.

## Aşamalı kartlar ve izinli dosya adayları

Her kart ayrı onaylanmış kapsam/dal/PR ile yürür. Aşağıdaki dosyalar adaydır; uygulama başlamadan çağıranlar ve açık PR'lar doğrulanır. CI engeli sürerken kaynak kartları birleştirilmez.

| Kart | İş ve aday dosyalar | Geçiş kanıtı |
|---|---|---|
| M0 | Bu tasarım ve PC matrisi; yalnız docs | İncelenebilir sözleşme; uygulanmış iddiası yok |
| M1 | Saf karar türü/üreticisi (yeni dar modül) + unit test; mevcut saf finans/oturum biçimleri | Tablo örnekleri; ağ/model/dispatch/mutasyon çağrısı sıfır; aynı girdi aynı karar; yanlış kullanıcı/belirsizlik testleri |
| M2 | Salt bağlam adaptörü ve gölge karşılaştırma; engine_commands/command_manager/engine_tools bağlantıları ayrı dar kartlara bölünür | Eski yol yalnız bir kez çalışır; eski side-effect handler'ları aday bulmak için çağrılmaz; gözlem açık/kapalı davranış eşitliği |
| M3 | İlk alan FINANCE: mevcut parse ve answer, pending etkileşimi | #213 önce sonuçlanmış; kur ve gerçek soru cevapları korunmuş; tüm giriş türlerinde eşdeğer karar |
| M4 | SESSION_CONTROL ve bekleyen bağlamlar tür tür; job_front/goal_executor/command_manager | İptal/onay/devam, kimlik/hash/süre, fotoğraf/uygulama/goal çakışması; eski kayıtlar korunur |
| M5 | Plan/mail okuma gibi diğer düşük riskli alanlar, sonra riskli alanlar ayrı kartlar | Eski kurallar ve negatif cümle seti; her adımda kapı ve çift yürütmeme |
| M6 | Doğrudan ses araçlarını ortak sözleşmeye bağlama, telefon sınırı ve görev yaşam döngüsünü tekleştirme | Gerçek çağıran envanteri; rid/owner korunur; tek yürütme; ses ve yazı davranış kabulü |
| M7 | Kanıtlanmış eski yönlendirme dallarını kaldırma | Her eski dalın eşleniği, test kapsaması, eski kayıt fixture'ı ve geri dönüş planı; kullanılmayan sanılıp toplu silme yok |

M1 sonucunu kullanmak için yeni bir model çağrısı eklenmez. Gölge karşılaştırmada eski nihai yolun ölçümü için yan etkisiz sınır işaretleri eklenir; handler'ı ikinci kez çalıştırarak ölçüm yapılmaz. Günlük: rid, anonim/sınırlı owner bağlamı, source, karar yolu, reason_code ve uyuşmazlık türü; sırlar/ham konuşma/ek/ekran içerikleri yok. Yerel kullanıcıya özel, sınırlı saklama; otomatik bulut aktarımı yok. Gözlem kaydı hatası başka bir yürütme başlatamaz.

Geri dönüş: bir sonraki kartı durdur; daha önce doğrulanmış eski yönlendirme sürümüne kontrollü dön. Yan etkisi belirsiz işlemi tekrar çalıştırma. Yeni yönlendirme arızasında dış etkiyi eski yoldan kör deneme yok; izin ve idempotency her durumda korunur.

## Test planı ve gerçek kabul

Mevcut tests/test_routing_sentences.py model cevabını taklit eden router kural regresyonudur; gerçek engine önceliği, gerçek model doğruluğu veya mikrofon kabulü değildir. Yeni testler bu seti zayıflatmadan dört katmanı kapsar:

- Saf karar ve tipli bağlam: cümle/owner/source/pending → karar; hiçbir yan etki yok.
- Gerçek EngineContext.handle: handler önceliği ve çağrı sayısı; fake kur/ağ/model; diğer kullanıcıya sıfır işlem. Mevcut pending_goal_yields, job_front, stale_goal_and_quota ve finance_bare_amount korunur.
- Yürütme/izin: yanlış alıcı, kaynak enjeksiyonu, deny+approve, taze olmayan onay, çift istek ve unknown dış etki için gerçek kapı + fake adaptör.
- Gerçek PC: [PC matrisi](PC_TABAN_KABUL_20261020.md); ses tanıma ve UIA ayrıca. Dış gönderim/para/cihaz kabulü yalnız ayrıca açık hedef/içerik/hesap izniyle yapılır.

Önce düşen test, dar yama, fiziksel kaynak satırı mutasyonu, tam modules.validation, head'e ait yeşil CI ve izinli diff zorunludur. Beklenen eski davranış değişiyorsa PR açıkça listeler; testi yeni koda uydurarak başarı üretilmez. Bu belgedeki senaryolar test kodu değildir ve çalışmış sayılmaz.
