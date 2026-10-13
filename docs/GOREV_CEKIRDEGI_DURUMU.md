# Ortak görev çekirdeği — teslim durumu

## Yapılan
Mevcut task_agents motoru güçlendirildi; araştırma, rapor, tarayıcı, kod taslağı ve doğrulama rolleri korunuyor. Kalıcı göreve devam/iptal/geçmiş komutları, görev belleği, kullanıcı model bağlamı, dosya SHA-256 kontrolü, iptal yarışı koruması, atomik saklama ve geçiş günlüğü eklendi. Arayüz dosyaları bu pakete alınmadı.

## Kontroller
- Son kodda 50 odaklı kurtarma, görev, kalıcılık ve komut yönlendirme testi geçti.
- Tam Python keşfinde 916 test çalıştı; 8 Windows ayar testi Linux ortamında başarısız, 2 test atlandı.
- Aynı 8 Windows başarısızlığı eski task_agents koduyla, aynı donanım taklitleri altında da yeniden görüldü. Yeni çekirdek kaynaklı bir hata olarak raporlanmadı. Windows'ta tam doğrulama hâlâ gerekir.
- 6 smoke grubu geçti. Son görev kodunda router_agents_smoke ayrıca geçti: gerçek main.handle, Bridge ve ses komut yönlendirmesi; model ve donanım taklitleri kullanıldı.
- Gerçek modele/tarayıcı hesabına çağrı, para harcama veya kullanıcı hesabında yayın/gönderim yapılmadı.

## Açık işler
Canlı PC doğrulaması; tüm servislerin resmi bağlantıları, gönderim/yayın yetkileri, medya üretimi, arka plan zamanlayıcısı ve daha gelişmiş uzman ekipleri. Ana plan JARVIS_ANA_PLAN.md içindedir. Bütün sosyal medya sistemi tamamlandı iddiası yoktur.

## Depo
GitHub'a gönderim, commit veya PR yok. Yeni runtime bağımlılığı yok. Geliştirme ortamına kurulan test bağımlılıkları uygulama paketine alınmadı. Anahtar/kişisel veri/görev günlükleri teslimde yok.
