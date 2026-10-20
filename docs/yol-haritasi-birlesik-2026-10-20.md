# Jarvis — Birleşik yol planı ve uçtan uca kabul

Güncelleme: 20 Ekim 2026 (Europe/Istanbul). Bu belge Hamdi'nin 14 alanlık hedefi, konuşmada açıklanan süreklilik ihtiyacı ve GitHub'dan doğrulanan durumla güncellenmiştir. Önceki raporun tarihsel metni Git geçmişindedir (#204–205); aşağıdaki sıra onun yerine geçer. Bu PR yalnız belgedir; burada tarif edilen yeni davranışlar uygulanmış sayılmaz.

## Sonraki durum — CI engeli

Bu plan #211 ile main'e girdi. #206/#208/#209/#210/#212 de squash birleşti (main 7563161). Bölüm 2'deki açık PR tablosu plan hazırlanırken alınmış tarihsel anlık görüntüdür. 62-B artık [#213](https://github.com/hamdkose-ctrl/Jarvis-v2/pull/213) taslağında hazır; yerel validation yeşil, GitHub ödeme/Actions harcama engeli yüzünden CI job başlamadı. Yeşil CI olmadan birleşmez.

Bu sırada [merkezi ayrım tasarımı](MERKEZI_AYRIM_TASARIMI.md) ve [ses/yazı PC kabul matrisi](PC_TABAN_KABUL_20261020.md) üzerinde ilerlenir. Gerçek PC denemeleri Denenmedi; M1 ve sonraki kod kartları uygulanmadı. Eski “62-B bağımlılık bekliyor” satırları bu güncelleme ile aşılmıştır; yeni engel CI'dır.

## 1. Hedef ve tamamlanma ölçüsü

Jarvis sesli ve yazılı verilen işi anlayan, bağlamını koruyan, gerektiğinde araştıran, araçları birlikte kullanan, hatadan toparlanan ve sonucu kanıtla teslim eden kişisel dijital çalışan olarak geliştirilir.

**Her alan geniş kullanım senaryolarıyla tasarlanır, küçük parçalarla geliştirilir ve uçtan uca görevlerle kabul edilir. Tek başarılı gösterim alanın tamamlandığı anlamına gelmez.** Hesap Makinesi açmak tam PC kontrolü, video açmak tam web kontrolü, dosya listelemek son üretilen dosyayı bulmak değildir.

Hedef geniştir; desteklenen uygulama, hesap, platform ve işlem sınırları açık tutulur. Para, dış gönderim, yayın, yıkıcı ve fiziksel işlemlerde kullanıcı kontrolü korunur. Bu plan mevcut izinleri genişletmez.

## 2. Doğrulanmış geliştirme durumu

GitHub anlık kontrolü: 20 Ekim 2026. Taban main: `3558352c2734bf0b8b5a74dba9f927f0f9e692ea`. PR durumları zamanla değişir; yeni işe başlamadan tekrar okunur.

| İş | Depo kanıtı / durum | Sınır ve sonraki iş |
|---|---|---|
| 45a–47: politika, Harita arka ucu, kaynak belirteçleri, dosya/sistem kapısı | main geçmişinde #188, #190, #192, #193 birleşmiş | Yeniden yazılmaz; gerçek hesap/cihaz kabulü ayrı |
| 48–50: mail/takvim, haber/finans, dosya/Hoca sözleşmeleri | #194–196 birleşmiş | Sözleşmenin bulunması tüm doğal dil yollarının aynı yürütücüye bağlandığını kanıtlamaz |
| 51–53: physical, yazıcı, slicer/CAD | #197–199 birleşmiş | Gerçek cihaz kabulü Denenmedi; physical her seferinde onaylı |
| 54–57: API/yerel program/HTTP cihaz sihirbazı ve Harita | #200–203 birleşmiş | İki gerçek entegrasyonun uçtan uca kabulü bekliyor |
| 59: okunur dosya listesi | [#206](https://github.com/hamdkose-ctrl/Jarvis-v2/pull/206) açık taslak, testler SUCCESS | Son yazılan dosyayı takip etme kapsamda yok; LLM yönlendirmesi ve PC kabulü Denenmedi |
| 60: kısa hedef durumu | [#207](https://github.com/hamdkose-ctrl/Jarvis-v2/pull/207) birleşmiş | Gerçek eski PC kayıtlarıyla kabul Denenmedi |
| 62-A: çıplak tutar finans ayrıştırması | [#208](https://github.com/hamdkose-ctrl/Jarvis-v2/pull/208) açık taslak, testler SUCCESS | Açık hedef sorusu tarafından yutulma ayrı 62-B |
| 58: çıplak iptal / bekleyen fotoğraf bağlamı | [#209](https://github.com/hamdkose-ctrl/Jarvis-v2/pull/209) açık taslak, testler SUCCESS | engine_commands.py sahibi; merkezi yönlendirmeyle aynı anda değiştirilmez |
| 61: hata tekrarını kaldırma / Ollama bağlantı reddi mesajı | [#210](https://github.com/hamdkose-ctrl/Jarvis-v2/pull/210) açık taslak, testler SUCCESS | goal_executor.py sahibi; haber kaynak/konu hatasını kapatmaz |

#206/#208/#209/#210 için önceki çalışma kayıtlarında tam modules.validation ve fiziksel satır mutasyon kontrolleri vardır. Bu belge çalışması o eski testleri yeniden çalıştırılmış gibi sunmaz. Yeni PR'ın kendi doğrulaması kendi PR gövdesine yazılır. Yeşil CI gerçek PC kabulü değildir. 58–62 kartlarının kuralı gereği taslaklar otomatik birleştirilmez.

### Açık sorunlar ve bağımlılıklar

- **62-B:** 60 ve 61 birleşmeden başlamaz. #207 birleşmiş, #210 açık olduğu için şu an bekler. #208 de test dosyasını değiştirir; aynı dosyada iki iş açılmaz. Önce açık hedef sorusu + “6 dolar” testiyle tekrar üret; yalnız hata varsa sınırlı düzeltme. Gerçek beklenen cevap hâlâ soruya cevap olarak işlenmeli.
- **Haber konusu/kaynak:** 61 sırasında sahte kaynakla `model_free_news.terms('son dakika haberleri')` → `['dakika', 'haberleri']` ve ilgisiz konu reddi üretildi. Ayrı dar kart: modules/model_free_news.py ve ilgili testler; daha geniş kaynak seçimi değişikliği ayrı kanıt ister. Gerçek PC'de DPÜ'nün neden seçildiği kesinleşmedi.
- **“Hangi dosya yazıldı?”:** #206 yalnız liste sunumunu düzeltir. Son göreve ait üretilen dosyanın kimliği/yolu ve kanıtı için ayrı gereksinim/test gerekir; mevcut tüm dosya listesi bu sorunun tam cevabı sayılmaz.
- **PR incelemesi:** #206/#208 alan içi değişiklik; #209/#210 çekirdekle temas eder. İnceleme ve açık onaydan sonra birleşme sırası belirlenir. Gelecekte taşınacak olması küçük düzeltmeyi tek başına geçersiz kılmaz; çakışma ve regresyon kanıtı değerlendirilir.

## 3. Başlangıçta sabitlenecek mimari sözleşme

Mevcut motor içinde tek giriş geliştirilir; sıfırdan motor veya ikinci Manifest/Registry yapılmaz. Kavramsal akış:

`Kullanıcı + giriş kaynağı + geçerli oturum bağlamı → INTENT / DOMAIN / EFFECT → ROUTE → plan → her adımda izin → execute → verify → evidence → devam/teslim`

- INTENT: oturum kontrolü, soru/sohbet, görev, uzun araştırma. DOMAIN: mail, finans, dosya, PC, web vb. EFFECT bağımsızdır; dış gönderim ayrı intent değildir.
- Örnek: “6 dolar kaç TL?” soru / finans / read; “Ahmet'e 6 dolar ödediğimi mail at” görev / mail / message_out. Konu adı risk sınıfı değildir.
- Yeni EFFECT alanı mevcut permission_classify/permission_gate sınıflarına bağlanır: read, local_reversible, local_destructive, message_out, publish, money_credential, system_config, physical. Eşleme eylem ve parametreleri dikkate alır; belirsiz durum sessizce yetki kazanmaz. İkinci izin otoritesi kurulmaz.
- Giriş etiketi tahmindir; her gerçek araç çağrısı yürütme anında yeniden sınıflandırılır ve kapıdan geçer. Planın sonradan eklediği gönderim, ilk isteğin read etiketiyle çalışamaz. Kapı hatası kapalı kalır; Engelle'yi onay/grant aşamaz.
- Ses ve yazı aynı karar/yürütme sözleşmesine bağlanır. Mikrofon kapalı, tanıma belirsiz veya kullanıcı sahipliği doğrulanmamışsa dış işlem başlamaz. Gerçek ses tanıma kabulü ayrı ölçülür.
- Bekleyen soru: kullanıcı, görev/işlem kimliği, beklenen cevap türü, oluşturulma/geçerlilik bilgisi ve iptal durumu taşır. Eski görev her yeni cümleyi yutamaz. Birden fazla uygun bekleyen işlem varsa belirsizlik sorulur.
- “İptal/devam/onayla” bağlamlıdır. Bağlam yoksa yeni görev üretmez. Onay yalnız ilgili hedef/içerik/işlem ve geçerli süre için işler; başka onaya taşınmaz.
- CLASSIFY sırasında işlem yapılmaz. Karar kaydında seçilen yol ve kısa gerekçe bulunur; gizli içerik kayda kopyalanmaz. LLM sınıflandırması varsa da güvenlik yetkisi vermez.

Merkezi ayrım ayrı mimari karttır; 58–62'nin dosya sınırlarına sonradan sıkıştırılmaz. Önce mevcut kararlar için regresyon/karakterizasyon, sonra yan etkisiz karar kaydı, sonra alan alan geçiş yapılır. İki yürütücü aynı isteği çalıştırmaz. task_agents işçi olarak kalabilir; görev yaşam döngüsü seçenek A doğrultusunda tek sahipte toplanır. Eski kayıt uyumu ve geri dönüş yolu korunur.

## 4. Alan kapsamları ve kabul örnekleri

Aşağıdakiler hedef kapsamıdır, bugün destekleniyor iddiası değildir. Her alan için desteklenen işlemler, eksikler ve gerçek kabul kanıtı ayrı tutulur.

| Alan | Tasarımda kapsanacak dallar | Örnek uçtan uca kabul |
|---|---|---|
| 1. PC kontrolü | Uygulama/pencere seçimi, kontroller, diyaloglar, dosya aç/kaydet, çok uygulamalı işler, değişen ekran, izin/iptal/toparlanma | İzinli uygulamada belgeyi aç, düzenle, yeni adla kaydet, dosyayı yeniden okuyarak doğrula; yanlış pencereye işlem yok |
| 2. Jarvis kontrolü | Ses/yazı eşliği, başlat/durdur/devam/değiştir, hesap/ayar/izin/araç yönetimi | Aynı işi iki girişle ayrı dene; durum ve izin kararı eşdeğer, durdurma gerçek yürütmeyi kesiyor |
| 3. Analiz ve çözüm | Bilinen/bilinmeyen, varsayım, kanıt, karşılaştırma, hesap, alternatif, belirsizlik, sonuç ölçümü | Kaynaklı veriden iki çözümü ölçütlerle karşılaştır; hesap tekrar üretilebilir; bilinmeyeni belirt |
| 4. Tek dosya | PDF/DOCX/XLSX/CSV, çeviri, konu arama, tablo, kaynak yeri, biçim koruma | Konuyu sayfa/sayfa adı/hücre ile bul, çevir, çıktıyı yeniden aç; bulunmayanı uydurma |
| 5. Çok dosya/klasör | 5–10 ve daha fazla dosyada envanter, indeks, konu ilişkisi, çelişki, sürüm/tekrar, araştırma ve anlatım | Verilen klasörde konuya ilişkin kaynakları birleştir; okunamayanları ve bakılan dosyaları say; kaynakları göster |
| 6. Hoca/çalışma | Oturum konusu, seviye, kaldığı yer, farklı anlatım, alıştırma, geri bildirim, web/video kaynakları | Soruyla ara ver, ilgili video incele, aynı derse dön; konu ve öğrenme ilerlemesi korunur |
| 7. Öğrenme/kişiye uyum | Kullanıcı tercihleri, eleştiri/öneri, geri bildirim, düzeltme/unutma, kapsamlı hafıza | Kullanıcı tercihi sonraki ilgili işte uygulanır; başka kullanıcıya geçmez; yanlış bilgi düzeltilebilir |
| 8. Web/YouTube | Sayfa/sekme gezinme, arama/form, oynat/duraklat/ileri, kullanılabilir reklam atlama, devamlı görev | İlgili videoyu bul, oynatmayı yönet, sonraki kaynağa geç; platform sınırı varsa açık bildir |
| 9. Haber/araştırma | Konu/tarih, tekil sayfa, çok yayıncı, güncellik, çelişki, kaynak güveni, takip | Son 7 günden en az iki yayıncı; tarihler ve URL'ler doğrulanmış; eksik kapsam açık |
| 10. Mail/takvim/not/plan | Gmail/iş maili, ekler, taslak, izinli gönderim, randevu/çakışma, hatırlatma ve takip | Mail ekini incele, sonuç taslağı ve kullanıcı onaylı takvim kaydı oluştur; doğru hesap ve alıcı |
| 11. Sosyal medya | İçerik planı, video düzenleme/altyazı, önizleme, yükleme/yayın, metrik analizi | Videoyu hazırla, çıktıyı doğrula, kesin hesap/içerik onayıyla yayınla; teslim/yayın ayrı ölçülür |
| 12. Finans | Kur/piyasa/dünya gündemi, alarm, portföy, analiz; ileride ayrıca yetkili işlem yolu | Tarihli verilerle kaynaklı analiz; işlem desteği ayrı tasarım, hesap ve açık onay ister; mevcut salt okuma otomatik genişlemez |
| 13. WhatsApp/Telegram | Hesap, kişi/grup seçimi, okuma, taslak/gönderim, ek, teslim ve takip | Kesin hedef ve içerikle bir kez gönder; dış içerik alıcı değiştiremez; servis/API sınırı açık |
| 14. Program üretme/kendini geliştirme | Gereksinim, tasarım, kod/test, izole deneme, taslak PR, sürümleme, geri alma, ölçüm | Önce hatalı senaryo/test, sonra aday çözüm; insan incelemesi; kendi kendine merge/deploy/izin genişletme yok |

Ortak görev döngüsü: isteği anla → durumu gözle → planla → uygula → sonucu doğrula → devam et; sorun varsa sınırlı toparlan veya eksik bilgiyi sor. Yanıt kaybında replay-safe olmayan işlem kör tekrarlanmaz; reconcile gerekir. İş kimliği, kullanıcı, açık belgeler/bağlantılar, tamamlanan adımlar ve çıktı kanıtı korunur.

## 5. Uygulama sırası ve geçiş koşulları

1. **Mevcut düzeltme taslaklarını incele:** izinli diff, önce düşen test, fiziksel mutasyon, tam validation, head'e ait CI ve Denenmedi kanıtı. Birleştirme ayrı açık onaya tabidir. Çekirdek dosyada aynı anda tek görev.
2. **Taban açıklarını kapat:** bağımlılıklar sonrası 62-B; haber konu/kaynak kartı; son üretilen dosya semantiği ayrı kart. Beş PC cümlesinin hepsi tek kök neden sayılmaz.
3. **Küçük gerçek PC taban kabulü:** aşağıdaki bağlam matrisiyle ses/yazı denemeleri. Başarısız alan için yeni özellik açılmaz; düzeltme/teşhis sürer. Sağlayıcı arızası kabulü engelliyorsa ilgili kota düzeltmesi bu aşamada yapılır.
4. **Kota/sağlayıcı sertleştirmesi:** kullanıcıya özel bütçe, anlaşılır 429 ayrımı, sınırlı retry, yedek bulunmaması, çevrimdışı durum. Ollama isteğe bağlı; yeni bağımlılık yapılmaz. Ücretli sağlayıcı/maliyet değişikliği otomatik değildir. #210 yalnız mesaj alt kümesini karşılar.
5. **Merkezi ayrım ve tek yaşam döngüsü:** bölüm 3'teki kademeli geçiş; ses/yazı, eski kayıt, pending sorular ve dış etkiler için regresyon. Açık #209/#210 sonuçlanmadan aynı çekirdek dosyalarda yeni iş başlamaz.
6. **Mevcut sözleşmeleri ortak yürütmeyle bütünleştir:** CONTRACT/load_all/Harita korunur; sürüm, bağımlılık, platform, doğrulama, replay/reconcile ve devre dışı bırakma standartlaştırılır. 45–57 tekrar yapılmaz; eksik bağlantılar kanıtla çıkarılır.
7. **Küçük Self Model + sağlık + kimlik:** tanımlı / bağlı / gerçek ortamda doğrulanmış ayrımı, auth_expired/offline/degraded/missing_dependency, açık görevler ve kota bilgisi. Durumun kaynağı ve kontrol zamanı görünür; bilinmeyen bilinmeyen kalır. Kimlik kısa, isim değiştirilebilir, sahip kullanıcı profilinden gelir; Hamdi uygulama geneline sabitlenmez. Sırlar modele/kayıtlara dökülmez.
8. **İki gerçek entegrasyon:** mevcut sihirbazla bir düşük riskli araç ve farklı türde ikinci araç; bağlantı, izin, yürütme, doğrulama, iptal/hata/toparlanma ölçülür. Yazıcı seçilirse gerçek cihaz, her işlemde physical onayı ve reconcile gerekir.
9. **Self-Improvement:** gözlem → zayıflık → kök neden hipotezi → tekrar üretme testi → iyileştirme → taslak PR → inceleme → insan onayı → aynı senaryoyu yeniden ölçme. İlk sürüm öneri ve kanıt paketi olabilir; otomatik kaynak değişikliği gerekmez. Kişisel veri temizlenir, ölçülemeyen “öğrendim” iddiası yapılmaz.
10. **Builder:** iki entegrasyon ve qualification kanıtı sonrası; ilk kapsam read/local_reversible. İzole kod/test/doküman üretimi ve insan incelemeli taslak PR. Kendi çıktısı güvenlik otoritesi olamaz; kendi kendine merge/deploy/etkinleştirme yok.
11. **Alanları derinleştir:** dosya/klasör, Hoca, araştırma, analitik araçlar, günlük işler, sosyal medya/iletişim ve finans; bölüm 4'teki kapsam kartlara bölünür. Sayısal hesap kodla, yorum modelle; varsayım ve kanıt ayrılır. Her alan artımından sonra gerçek kabul.
12. **Görsel teslimat ve deneyim:** doğrulanmış yapısal veriden karşılaştırma/timeline/rapor; okunabilirlik ve sayı doğrulaması. Varlık merkezli büyük UI en son, düşük donanım ölçümüyle. Durdur/onay/hata görünürlüğü bugünden korunur; çalışma yüzeyi kapansa da sonuç ve kanıt erişilebilir kalır.

## 6. Kabul ve kanıt standardı

Beş taban cümlesi: “hangi dosya yazıldı”, “hedef durumu”, “iptal”, “hedef son dakika haberleri”, “6 dolar”. Her biri bağlam yokken, aktif işte, soru/onay beklerken ve iptal edilmiş/eski kayıt varken uygun örneklerle sınanır. Aynı kullanıcıda bekleyen fotoğraf/uygulama seçimi ve başka kullanıcı izolasyonu da kapsanır. Özellikle “6 dolar” bağımsız kur sorusu ve gerçek tutar cevabı olarak ayrı denenir. Mail/mesaj kelimesi geçen salt sorular dış gönderim başlatmamalı.

Her kayıt: sürüm/commit, kullanıcı yerine anonim kimlik, ses/yazı girişi, başlangıç bağlamı, beklenen davranış, gözlenen sonuç, çıktı/kanıt ve Denenmedi. Ses kabulünde gerçek mikrofon, yankı/TV, tanıma belirsizliği ve durdurma ayrıca ölçülür; metin testleri bunların yerine geçmez. Anahtar/özel mail/içerik depoya girmez.

Durumlar ayrı tutulur: planlandı → kod/test kanıtı → CI kanıtı → gerçek ortam kabulü. Tanımlı veya bağlı araç, gerçek kabulü yokken “tam çalışıyor” diye sunulmaz. İlk beş cümlenin geçmesi 14 alanın tamamlandığı anlamına gelmez.

**V2 çıkışı için 10/10 gerçek senaryo şartı korunur:** uzun görev+kesinti/devam; dosya uçtan uca; güncel çok kaynaklı haber; Gmail+ek+çıktı; güvenli tek gönderim; gerçek PC görevi; üçüncü taraf uygulaması; kuyruk+restart; sağlayıcı arızası; karma araştırma/rapor/görsel/taslak görevi. Kabul küçük gruplar halinde geliştirme boyunca yapılır; sonunda aynı sürümde toplu doğrulanır. Kota/cihaz yokluğu geçer sayılmaz, Denenmedi kalır. Bu V2 tabanı, bütün uzun vadeli alanların tamamlandığı anlamına gelmez.

## 7. Çalışma disiplini ve hemen sonraki iş

Her kod kartı: güncel main'den ayrı dal → önce düşen test → dar satır yaması → ilgili negatif kontroller ve fiziksel satır mutasyonu → tam `python -X utf8 -m modules.validation` (“Tüm test grupları başarılı.”) → taslak PR → head'e ait yeşil testler CI → izinli diff ve kontrol listesi. main'e doğrudan push, force, test silme/zayıflatma yok; gerekirse main dala merge edilir. Yeni Node testi JS_GROUPS'a eklenir; CRLF korunur; yeni except Exception bloğunun ilk satırı diagnostics kaydıdır.

PR gövdesi: Before / After / How, Kontrol listesi, Denenmedi. Belge değişikliğinde önce düşen davranış testi ve kaynak mutasyonu uygulanamaz; bu açıkça yazılır, sahte test üretilmez. Gerçek PC, canlı hesap ve gerçek cihaz her PR'da kanıt yoksa Denenmedi olarak kalır.

### Sonraki dar düzeltme kartı: haber konu terimleri

Dal: `gpt/haber-genel-konu-terimleri`. İzinli kaynak: modules/model_free_news.py; test: tests/test_model_free_news_fallback.py; AGENTS.md'ye yalnız madde ve docs/agents/haber.md alan notu. Seçenekler: (A) mevcut saf terms işlevinde genel haber ifadelerini sınırlı normalize etmek; (B) yeni model/sınıflandırıcı eklemek. A tercih edilir: doğrulanmış hata için küçük ve modelsiz değişiklik; konu eşleştirme veya tarih/kanıt kapısı gevşetilmez.

Önce düşen test: genel “son dakika haberleri” gerçek konu sözcüğü üretmemeli; tam cümle alıntısı değişmeden dönmeli. Negatif: “son dakika yapay zeka haberleri” yapay/zeka konusunu korumalı ve ilgisiz makaleyi reddetmeli. “dakika” gerçek içerik bağlamında otomatik silinmemeli. Ağ/model kullanılmaz. Fiziksel mutasyon, ilgili haber regresyonları, tam validation ve CI şarttır. DPÜ gerçek kaynak seçimi bu kartın dışında kalır.

**Şu an devam:** açık PR incelemeleri ve bu plan taslağı. 62-B #210 nedeniyle bekler; merkezi çekirdek işi #209/#210 ile çakışır. Haber konu terimleri için ayrı dar kartın tekrar üretme testi hazırlanabilir; kaynak seçiminin gerçek PC kök nedeni bu kart kapanınca otomatik çözülmüş sayılmaz. Yeni büyük özellik açılmaz.
