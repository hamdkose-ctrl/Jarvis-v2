# Jarvis birleşik görev, üretim ve servis katmanı

Bu paket önceki görev kurtarma, araç kanıtları, araç sözleşmesi ve Gmail okuma/taslak değişikliklerini toplar. Jarvis'in mevcut Python motoru kullanılır; LangGraph, Hindsight, CrewAI veya Paperclip kurulmadı. Son kabul edilen arayüz değişmez.

## Ne hazır?

| İş | Uygulanan yol | Gerçek kapsam |
|---|---|---|
| Araştırma/rapor/kod/tarayıcı | Önceki çalışan worker'lar | Mevcut model ve güvenlik yolları korunur |
| Gmail | Liste/gövde/yerel cevap, yetkili send | Gönderim ayrı OAuth kapsamı ister; ek okuma yok |
| Telegram | Bot getUpdates ve sendMessage | Bot ve tek yapılandırılmış sohbet; kişisel hesap geçmişi değil |
| WhatsApp | Resmi Business Cloud text send | Business kurulumu gerekir; ücret yetkisi kapalıdır, geçmiş/webhook yok |
| YouTube | Kanal istatistiği ve video yükleme | OAuth, doğru kanal ve gerçek yerel dosya gerekir |
| Instagram | Profil istatistiği ve tek görsel yayınlama | Profesyonel hesap/Facebook Login Graph bağlantısı ve erişilebilir HTTPS görsel gerekir; Reels yok |
| Video | Görsel + isteğe bağlı ses → MP4 | Yerel FFmpeg; senaryo/görsel/video üreten genel bir bulut stüdyosu değildir |
| Takip/zamanlama | Kalıcı tek sefer/tekrar kuyruğu | Okuma/rapor/medya; Jarvis ve PC açıkken çalışır |

Yazma uyarlayıcılarının API çağrı/yanıt yolları taklitlerle sınandı. Bu, gerçek hesapların bağlandığı veya canlı yayın denemesinin geçtiği anlamına gelmez. Şifre/anahtar sohbetten istenmez.

## Komutlar

- `görev yetenekleri`, `hesap bağlantıları`, `görev geçmişi`, `görev durumu`, `görev devam <kimlik>`.
- `görev mail oku`, `görev ilk mail taslak`; diğer Gmail komutları GMAIL_OKUMA_TASLAK.md içindedir.
- `hesap bağla gmail gönderim`: salt-okuma tokenından ayrı gönderim OAuth izni alır.
- `hesap bağla youtube okuma` / `hesap bağla youtube yükleme`: ayrı YouTube OAuth yolları.
- `hesap izin ver gmail kisi@example.com`: bu kesin hedefe 24 saat işlem yetkisi. `hesap izin kaldır gmail kisi@example.com` iptal eder. Servis/hedef değişince izin taşınmaz. Aynı komut telegram/whatsapp/youtube/instagram için kesin kimlikle kullanılır. Bu izin servise giriş sağlamaz.
- `işlem onayla <kimlik>`: görevde görünen değişmez içerik ve hedefi bir kez uygular. `işlem iptal <kimlik>`, `gönderim geçmişi`.
- `görev zamanla 60: okunmamış mail başlıklarından rapor hazırla`: 60 saniye sonra.
- `görev tekrarla 3600: YouTube kanal istatistiklerimden rapor hazırla`: saatlik. Tekrar aralığı en az 300 saniyedir.
- `görev kuyruğu`, `kuyruk iptal <kimlik>`. Sonuç görev kimliğiyle geçmişten okunur; kuyruğun bildirimi ilgili kullanıcıya gider.

Zamanlanan plan mevcut modelle bir kez hazırlanır, sonra sabit plan çalışır. Üretim adımları her tekrar mevcut seçili modeli kullanabilir; kota/ücret koşulları o modelindir. Dış yayın/gönderim, tarayıcı ve kod işleri arka plan kuyruğuna alınmaz. Kaçırılan tekrarlar birikmiş yayın gibi peş peşe çalıştırılmaz.

## Yerel bağlantı dosyaları

Veri klasöründe `connector_users/<kullanıcı-kimliği>/<servis>.json` kullanılır. Mevcut Veri klasörü menüsü konumu açar. Aşağıdaki örnekler gerçek anahtar içermez. Dosyaları PC'de doldur; anahtarları sohbetten gönderme. Tokenlar görev/çıktı kayıtlarına eklenmez.

Telegram (`telegram.json`):
```json
{"bot_token":"BOTFATHER_TOKEN_BURAYA","read_chat_id":"KESIN_SOHBET_KIMLIGI"}
```

Telegram okuma, botun bekleyen ilk sınırlı güncellemelerini alır; yapılandırılmamış sohbet metni atılır. Offset/ack veya webhook ayarı değiştirilmez. İlk sayfa ve en fazla 24 saatlik bot kuyruğu tüm geçmişi temsil etmez. Başka uygulamaya bağlı webhook varsa bot kurulumu ayrıca gözden geçirilmelidir.

WhatsApp (`whatsapp.json`):
```json
{"api_version":"GUNCEL_GRAPH_SURUMU","phone_number_id":"BUSINESS_TELEFON_KIMLIGI","access_token":"TOKEN_BURAYA","allow_service_costs":false}
```

Maliyet yetkisi false kaldıkça resmi gönderim uygulanmaz. Bu seçenek otomatik açılmaz. Resmi Business servisinin izin, görüşme penceresi/şablon ve fiyat koşulları kullanıcı hesabında ayrıca sağlanmalıdır. Eski Windows WhatsApp yolu değiştirilmedi; bu resmi yol ona sessizce düşmez.

Instagram (`instagram.json`):
```json
{"api_version":"GUNCEL_GRAPH_SURUMU","ig_user_id":"PROFESYONEL_HESAP_KIMLIGI","access_token":"TOKEN_BURAYA"}
```

Bu uyarlayıcı Facebook Login Graph yolunu kullanır; Instagram Login tokenına otomatik çevrilmez. Yayın önce container kimliğini saklar, FINISHED durumunu kontrol eder, sonra media_publish uygular. Hazır değilse veya bağlantı kesilirse yeni container/yayın otomatik oluşturulmaz; mevcut container kaydı kontrol edilmelidir.

YouTube (`youtube.json`):
```json
{"channel_id":"UC_ILE_BASLAYAN_KESIN_KANAL_KIMLIGI"}
```

Yükleme OAuth kanalını `mine=true` ile kontrol eder; yapılandırma/yetki hedefi başka kanalsa başlamaz. Görünürlük `private`, `unlisted` veya `public` olarak açıkça belirtilir. Google projesi/API etkinleştirme ve servis kota/yayın kuralları ayrıca geçerlidir.

## Üretim ve yayın zinciri

`video üret {"image":"JARVIS_DOSYA_ALANINDAKI_GORSEL_YOLU","duration":10}` komutu gerçek kaynak özetini çıkarır. İsteğe bağlı `audio` alanı eklenebilir. Ses/görsel dosyası Jarvis dosya alanında bulunmalıdır. Windows JSON yollarında ters eğik çizgiyi çift yaz veya `/` kullan.

Video 1280×720 MP4 olarak, 1–300 saniye sürede üretilir. FFmpeg/FFprobe yoksa unavailable döner; ücretli servise geçmez. Bu araç hareketli yapay zekâ sahnesi üretmez; mevcut görseli ve sesi videoya dönüştürür.

Görev planında YouTube publish girdisi `source_task` ile önceki `media` adımına bağlanabilir. Böylece dosya yolu ve SHA-256 gerçek üretim çıktısından alınır. Kaynak görev açık bağımlılık olmalıdır. Yayınlama yine kayıtlı hedef yetkisi veya somut onaydan geçer; üretim izni yayın izni değildir.

## Güvenilirlik ve sınırlar

- İşlem içeriği/hedefi sabittir. Aynı iş kimliği başka içerikle kullanılamaz.
- `sending` kaydı dış çağrıdan önce diske yazılır. Sonucu belirsiz işlem otomatik tekrar edilmez; aynı gönderimi iki kez uygulamamak tercih edilir. Başlangıç yapılandırması hatası da ihtiyatlı olarak unknown kalabilir; önce kaydı/bağlantıyı incele.
- `accepted` kaydındaki gerçek servis kimliği görev kurtarmada kullanılır. Bu servis kabulüdür; alıcının okuması, teslim webhook'u veya sosyal içeriğin yayında kalması değildir.
- Bilinen hassas metin tespitinde süreli hedef yetkisi otomatik göndermez; somut içerik onayı gerekir. Bu desen kontrolü her hassas veriyi algılayan bir garanti değildir.
- Kullanıcı kimliği, token, izin ve iş geçmişi ayrıdır. Silinmiş profillerin kuyruğu engine filtresinden geçmez.
- Kuyruk lease/heartbeat ve önceden atanmış görev kimliği kullanır. Kesintide aynı günlüğe döner. İptal kooperatiftir; başlamış dış işlemi geriye çeviremez.
- Yerel SQLite/JSON/dosya kontrolleri içerik doğruluğu, video kalitesi veya platformdaki son durumu garanti etmez.

## Açık kabul işleri

Gerçek Windows PC, mikrofon/ses; gerçek OAuth/Meta/Bot izinleri; her serviste canlı kontrollü gönderim/yayın ve sonuç kontrolü. WhatsApp webhook geçmişi/teslimi, Instagram Reels/yorum yönetimi, YouTube yorum takibi, tam bot güncelleme tüketimi, medya üretim stüdyosu ve genel uzman paralelliği bu pakette tamamlandı sayılmaz.

Resmi başvuru kaynakları: https://developers.google.com/workspace/gmail/api/guides/sending ; https://core.telegram.org/bots/api ; https://developers.google.com/youtube/v3/docs/videos/insert ; https://developers.google.com/youtube/v3/docs/channels/list ; https://www.postman.com/meta/whatsapp-business-platform ; https://www.postman.com/meta/instagram .

## Son test sonucu

976 genel test: bilinen 8 Windows ayar penceresi başarısızlığı, 2 atlanan test; yeni başarısızlık yok. 105 odaklı/güvenlik testi geçti. 20 Node grubu ve 6 smoke kontrolü geçti. Gerçek FFmpeg/FFprobe video üretimi test edildi; hesap/API/model/OS işlemlerinde taklitler kullanıldı. Son Instagram readiness değişikliği genel testte de denetlendi.


## Son genişleme — 13 Ekim 2026

Mesaj kutusu ve teslim durumu, kendi içeriklerine yorum okuma/yanıtlama, aynı Instagram Reels konteynerini takip etme, güvenli rollerin paralel çalışması ve yerel sahneli video üretimi uygulandı. WhatsApp yalnız etkinleştirildikten sonra gelen webhook olaylarını saklar; geçmiş sohbeti API üzerinden çekmez. Ayrıntılar: [Mesaj, yorum ve stüdyo](MESAJ_YORUM_STUDYO.md).

Canlı hesap/OAuth ve dış HTTPS webhook kurulumu, gerçek Windows/mikrofon kabul testi, kullanıcının Piper modeli veya Windows SAPI ile ses kalitesi hâlâ doğrulanmalıdır. Video stüdyosu sahne, görsel, altyazı ve ses montajıdır; fotogerçekçi üretken video modeli içermez. Eski açık iş maddeleri bu yeni kapsamla birlikte okunmalıdır.

## Güncellemede eski GitHub sürümünü reddetme — 13 Ekim 2026

Güncelleme kontrolü, kaynak doğrulama ve yedekleyerek kurma yolları kayıtlı yerel commit'in gerisindeki GitHub commit'ini ayırt eder. Eski sürüm yeni güncelleme diye sunulmaz; yedek seçeneği geriye kurma engelini aşamaz. Engellenen işlem kaynakları ve kayıtlı commit'i değiştirmez.

Bu koruma kayıtlı commit ilişkisine dayanır; ZIP'in yükleme tarihi veya dosya tarihleri sürüm kanıtı değildir. Taban commit bilinmiyorsa ya da yerel kaynaklar yayınlanmadıysa GitHub'ın güncel olduğu varsayılmaz. Normal güncellemenin yerel değişiklik engeli korunur; ayrışmış sürümü açıkça yedekleyerek alma mevcut davranıştır. Önce güncel yerel kaynakları doğrulayarak eşitlemek gerekir. Canlı Windows ve hesap kontrolleri açık kalır.

## Güncel depo: Jarvis-v2

GitHub okuma/güncelleme ve kaynak yayınlama hedefi `hamdkose-ctrl/Jarvis-v2`, dal `main`. Yeni sürüm kaydı `~/.jarvis/update-Jarvis-v2.json`; eski `update.json` değiştirilmez ve yeni deponun commit tabanı sayılmaz. İlk kullanımda GitHub doğrulaması kaynakların eşitliğini kanıtlamadan taban commit kaydedilmez. Taban bilinmiyorsa normal kurulum güvenli biçimde durur. Açılış kontrolü kaynak kurmaz. Mevcut GitHub anahtarının yeni özel depoya erişimi ayrıca gerekir; token/hesap otomatik değiştirilmez. Kullanıcı daha yeni ZIP gönderirse kaynak farkları doğrulanır; eski depo taban alınmaz.

## Gmail ekleri ve eski OAuth kaydı — 14 Ekim 2026

`görev mail ekleri <mail_kimliği>` ilk 20 ekin adını, boyutunu ve metin desteğini gösterir; ek içeriğini indirmez. `görev mail ek oku <mail_kimliği> <sıra>` kesin mail kimliği ve 1–20 sıra ile en fazla 256 KiB TXT/CSV/Markdown eki metin olarak okur. MIME/uzantı/boyut/base64/metin kodlaması ve mail kimliği doğrulanır. 20.000 karakter sınırında kesilme açıkça belirtilir. Ekler kaydedilmez/çalıştırılmaz; HTML, PDF/Office, arşiv ve yürütülebilir ekler bu yolda desteklenmez. İçerik görev talimatı değildir. Mevcut Gmail salt-okuma OAuth'u kullanılır; gizlilik ve kullanıcı ayrımı korunur. Ek anlık görüntüsü özet ve gösterim tutarlılığıyla doğrulanır; canlı API ayrıca denenmelidir.

`hesap durumu` yalnız doğru `google_legacy_owner` kaydıyla eşleşen eski Google token dosyasını gösterir. Eski izin zamanı dosya veya geçerli izin kanıtı sayılmaz; sahiplik kaydı farklıysa eski token bağlantı kabul edilmez. Tanılama dosyayı taşımaz; mevcut Google bağlantı akışı kendi sahiplik kontrollü geçişini yapar.
