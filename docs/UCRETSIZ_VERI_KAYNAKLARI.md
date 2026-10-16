# Anahtarsız veri kaynakları — 16 Ekim 2026

Bu değişiklik mevcut `data` aracını genişletir. Yeni ajan çatısı, model,
API hesabı, kart, abonelik veya ikinci görev kuyruğu kurmaz.

## Kullanılabilen yollar

| İhtiyaç | Mevcut araç | Sınır |
| --- | --- | --- |
| Kaynak seçenekleri | `data {"operation":"sources"}` | Yerel liste; canlı erişim kanıtı değildir. |
| Haber bağlantıları | `data {"operation":"news_search","query":"artificial intelligence","days":7,"domains":["tubitak.gov.tr","sanayi.gov.tr","edu.tr"],"limit":10}` | GDELT DOC; keşif sonucu, doğrulanmış haber değildir. |
| Yayıncının dizini | `data {"operation":"headlines","url":"https://tubitak.gov.tr/tr/haberler","query":"yapay zeka"}` | Gerçek HTML/RSS/Atom bağlantıları. |
| Döviz | `data {"operation":"exchange","base":"USD","quote":"TRY"}` | Frankfurter günlük kaynak kuru; anlık alış/satış değildir. |
| Finans ve mağaza | `finance_csv` / `store_csv` | İzinli CSV ve açık sütun eşleştirmesi; hesap/model çağrısı gerekmez. |
| Sosyal medya | `social` | Mevcut yetkili YouTube/Instagram hesabı gerekir; genel ücretsiz sosyal veri erişimi eklenmedi. |

GDELT İngilizceye çevrilmiş haber dizinini arar; konu metninde İngilizce
kullanmak daha uygundur. Sorgu düz metindir; kullanıcı operatörleri, URL veya
anahtar içeremez. Alan adı filtreleri ayrı `domains` listesinde verilir.
Gelen URL'ler ayrıca alan adı ve HTTPS denetiminden geçer. Arama sonucunun
`seen_at` değeri yayın tarihi sayılmaz; `published` alanı bilerek boş kalır.

## Haber teslim akışı

1. Kullanıcının istediği kurum kapsamını koruyarak `headlines` veya
   `news_search` ile gerçek bağlantı bul.
2. Her seçilen tekil sayfayı `research` ile oku; makaleye ait yayın tarihini
   ve gövde alıntılarını mevcut kurallarla doğrula.
3. Varsayılan son 7 gündür. Sonuç yoksa sınırlı kaynaklarda doğrulanmış
   haftalık gelişme bulunamadığını belirt; eski haberle doldurma. 30–90 günlük
   tarih aralığı yalnız açık kullanıcı isteğiyle kullanılabilir.
4. `writer` yalnız doğrulanmış haber adımlarına bağlı rapor oluşturur;
   `verify` gerçek dosyayı ve içerik kanıtını kontrol eder.

Planlayıcı erişilemezken mevcut dar yapay zekâ raporu kurtarması korunur.
Önceden denenmiş en fazla iki yayıncı dizini bağlantı vermiyorsa, yalnız
aynı alan adlarında tek GDELT araması denenir. Önceden izin verilen gün
aralığı kullanılır (varsayılan 7, açık istekle en fazla 90). Mevcut 10 kurtarma/24 tur/96 toplam adım
sınırları uygulanır. Kısmi rapor hedefi tamamlandı saymaz; hedef kimliği ve
eski dosyalar korunur. Gönderim/onay/iptal kapıları değişmez.

## Erişim ve maliyet

- GDELT: https://www.gdeltproject.org/ ve
  https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
  açık veri ve anahtarsız DOC JSON uç noktasını belgeler. Tüm kurumların
  indekslendiği, tüm haberlerin bulunduğu veya kesintisiz erişim garantisi yoktur.
- Frankfurter: https://frankfurter.dev/ ücretsiz, anahtarsız günlük kur
  servisini belgeler. Mevcut adaptör yeniden yazılmadı.
- GDELT istekleri süreç genelinde en az 5 saniye aralıklıdır. Erken çağrı
  bekletilmeden reddedilir; 429 sonrasında 60 saniye geri çekilir. Otomatik
  yeniden deneme, ücretli yedek veya abonelik yoktur. Bu süreç içi sınırlama
  başka bilgisayarları veya başka programları koordine etmez.
- RapidAPI / FreePublicAPIs kataloglarında görünmek bağlanmış veya ücretsiz
  olduğu anlamına gelmez. Rastgele katalog uç noktaları otomatik eklenmedi.

## Doğrulama sınırları

Geliştirme ağında Frankfurter USD/TRY JSON yanıtı verdi. GDELT ilk HTTP yoklamasında 429 döndürdü; sonraki yoklama gerçek haber
bağlantıları içeren JSON200 verdi. Jarvis'in doğrudan, IP doğrulayan okuyucusunda
bu ortamda DNS çözümlemesi başarısız oldu. HTTP yoklaması üretim okuyucusunun
veya Windows üzerinde baştan sona güncel rapor tesliminin doğrulanması değildir.
Ağ/model sınırları taklit edilerek gerçek görev kaydı ve rapor dosyasıyla
regresyonlar çalıştırılır; canlı kullanıcı anahtarı/model çağrısı yapılmaz.

Son kontrol: 1.309 Python testi başarılı (Windows DPAPI için 1 skip),
25 JavaScript grubu ve 6 smoke grubu başarılı. Son salt okunur kural
incelemesi geçti. İncelemede bulunan yalnız başlıkla haber hedefi tamamlama
açığı kapatıldı; verify bağımlılığına sarma ve eski tamamlanma kaydından
sürdürme regresyonları da geçti.

## Hamdi'nin en son yapacağı kontroller

Önce tek komut: `scripts\v2_kontrol.bat --public-data --skip-suite`.
Yeni seçenek yalnız açıkça verildiğinde canlı, anahtarsız web okuması yapar:
günlük kur, resmî alanlarda son 7 günlük haber araması, en fazla iki tekil
haberin yayın tarihi/alıntısı ve kısmi raporun gerçek dosya doğrulaması.
Model çağrısı veya hesap bağlantısı yoktur. Aktif hedef değiştirilmez.
GDELT zaman aşımı, boş sonuç veya doğrulanamayan haber durumunda TÜBİTAK ve
Boğaziçi'nin resmî dizinleri mevcut headlines okuyucusuyla birer kez denenir.
Her dizinden en fazla bir ilgili aday (toplam iki ek makale) doğrulanır.
TÜBİTAK'ın bilinen tekil haber şablonunda gövde dışında kardeş bloktaki
başlık ve gövde içindeki Türkçe tarih, eşleşen canonical ve tek haber koşuluyla
okunur. İlgili haber kartlarının tarihi makaleye taşınmaz. Yalnız son
7 günlük doğrulanmış adaylar kullanılır; otomatik genişleme yoktur. Eski
haberler haftalık rapora eklenmez. Dosya adı `haftalik-rapor.md` ile biter.
GDELT hatası pending kalabilirken yayıncıdan alınan gerçek rapor ayrıca passed
olabilir. Uygun tarihli makale yoksa rapor yine pending kalır; süre artırılarak
veya tarih koşulları gevşetilerek sahte başarı oluşturulmaz.
Sonuç mevcut `v2_kabul_sonucu.json` dosyasına kaydedilir. Erişilemeyen
servis veya doğrulanamayan haber `pending` kalır; sahte başarı yazılmaz.
Bu kontrol normal planlayıcı veya tüm kurumların araştırılması yerine geçmez.

1. Güncel sürümde “Anahtarsız veri kaynaklarını listele” isteğinde GDELT,
   Frankfurter ve yayıncı dizini seçeneklerinin görünmesini kontrol et.
2. “USD TRY günlük kurunu getir; veri tarihini ve kaynağını göster” de.
   Bunun banka alış/satış fiyatı olarak sunulmadığını kontrol et.
3. Mevcut Türkiye yapay zekâ hedefini **sürdür**. Yeni hedef oluşmamalı.
   GDELT çalışırsa bulunan tekil sayfaların tarih/bağlantıları raporda yer
   almalı. Çalışmazsa somut hata ve eksik kapsam görünmeli; sahte başarı olmamalı.
4. Teslim edilen Markdown dosyasını aç: yayın tarihleri tekil sayfalarla
   eşleşmeli, kategori/indeks tarihi haber tarihi yapılmamalı. Kısmi teslim
   varsa araştırmanın tamamlandığı söylenmemeli.
5. Hedefi tekrar sürdür: doğrulanmış kısmi rapor gereksiz yeniden
   oluşturulmamalı. Bu işlemlerde kart/anahtar/ücretli sağlayıcı istenmemeli.
