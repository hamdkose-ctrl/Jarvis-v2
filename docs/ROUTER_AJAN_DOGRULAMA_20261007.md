# Router/ajan doğrulaması · 7 Ekim 2026

> Tarihsel kayıt: Bu belgedeki eski sağlayıcı sırası/OpenRouter/ücretli vendor seçimi güncel hedef değildir.14 Kasım2026 Router V2 ve uygulama/emeklilik haritası geçerlidir: [güncel mimari](architecture/JARVIS_ROUTER_ARCHITECTURE_V2.md), [uygulama/kabul](architecture/JARVIS_ROUTER_V2_IMPLEMENTATION_AND_RETIREMENT_MAP.md).


Tam sabit doğrulama koşucusu: 255 Python testi; 254 başarılı, 1 Windows DPAPI testi Linux ortamında atlandı. 8 JavaScript davranış grubu ve 6 Python entegrasyon smoke akışı başarılı. WebUI JavaScript sözdizimi kontrol edildi. Son küçük değişiklikler (testte isteğe bağlı Playwright adaptörü, görev ilerleme olayı ve Windows kurulum hata kodu) sonrasında ilgili 15 ajan/tarayıcı testi ve gerçek main/Bridge/ses smoke akışı yeniden geçti.

Yeni kapsam: görev türü seçimi, kullanıcıya özel ücretsiz hesap tercihi/anahtar ayrımı, ücretli model reddi, kota fallback ve bekletme, iptal, gizlilik, Gemini yardımcı çağrılarının bütçe kapısı, otomatik sağlayıcı UI, gerçek rapor kaydı ve geri okuma, bağımlılık hatası, görev onayı/iptali/devamı, geliştirme modu kilidi, beklenen tarayıcı sonucu, değişen hedef, çoklu seçici, şifre alanı reddi, onayın etki öncesi tüketilmesi ve tekrar gönderimin engellenmesi, PC/ses tanılamasının donanım başarısı iddia etmemesi.

Model/OS/tarayıcı adaptörleri otomatik testlerde taklit edildi; gerçek iş mantığı ve dosya/sohbet/Bridge yönlendirmesi çalıştırıldı. Chromium paketi kurulabildi fakat tarayıcı ikilisi indirmesi eksik/geçersiz ZIP döndürdü; gerçek Chromium sayfası açma testi yapılamadı. Windows donanımı ve kullanıcının gerçek model hesapları bu ortamda yoktu. Bunlar [bekleyen gerçek ortam doğrulamaları](BEKLEYEN_ISLER.md) içinde açıkça kaldı.
