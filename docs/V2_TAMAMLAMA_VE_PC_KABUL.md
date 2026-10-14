# Jarvis V2: geliştirme ve gerçek PC kabulü

Bu paket kodda yapılabilecek geliştirmeleri ve PC'de çalıştırılacak kontrolleri birleştirir. Gerçek Windows/mikrofon/hesap kabulü, yalnız aşağıdaki denemelerden sonuç alındığında tamamlanır. Test taklitleri bu kabulün yerine geçmez.

## 1. GitHub ve yerel sürüm

Menü → GitHub ve güncelleme → Doğrula. Uzak sürüm ileride ve yerel dosyalar değişmemişse GitHub'dan Al, sonra Jarvis'i tamamen kapatıp aç. Ayrışma, bilinmeyen taban veya yerelde daha yeni kaynak varsa normal güncelleme durur; bu mesajı incelemeden kaynakları değiştirme. Tekrar Doğrula'da aynı sürüm görünmeli.

## 2. Otomatik kabul raporu

Jarvis klasöründe `scripts\v2_kontrol.bat` çalıştır. Kaynak eşleşmesi, izole sürüm testleri ve yerel servis önkoşulları kontrol edilir. Varsayılan olarak gerçek Gmail, masaüstü işlemi, mikrofon, kamera veya hoparlör başlatılmaz. Rapor `v2_kabul_sonucu.json` dosyasındadır; bu dosya Git'e gönderilmez. Rapor mail metni/kimliği, ek içeriği, komut metni veya anahtar içermez.

Gmail bağlıyken: `scripts\v2_kontrol.bat --gmail --skip-suite`. İlk okunmamış mailin desteklenen eki okunup yerel kanıt sözleşmesinden geçer; posta okunmuş işaretlenmez, dosya çalıştırılmaz, cevap gönderilmez. Test eki yoksa sonuç pending'dir; tamamlandı sayılmaz.

Windows masaüstünde: `scripts\v2_kontrol.bat --desktop --narration --skip-suite`. Hesap Makinesi açılır ve 12 + 7 = 19 görevi mevcut UIA motoruyla denenir. Yerel anlatım geçici WAV üretir, hoparlörde çalmaz. Hesap Makinesi ve WAV üretiminin başarılı olması mikrofon, ses kalitesi veya diğer uygulamaların kabulü değildir.

Son kullanıcı PC denemesinde kamera, 12 + 7 = 19 ve SAPI WAV üretimi geçti. Ekran komutunu `ekran paylasımını aç` ile yeniden dene; bu yazım artık tanınır. `PC görevi ayrıntıları` adımları ve bu çalışma turunun süresini gösterir. Süre ölçümü hız iyileşmesi kanıtı değildir. Son PC'de FFmpeg/FFprobe eksik olduğundan `scripts\video_kurulum.bat` ardından Jarvis'i yeniden açıp `video araçlarını kontrol et` çalıştır.

## 3. Elle yapılacak donanım ve hesap kontrolleri

- Hey Jarvis, Konuş düğmesi, mikrofonu kapatma ve sesli cevap. Mikrofon kapalıyken sesli komut işlenmemeli.
- Ekran/kamera paylaşımı aç/kapat; Ekranı İncele; paylaşım kapatıldığında eski görüntü yeni görüntü diye kullanılmamalı.
- PC görevi iptal ve uygulama izni. Hesap Makinesi sonucunu ekranda 19 olarak gör; telefon/konuk masaüstü sınırını ayrıca dene.
- Gmail: `hesap durumu`, `İlk mailin eklerini göster`, `İlk mailin ilk ekini oku`. Ek yoksa Ek yok cevabı beklenir.
- Telegram, YouTube ve Meta hesapları için kendi bağlantıların ve ayrı kapsamlı izinlerin gerekir. Dış gönderim/yayın kabulünü yalnız kendi belirlediğin kesin hedef ve içerikle yap. Bu paket hesap bağlantısını veya teslimi varmış gibi göstermez.
- Jarvis kapalıyken tekrar eden kuyruk çalışmaz. `görev zamanla 60: Gmail okunmamış mail başlıklarımı listele`, `görev kuyruğu`; Jarvis'i süre dolmadan kapatıp yeniden aç. Aynı görev bir kez tamamlanmalı. Gelecekteki başka işi `kuyruk iptal KİMLİK` ile iptal et; çalışmamalı. Tekrar eden işler için `görev tekrarla 300: Gmail okunmamış mail başlıklarımı listele` kullan; kaçırılan tekrarlar peş peşe çalışmamalı.

## 4. Hafıza düzeltme ve unutma

`hafızamı göster` onaylı bilgileri listeler. `hafıza düzelt: eski bilginin tamamı | yeni bilgi` yalnız tam eşleşen tek kaydı değiştirir. `hafıza unut: bilginin tamamı` yalnız seçilen onaylı bilgiyi siler. Kısmi/çoklu eşleşme tahmin edilmez. Diğer kullanıcıların hafızası değişmez; disk yazımı başarısızsa bellekteki eski bilgi korunur. Sohbet geçmişi, görev raporları ve yüklenen belgeler ayrı veri alanlarıdır; bir fact'i unutmak bu alanları topluca silmez.

## 5. Ortak PC sözleşmesi ve uzman üretim akışları

Ses/parlaklık/medya, uygulama açma-kapatma, sistem kapatma-iptal ve pencere işlemlerinin 11 giriş noktası ortak tür denetimi ve işlem kaydı kullanır. Mevcut Windows/odak/izin kontrolleri korunur. Son 200 işlemde yalnız kimlik, kullanıcı, istek, risk ve durum saklanır; argümanlar ve özel metinler saklanmaz. PC işlemleri otomatik yeniden yürütme sınıfında değildir. Kapatma komutunun iletilmesi PC'nin gerçekten kapandığı kanıtı değildir. Sözleşme masaüstü yetkisini genişletmez; UIA görevleri mevcut kendi kanıt/izin motorunda kalır.

`görev akışları` hazır ekipleri gösterir. Akışı seçmek planlayıcı model çağrısı yapmaz; araştırma ve yazım kendi mevcut LLM yollarını kullanabilir:

- `görev akışı rapor: https://example.com | Türkçe kaynaklı rapor hazırla`: araştırmacı → yazar → doğrulayıcı.
- `görev akışı mail: MESAJ_KİMLİĞİ | Kısa cevap taslağı hazırla`: Gmail okuyucusu → yerel taslak yazarı → doğrulayıcı. Gönderim yok.
- `görev akışı kod: Hesaplama hatasını düzelt`: mevcut şifreli geliştirme alanı → doğrulayıcı. Alan açık değilse durur; kaynak otomatik uygulanmaz.
- `görev akışı video: {"scenes":[{"caption":"Jarvis denemesi","duration":3}],"layout":"landscape"}`: yerel montaj → doğrulayıcı. FFmpeg gerekir; dış yayın veya fotogerçekçi üretken model içermez.

Akışlar mevcut görev kimliği/iptal/devam/kanıt kurallarını kullanır. Önceki adım başarısızsa bağlı adımlar çalışmaz. Yeni ajan framework'ü, ücretli model veya otomatik servis gönderimi eklenmedi.
