# PC taban kabulü — ses ve yazı

20 Ekim 2026. Bu liste hazırlanmıştır; aşağıdaki denemeler burada yapılmadı. Durumların tamamı başlangıçta **Denenmedi**. Yerel test/CI gerçek PC kabulü değildir.

## Sürümü sabitle

- Jarvis kapalıyken repo içinde `git status --short`, `git branch --show-current`, `git rev-parse HEAD` ile değişiklik/dal/commit kaydet. Yerel değişiklik varsa silme, reset veya üstüne yazma; önce durumu incele.
- Temiz main üzerinde `git pull --ff-only origin main`; ayrışma varsa dur ve çıktıyı getir. Son commit'i tekrar kaydet. Başka daldaki değişikliği main'e taşıma.
- Aynı Windows ortamında `python -X utf8 -m modules.validation`. Son satır “Tüm test grupları başarılı.” ve çıkış 0 olmalı. Bu PC denemelerinin sonucu değildir.
- Normal mevcut başlatıcıyla aç. Kullanıcıyı ve bağlı hesabı yerelde doğrula. Şifre/anahtar/özel mail içeriğini rapora ekleme.
- main tabanı `7563161` altı düzeltmeyi içeriyor (#206/#208/#209/#210/#211/#212). **#213 (62-B) main'de yok:** aşağıdaki T07'de açık soru varken “6 dolar”ın yutulması bekleyen bilinen hatadır. Bu durum tüm tabanın geçtiği anlamına gelemez; yeni sürüm gelince T07 tekrar edilir. CI ödeme engeli giderilmeden #213 birleştirilmez.

## Uygulama biçimi

Önce yazılı turu, sonra aynı başlangıç koşullarıyla sesli turu yap. Bir turun etkisini diğerinin başlangıcı sayma. Ses turunda tanınan metni de kaydet: yanlış tanıma ile doğru metnin yanlış yönlendirilmesini ayır. Mikrofon kapalı denemesinde komut gerçekleşmemeli. Kayıt olmadan seçilen handler'ı tahmin etme; iz görünmüyorsa “yol bilinmiyor” yaz.

Açık gerçek işi silerek test ortamı temizleme. Test için ayrı profil ve hassas olmayan örnek dosyalar kullan. Bekleyen gönderim/para/yıkıcı işlem oluşturmadan önce ayrıca uygun test hesabı/hedefi belirlenmeli; bu liste canlı dış gönderim izni değildir. Alıcı sorusu senaryosunu güvenli hazırlayamıyorsan T07–T09 Denenmedi kalır.

| ID | Başlangıç / cümle | Beklenen ve kanıt | Yazı | Ses |
|---|---|---|---|---|
| T01 | Açık görev/pending yok: “iptal” | “İptal edilecek açık görev yok.”; yeni sohbet/görev/onay veya işlem oluşmaz | Denenmedi | Denenmedi |
| T02 | Açık görev/pending yok: “devam”, ardından “onayla” | Kayıtsız işi başlatmaz, başarı veya gönderim iddiası yapmaz; mevcut sürümün gerçek cevabını kaydet | Denenmedi | Denenmedi |
| T03 | Örnek dosyalar: “hangi dosya yazıldı” | Yanıtı aynen kaydet; ham JSON olmamalı. Yalnız liste veriyorsa “son yazılan bulundu” sayma; LLM'nin files_list seçtiği henüz kanıtlanmış değil | Denenmedi | Denenmedi |
| T04 | Kayıtlı uzun hedef: “hedef durumu” | En çok iki satırlık özet: durum/adım/kaynak/varsa rapor yolu; eski raporun tam metnini dökmez | Denenmedi | Denenmedi |
| T05 | Açık soru yok: “6 dolar” | Kaynaklı TL karşılığı veya dürüst kaynak erişim hatası; mail/alıcı/gönderim sorusu yok. Kur hesabı gerçek kaynak tarihiyle kontrol edilir | Denenmedi | Denenmedi |
| T06 | Açık bağımsız istek: “hedef son dakika haberleri” | Araştırma süreci; genel kelimeleri konu sayan hata yok. Tamamlandı diyorsa tarihli tekil haberler, en az iki yayıncı ve açılabilen rapor kanıtı; eksikse kısmi/başarısız açık | Denenmedi | Denenmedi |
| T07 | Güvenle hazırlanmış taze alıcı sorusu: “6 dolar” | Hedefe cevap sayılmadan kur yoluna gitmeli. #213 main'e girmeden bilinen hata olarak ölçülür; geçti diye varsayılmaz | Denenmedi | Denenmedi |
| T08 | Aynı tür taze soruda gerçek test adresi cevabı | Soru cevabı olarak devam edebilir; gönderim onayı yerine geçmez. Gerçek gönderim yapmadan onay öncesinde dur | Denenmedi | Denenmedi |
| T09 | Süresi geçmiş/iptal edilmiş soru: yeni bağımsız kur sorusu | Eski hedef canlanmaz; izin ve onay başka işe taşınmaz | Denenmedi | Denenmedi |
| T10 | Bekleyen hassas olmayan fotoğraf işlemi: “iptal” | “Tamam, fotoğrafla bir şey yapmıyorum.”; fotoğraf cevabı yutulmaz, yeni görev yok | Denenmedi | Denenmedi |
| T11 | İzinli, geri alınabilir PC işi sürerken Durdur | Yeni adım başlamaz; durum gerçeği söyler. O an tamamlanan adım geri alınmış sayılmaz; sonucu gözle | Denenmedi | Denenmedi |
| T12 | A kullanıcısının test bağlamı varken B profiline geç | B cevabı A işini sürdürmez; A içeriği B'ye görünmez. Gerçek hesapları değiştirmeden uygun test profilleriyle yap | Denenmedi | Denenmedi |
| T13 | “Mail göndermek nasıl çalışır?”, “Bu maili taslak hazırla, gönderme” | İlkinde açıklama, ikincide en fazla taslak; mail kelimesi/olumsuzluk dış gönderim başlatmaz | Denenmedi | Denenmedi |
| T14 | Ses için mikrofon kapalı; ardından TV/YouTube/yankı ortamı | Kapalıyken işlem yok; yanlış tetikleme varsa koşulu/tanınan metni kaydet. Tehlikeli komutla deneme yapma | Uygulanamaz | Denenmedi |

T06 canlı kaynak/sağlayıcı gerektirir; kota yoksa “engelli/kısmi” kaydet. “Ollama yüklenmemiş veya çalışmıyor” bağlantı reddi mesajı, servis hiç kurulu değil teşhisi sayılmaz. Gerçek sağlayıcı hata nedenini ham anahtar içeren loglarla paylaşma.

## Sonuç biçimi

```text
Commit / dal:
ID:
Giriş: yazı / ses
Başlangıç bağlamı:
Söylenen metin / tanınan metin:
Beklenen:
Gözlenen cevap ve gerçek etki:
Yol: kanıtlı handler / bilinmiyor
Çıktı dosyası veya yerel kanıt:
Sonuç: Geçti / Kaldı / Kısmi / Engelli / Denenmedi
Tekrar gerektiren koşul:
```

Rapor yerelde kullanıcıya ait kalır; ekran görüntüsündeki kişisel verileri paylaşmadan önce temizle. Aynı hata ardışık tekrarlarla gerçek dış etki oluşturmamalı. İlk hatada o senaryoyu durdur, bağlamı kaydet; diğer bağımsız güvenli senaryolar yapılabilir. Tüm zorunlu senaryolar kanıtlanmadan “taban tamam” yazılmaz. Bu küçük kabul, birleşik plandaki 10/10 V2 kabulünün veya 14 alanın tam kapsamının yerine geçmez.
