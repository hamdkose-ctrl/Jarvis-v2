# Ortak araç girdisi ve yürütme kaydı

13 Ekim 2026. Önceki görev kurtarma ve araç sonuç doğrulama paketinin üzerine uygulanır.

## Yapılanlar

Mevcut Python görev motoru kullanılıyor. Yeni framework, bulut çağrısı veya hesap bağlantısı eklenmedi.

| Araç | Girdi | Risk | Kesintiden sonra tekrar |
|---|---|---|---|
| research | url; isteğe bağlı question | Ağdan okuma | Kullanıcı devam komutuyla |
| writer | instruction; isteğe bağlı filename | Yerel rapor oluşturma | Kullanıcı devam komutuyla; yeni dosya oluşabilir |
| browser | url, instruction | Dış etki ihtimali | Belirsiz sonuçta otomatik tekrar yok |
| coder | request | Geliştirme çalışma alanı | Belirsiz sonuçta otomatik tekrar yok |
| verify | Boş girdi; önceki sonuçlar bağımlılık olarak | Yerel kanıt okuma | Kullanıcı devam komutuyla |

Planın sağladığı alanlar işe başlamadan kontrol edilir. Eksik zorunlu alanlar worker sınırında, ağ/model/dosya çağrısından önce reddedilir. Bu durumda bağımlı işler bloke olur; bağımsız işler ilerleyebilir. Bilinmeyen alanlar, yanlış türler, boş/aşırı uzun metin, geçersiz URL ve dosya adı reddedilir. Bağımlılıklar tekil ve önceki görev kimlikleri olmalıdır.

Her denemenin kullanıcı, görev, adım, yetenek, risk ve deneme numarası gerçek çalışma bağlamından türetilir. İlk kayıt aracı çağırmadan önce atomik olarak saklanır. Model bu kayıtla kullanıcıyı veya risk sınıfını değiştiremez.

Sonuç `verified`, `approval_required`, `blocked`, `unavailable`, `failed` veya `effect_unknown` olarak kaydedilir. `verified` önceki araç kanıt kontrollerinden geçmiş tamamlanmış yürütmedir; içerik doğruluğu garantisi değildir. İşlem aniden kesilirse ilk kayıt `pending` kalabilir; devam kararı mevcut görev durumuna ve worker türüne göre verilir.

Tarayıcı/kod hatasında dış etki bilinmiyorsa güvenli tarafta kalınır, otomatik tekrar yapılmaz. Risk etiketi izin vermez. Somut tarayıcı planı onayı, kullanıcı ayrımı, geliştirme kilidi ve gizlilik kontrolleri aynen geçerlidir. Yeni genel hesap yetkilendirme sistemi kurulmadı.

## Doğrulama

`test_task_tools`, bozuk girdinin gerçek workera ulaşmamasını, bozuk planla hiçbir iş başlamamasını, dış çağrıdan önce kayıt yazılmasını, sahte kullanıcı/risk alanlarının kullanılmamasını, belirsiz işlemin tekrarlanmamasını ve onayın korunmasını sınar. Görev, kurtarma, sonuç ve mevcut regresyon testleriyle birlikte çalıştırılır.

Canlı Windows/tarayıcı/model/hesap işlemleri bu yerel testlerin dışında kalır. Sonraki aşama servis yetenekleri ve hesap bağlantılarıdır; tüm sosyal servislerin hazır olduğu iddia edilmez.

Son çalıştırma: 58 odaklı test, 20 Node grubu ve 6 smoke kontrolü geçti. Genel 933 testte 8 Windows ayar penceresi başarısızlığı, 2 atlanan test var; bunlar önceki teslimdeki bilinen Linux/Windows sınırıdır. Canlı Windows doğrulaması bekliyor.
