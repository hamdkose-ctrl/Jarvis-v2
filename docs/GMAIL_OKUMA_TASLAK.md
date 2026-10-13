# Gmail gövde okuma ve yerel cevap taslağı

13 Ekim 2026. Mevcut Jarvis görev motoru ve Gmail salt-okuma OAuth bağlantısı kullanılır. Yeni framework, bağımlılık veya OAuth kapsamı eklenmedi.

## Komutlar

| Komut | Sonuç |
|---|---|
| `görev mail oku` | Okunmamış gelen kutusu başlıkları ve mesaj kimlikleri |
| `görev mail oku <kimlik>` | Seçilen mailin metin gövdesi |
| `görev mail taslak <kimlik>` | Maili okur, yerel cevap taslağı yazar ve kayıt/dosyayı doğrular |
| `görev ilk mail oku` | Okunmamış listedeki ilk maili okur |
| `görev ilk mail taslak` | Liste → ilk mail → cevap dosyası → doğrulama |

İlk mail API'nin ilk döndürdüğü okunmamış gelen kutusu sonucudur. Liste boşsa taslak hazırlanmaz. Mevcut Gmail bağlantısı kurulu olmalıdır; bu paket hesabı bağlamaz ve otomatik giriş penceresi açmaz.

Doğrudan komutlarda görev planı için model çağrısı yoktur; cevap yazma için mevcut seçili model kullanılır. Yerel taslak, dosyanın PC'ye kaydedilmesi anlamındadır; Gemini/Groq seçiliyse üretim mevcut model/gizlilik yolunu kullanır. Gizli/yerel modda web engeli Gmail okumasını da durdurur.

## Okuma sınırları

Düz metin tercih edilir. Yalnız HTML varsa etiketler metne çevrilir; script/style/head metni alınmaz. HTML tarayıcıda açılmaz, bağlantı ve izleme görselleri yüklenmez. .txt/.html ekleri gövde yerine okunmaz; diğer ekler de indirilmez. Snippet tam gövde kanıtı değildir. Okunabilir gövde yoksa adım başarısız kalır.

MIME sınırları: en fazla 256 parça, 16 iç içe seviye ve toplam 2.000.000 kodlanmış karakter. Çıktı gövdesi 20.000 karakterle sınırlıdır; daha uzunsa kayıtta ve görünen metinde kesildiği belirtilir. HTML'den çıkarılan metin görsel düzeni tam korumaz. Bozuk kodlama/MIME veya yanlış mesaj kimliği başarı sayılmaz.

## Taslak ve kayıt

Akış `account → writer → verify` şeklindedir; ilk mail komutunda öncesine `list_unread` eklenir. Writer kullanıcıya özel `Jarvis Görevler` klasörüne benzersiz isimli Markdown dosyası yazar. Taslak yönergesi eksik bilgiyi işaretlemesini, taahhüt uydurmamasını ve gönderilmediğini belirtmesini ister. İçerik kalite kontrolü kullanıcı incelemesi gerektirir; dosya doğrulaması cevabın doğru olduğunu garanti etmez.

Bu aşamada mail gönderilmez, Gmail hesabında taslak açılmaz, okunmuş işaretlenmez ve mail silinmez. Hiçbir `send`, `modify`, `drafts.create` veya `attachments.get` çağrısı yoktur.

Gövde ve başlıklar kullanıcıya özel görev JSON'unda saklanır. Kayıt özeti ve görüntülenen metin yeniden doğrulanır; başka kullanıcıya ait listeyle mail seçilemez. Devam komutu tamamlanmış okuma adımını tekrar yürütmez. Bu kanıt kayıtlı anlık görüntüyü doğrular; Gmail'deki son durumu veya yeni mailleri izlemez.

Yeni listelerde kimlik gösterilir. Önceki listelerin gösterim biçimi korunarak eski tamamlanmış görevler aynı kanıtla kontrol edilebilir.

## Doğrulama ve açık işler

Testler plain/HTML/charset, eklerin atlanması, uzun/bozuk/derin MIME, kimlik ve liste seçimi, boş liste, değişmiş gövde, dosya üretimi ve gönderim çağrısı yapılmamasını sınar. API/model/OS taklitleri kullanılır. Canlı Gmail/OAuth, gerçek model cevap kalitesi ve Windows PC doğrulaması ayrıca gerekir.

Açık: ekleri kullanıcı seçimiyle okuma, açık yetkili gönderim, servis izin kayıtları, diğer hesaplar ve sürekli takip.

Resmi API dayanağı: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages ve https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get .

Son kod doğrulaması: 80 odaklı test geçti. Genel 955 testte önceki 8 Windows ayar penceresi başarısızlığı, 2 atlanan test var. Router/ajan smoke geçti (model/OS taklitleri). Gerçek Gmail/OAuth/model/Windows kontrolü bekliyor.
