# Ayrı kopyada test ve bağımsız açılış kurtarması

## Günlük kullanım

`baslat.bat` artık standart kütüphane ile çalışan `launcher.py` üzerinden açar. Geliştirme alanında şifre ve son uygulama onayı korunur. Taslak geçici proje kopyasına uygulanır; asıl kaynaklar test sırasında değişmez. Test kopyası kaynakları ve görselleri içerir, `.venv`, önbellek ve özel veri deposunu içermez. Her test grubu ayrıca geçici kullanıcı verisi kullanır. Test kopyaları işlem sonunda silinir.

Mevcut regresyon testleri aday kodda önce çalışır. Test dosyaları değiştirilmişse adayın kendi testleri de çalışır. Böylece model mevcut testleri silerek veya zayıflatarak geçiş sağlayamaz. Kurtarıcı, başlatıcı ve doğrulama altyapısı modelin düzenleme kapsamından çıkarılmıştır.

Testlerden sonra kaynak hash'leri yeniden kontrol edilir. Test sırasında elle değiştirilmiş dosya üzerine yazılmaz. Yalnız değişen dosyaların eski baytları ve yeni sürüm hash'leri kalıcı işlem kaydına yazılır; bütün projenin kalıcı kopyası alınmaz. PNG referansı `asset` aracıyla taslak olarak alınabilir; görsel ekleme/değiştirme/silme ve SVG düzenlemesi aynı geri alma akışını kullanır.

## Bağımlılıklar

Bağımlılık listesi değiştiğinde mevcut Python ortamına paket kurulmaz. Tam aday sürüm kilidi ile ayrı sanal ortam hazırlanır ve testler onun Python'u ile çalışır. `requirements.txt` değişikliği için kilit dosyasının da güncellenmesi gerekir. Paket kurulumu/test başarısızsa yeni ortam silinir; çalışan ortam korunur. Başarılı kurulumun Python yolu kaydedilir; yeniden başlatıcı bu ortamı seçer. Geri alma dosyalarla birlikte önceki Python yolunu da geri getirir. İndirme başarısızlığında uygulama ilerlemez.

## Yeniden başlatma ve kurtarma

Uygulama modülleri yüklenmeden önce yarım kalmış dosya işlemi yedekten toparlanır. Yeni sürümde hem komut motoru hem web açılış kurulumu hazır sinyali verir; süreç 5 saniye daha çalışmalıdır. Başlangıç için 120 saniye tanınır. Süre dolarsa veya süreç erken kapanırsa yeni süreç durdurulur, önceki kaynaklar/ortam geri getirilir ve önceki sürüm bir kez açılır. Bu açılış kontrolü mikrofon, gerçek model veya tarayıcıdaki her ekran davranışını doğrulamaz.

Windows başlatıcısının bağımlılık kontrolü ve eski kurulum kalıntılarını temizleme davranışı korunur. Bu kontrollerden önce yarım kalan işlem kurtarılır; açılış onayı bekleyen aday ortam yerinde onarılmaz, gözetimli açılışa bırakılır.

`python gui.py` doğrudan çalıştırılırsa bağımsız gözetim atlanır; günlük kullanımda `baslat.bat` veya `python launcher.py` kullanın. Açılış kontrolü bekleyen tek geliştirme tamamlanmadan başka geliştirme uygulanmaz. Kullanıcı sonradan bir dosyayı elle değiştirdiyse kurtarma bu dosyayı ezmek yerine durur ve yedeği korur.

## Saklama sınırı

İşlem geçmişi en fazla son 3 kayıt ve 100 MiB hedefiyle temizlenir. Bekleyen kurtarma ve en son sağlıklı sürüm kaydı silinmez; bu korunan kayıtlar gerektiğinde sınırın önüne geçer. Tek değişiklik 100 MiB kayıt sınırını aşarsa kaynaklara dokunmadan reddedilir. Kullanılmayan, bu kuruluma ait aday Python ortamları geçmiş temizliği sırasında kaldırılır; orijinal `.venv` silinmez. Python ortamlarının paket boyutu bu 100 MiB kaynak-yedek sınırına dahil değildir. Eski bir kaydın saklama süresi dolmuşsa otomatik geri alma bunu açıkça bildirir.

## main.py

Komut öncelikleri `modules/command_manager.py` içine taşındı. Kullanıcı profili, oturum, olay yayımlama ve işlev bağımlılıkları açık `CommandContext` ile verilir. Bekleyen onay → Router → tanılama → görev ajanı → PC yardım → geliştirme → tablo/çeviri/çalışma sırası korunur. `main.handle()` ses, web ve telefon için mevcut giriş noktası olarak kalır. Bu, adım adım ayrıştırmanın ilk devamıdır; bütün ana döngü ve ses koordinasyonu bu değişiklikte taşınmadı.

Kullanıcı hafızası/ayarları üzerinde veri şeması göçü bu akışın kapsamı dışındadır; kaynak geri alma, uygulamanın gerçek kullanım sırasında yaptığı veri değişikliklerini otomatik geri çevirmez. Böyle bir değişiklik ayrıca veri göçü ve veri yedeği tasarımı gerektirir.

## Doğrulama

Linux ortamında ortak Python/JavaScript/bütünleşme koşucusu çalıştırılır. Yeni testler asıl kaynakların test boyunca değişmemesini, test esnasında yapılan elle düzenlemeyi, PNG baytlarının geri alınmasını, yarım işlemi, gerçek alt süreçte bozuk açılışı ve sağlıklı açılışı, iki hazır sinyali zorunluluğunu, bağımlılık kurulum hatasını, Python yolu geri dönüşünü, yedek sınırlarını ve komut önceliklerini kapsar. Gerçek Windows arayüzü ve gerçek Windows paket kurulum/güncelleme denemesi bu ortamda yapılmamıştır.

İlk paket kontrolü: 388 Python testi (387 başarılı, Windows DPAPI testi atlandı), 10 JavaScript davranış grubu, JavaScript sözdizimi kontrolleri ve 6 başsız bütünleşme grubu başarılı. Bozuk açılış denemesindeki kasıtlı SyntaxError, geri alma testinin beklenen girdisidir.

Son genel kontrol paketinde 396 Python testi (395 başarılı, Windows DPAPI testi atlandı), JavaScript kontrolleri ve 6 başsız bütünleşme grubu geçti. Ek düzeltmeler `docs/GENEL_KONTROL_20261008.md` içinde.
