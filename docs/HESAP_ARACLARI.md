# Hesap araçları: ilk çalışan uyarlayıcı

13 Ekim 2026. Jarvis'in mevcut Python motoru korunur. `account_tools` ortak hesap sınırı, `account` ise mevcut görev grafiğindeki worker'dır.

## Kullanım

- `hesap bağlantıları` veya `hesap yetenekleri`: destek listesini gösterir. Canlı bağlantı testi değildir.
- `görev mail oku`: en çok 5 okunmamış gelen kutusu mailinin gönderen ve konusunu görev kaydına alır; model çağrısı yapmaz.
- `görev: okunmamış mail başlıklarını listele ve Markdown raporu hazırla`: mevcut planlayıcı `account → writer → verify` zincirini kurabilir. Model ürettiği planı doğrulama ve mevcut görev sınırları içinde yürütür.
- `görev durumu`, `görev geçmişi`, `görev devam <kimlik>` önceki görev komutlarıdır.

Gmail hesabını mevcut Gmail/Takvim bağlantısından bağlamak gerekir. Bu güncelleme hesabı sizin yerinize bağlamaz. İzin yoksa yeni giriş penceresi açılmaz; mevcut bağlantıdan izin yenileme gerektiği bildirilir. İzin veya Google paketleri eksikse sonuç başarılı sayılmaz. Diğer API hataları adımı başarısız bırakır.

## Gerçek kapsam

| Servis | Ortak görev katmanındaki durum |
|---|---|
| Gmail | `list_unread`: başlıklar; `read_message`: seçilen mailin metin gövdesi; salt okuma |
| Telegram | Henüz uyarlayıcı yok |
| WhatsApp | Mevcut Windows otomasyonu ayrı kalır; ortak araç bu yola otomatik düşmez |
| YouTube | Henüz ortak yayın/hesap uyarlayıcısı yok |
| Instagram | Henüz uyarlayıcı yok |

Güncel ek aşama: `read_message` seçilen mailin metin gövdesini okur ve mevcut writer yerel cevap dosyası hazırlayabilir; ayrıntı GMAIL_OKUMA_TASLAK.md içindedir. Ek indirme, gönderim, Gmail hesabında taslak oluşturma, silme ve okunmuş işaretleme yapılmaz. Liste ilk sayfadır; daha fazla sonuç varsa açıkça belirtilir. Yetenek kaydı bağlantı veya kullanıcı izni değildir.

## Kanıt ve kullanıcı ayrımı

Mesaj kimlikleri, From/Subject başlıkları, sorgu, liste sınırı, okuma zamanı, kullanıcı ve ilk sayfa bilgisi görev JSON'una kaydedilir. SHA-256 bu anlık görüntünün tutarlılığını kontrol eder; sonuç metni de bu kayıttan türetilir. Devam ederken kayıt değişmişse iş durur. Kontrol Gmail'e yeniden bağlanmaz; sonradan gelen/silinen maili tespit eden sürekli takip değildir.

Başlıklar kullanıcıya özel yerel görev klasöründe saklanır. OAuth token/anahtarları çıktıya veya teslim paketine girmez. Görev kullanıcısı açık çalışma bağlamıyla eşleşmelidir; UI'daki genel aktif kullanıcıya düşülmez. Kullanıcıya ayrı mevcut Google token yolu korunur. Gizlilik modu web erişimini kapatmışsa bu okuma da kapalıdır.

Mail başlıkları ve diğer dış içerik sonraki model adımlarında veri sayılır; talimat olarak izlenmemesi mevcut writer sistem yönergesindedir. Kayıt özeti içerik doğruluğu veya kötü niyetli metne karşı tam koruma garantisi değildir.

## Resmi API dayanağı

- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get
- https://developers.google.com/workspace/gmail/api/auth/scopes

Mevcut `gmail.readonly` bağlantısı kullanılır. Yeni OAuth kapsamı eklenmedi.

## Açık işler

Gmail gövde okuma ve yerel cevap dosyası son aşamada eklendi (GMAIL_OKUMA_TASLAK.md). Ek okuma, açık yetkili gönderim, servis başına izin kaydı, Telegram/resmi WhatsApp ve sosyal yayın uyarlayıcıları, zamanlanmış takip ve gerçek hesap/Windows kabul testleri bekliyor. Bu paket bütün hesapların bağlandığını iddia etmez.

## Son doğrulama

69 odaklı test geçti. Son sonuç doğrulama değişikliğinden sonra 22 hesap/sonuç testi ayrıca geçti. Router/ajan smoke geçti (OS/model taklitleri). Genel 944 testte önceki 8 Windows ayar penceresi başarısızlığı ve 2 atlanan test var. Canlı Gmail/OAuth/Windows denemesi yapılmadı. Arayüz dosyası değişmedi.
