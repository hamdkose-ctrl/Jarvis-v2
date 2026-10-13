# İsteğe bağlı OpenAI ve Claude · 7 Ekim 2026

Bu tam paket önceki sesli işlem, PC kontrolü ve atölye kaldırma güncellemelerini içerir.

## Kurulum

Jarvis'i kapat. ZIP içindeki **Jarvis** klasörünün içeriğini mevcut kurulumun üzerine kopyala. `baslat.bat` ile yeniden aç. Kişisel `.jarvis` klasörünü silme.

## Kullanım

Ayarlar → Yapay Zekâ ve Bağlantılar bölümünde OpenAI ve Claude kartları bulunur.

1. Kullanmak istediğin sağlayıcının API anahtarını gir ve **Kaydet** de. Anahtar yalnız aktif Jarvis kullanıcısına kaydedilir; sağlayıcı değişmez.
2. **Modelleri getir** ile hesabına açık model kimliklerini al. Bu düğme model listesi çağrısı yapar; sohbet üretme denemesi yapmaz. Alternatif olarak model kimliğini yazabilirsin. Listede görünmek, her modelin sohbet ve görüntü girişini desteklediği anlamına gelmez.
3. Modeli seçip **Seç ve kullan** de. Sağlayıcı ve model değişikliği ayrı onay ister. İptal edersen etkin sağlayıcı ve etkin model değişmez. Anahtar/model taslağını kaydetmek, ücretli üretim çağrısı yapmaz.
4. Ücretsiz kullanım düzenine dönmek için mevcut Gemini/Groq seçeneğini veya yerel Ollama'yı seç. Varsayılan seçeneği Gemini kullanır ve yeni ücretli sağlayıcılara otomatik geçmez.

Ücretler ve hesap erişimi ilgili sağlayıcıya bağlıdır. Bu pakette fiyat veya ücretsiz kota garantisi verilmez. Sağlayıcı hatasında otomatik ücretli alternatif seçilmez; ücret doğurmuş olabilecek zaman aşımı isteği kendiliğinden tekrarlanmaz.

Claude için çoklu çalışma alanı anahtarı kullanıyorsan sağlayıcının istediği çalışma alanı kimliğini ilgili isteğe bağlı alana gir.

## Kapsam

OpenAI Responses ve Claude Messages bağlantıları sohbet, akıl yürütme, kod üretme ve Jarvis'in kayıtlı işlemlerinin yönlendirilmesinde kullanılır. Seçilen model destekliyorsa ekran/kamera görüntüsü analizi de bu sağlayıcıya gider. Modelin desteklemediği bir istek hata olarak bildirilir; Gemini'ye gizlice yönlendirilmez.

OpenAI/Claude seçiliyken Gemini Live sohbeti devreden çıkar; mevcut ses tanıma → seçilen yapay zekâ → normal seslendirme yolu kullanılır. Uyandırma dinleyicisinin bu yola geçebilmesi için standart dinleyici canlı modla birlikte hazırlanır, canlı mod açıkken mikrofonu açmaz. Mikrofon kapalı bayrağı korunur. Bu paket OpenAI Realtime veya Claude için ayrı gerçek zamanlı ses akışı eklemez.

Ses tanıma ve anlamsal gömme ayrı mevcut işlevlerdir: OpenAI/Claude anahtarı bunların Gemini/Google veya yerel Ollama gereksinimlerini otomatik değiştirmez. İsteğe bağlı sağlayıcı anahtarları tüm Jarvis işlevlerinin tek anahtarla çalışacağını garanti etmez.

Gizli ve yalnızca yerel modda yeni ücretli bulut adaptörleri ağ çağrısı yapmaz. Windows anahtar koruması çalışmazsa yeni anahtar kaydedilmez. API anahtarları sohbet kaydında, sağlayıcı hata metninde veya UI durumunda gösterilmez.

## Temizlik

Kullanılmayan `key_user` ve `_ohist` değişkenleri kaldırıldı. Ana işlevlerin içinde davranışı olmayan `pass` kalıntıları temizlendi; hata yakalama blokları korundu. Eski atölye dosyalarını temizleyen kurulum adımı korunur. Paket Python önbelleklerini ve eski kurulum günlüğünü içermez; kurulumun ürettiği tanılama günlüğü silinmez. Kişisel hafıza, not, görev, anahtar ve `.jarvis` çalışma günlükleri korunur.

## Doğrulama

Gerçek ücretli API çağrısı yapılmadı. İstekler test adaptörleriyle doğrulandı: kişiye ait anahtar, model listesi ve sayfalama, OpenAI/Claude istek biçimleri, geçmiş ve görüntü gönderme, gizlilik, onay/iptal, aday modelin etkin modeli değiştirmemesi, anahtar silme, zaman aşımı/kota hatasında tekrar yapmama ve Gemini'ye ücretli hata sonrası düşmeme.

Yeni sağlayıcı testleri ve mevcut UI davranış grupları geçti. Önceki Linux test ortamında görülen Windows yazı tipi/DPAPI ve ağ arayüzü izin sorunları genel çalıştırmada devam eder. Gerçek Windows mikrofon geçişi ve hesapta seçilen ücretli model bu ortamda donanım/gerçek anahtarla doğrulanmadı.

## Resmi API kaynakları

- [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
- [OpenAI model listesi](https://developers.openai.com/api/reference/resources/models/methods/list)
- [Claude Messages API](https://platform.claude.com/docs/en/api/messages/create)
- [Claude API kimlik doğrulaması](https://platform.claude.com/docs/en/api/overview)
- [Claude model listesi](https://platform.claude.com/docs/en/api/models/list)
