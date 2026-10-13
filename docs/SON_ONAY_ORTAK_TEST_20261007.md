# Son onay ve ortak doğrulama · 7 Ekim 2026

- Sohbet düğmesi, şifre penceresi ve durum alanı: Şifre Korumalı Geliştirme Modu.
- Otomatik uygulama kaldırıldı; önceki kayıtlı auto_apply=True değeri yok sayılır. Şifre yalnız giriş içindir. Kullanıcı değişiklik farkını görüp Uygula / değişiklikleri uygula ile açık son onay verir.
- Geliştirme, GitHub yayını ve run_tests.bat aynı modules/validation.py üzerinden doğrulanır: Python derleme, unittest, bütün webui JavaScript sözdizimi, 9 JavaScript davranış grubu ve 6 bütünleşme akışı. Node yoksa veya zorunlu test eksikse başarı verilmez. Her grup geçici ve ayrı veri klasörünü kullanır. GitHub yayını kullanıcı komutuyla yapılır.
- main_planner.py: not, takvim, makro ve günlük özet işlemleri; web_window.py: pencere, widget ve tepsi işlemleri. Bağımlılıklar çalışma zamanı nesnesiyle açıkça aktarılır; mevcut giriş noktaları korunur. main.py 2818 → 2533, web.py 2090 → 1812 satır. Bölünmenin bu aşaması tamamlandı; dosyaların tüm sorumlulukları ayrılmış değildir.

## BAT dosyaları

- baslat.bat: günlük başlatma.
- Güncel paket: tarayıcı ajanı ve Chromium, kurulum.bat ile birlikte hazırlanır.
- Güncel paket: çevrimdışı Hey Jarvis modelleri kurulum.bat ile birlikte hazırlanır; ayrı uyandırma kurulumu kaldırıldı.
- run_tests.bat: günlük kullanım için gerekmez. Güncelleme sonrası bir kez önerilir; Python sanal ortamı ve Node.js gerekir. Çift tıklayınca sonuç penceresi açık kalır.

## Sınırlar

Testler Linux ortamında; modeller, Windows işlemleri ve donanım taklitleriyle çalışır. Gerçek Windows pencereleri, mikrofon, hesaplar ve Chromium cihazda doğrulanmalıdır.

Son doğrulama: 282 Python testi (281 başarılı, 1 Windows DPAPI testi atlandı), 9 JavaScript davranış grubu ve 6 bütünleşme grubu başarılı. Python/JavaScript sözdizimi ve ZIP CRC/kaynak eşleşmesi temiz.
