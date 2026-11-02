# JARVIS V5 — Değerlendirme · 7 Ekim 2026

Bu rapor, kaynak ağacının **statik okunmasıyla** hazırlanmıştır. Hiçbir donanım, canlı servis
veya çalışan kurulum uçtan uca denenmemiştir. Bu rapordaki hiçbir satır "doğrulandı" sayılmaz;
"kaynakta mevcut" ile "kurulumda çalıştığı görüldü" ayrımı bilinçli olarak korunmuştur.

---

## 1. İnceleme kapsamı

İncelenen alanlar ve dayanakları:

| Alan | İncelenen dosyalar |
| --- | --- |
| Ana komut hattı | `main.py` (2.533 satır), `modules/router.py`, `modules/smart_router.py` |
| Çalışma ekranı | `web_study.py`, `web_study_sources.py`, `web_study_exams.py`, `modules/study.py`, `modules/study_services.py` |
| Dosyalar ekranı | `web_files.py`, `modules/nxapi.py` |
| Ekran (görü) sayfası | `modules/vision.py`, `webui/nx.js` (Ekran bölümü) |
| Araçlar sayfası | `webui/nx.js` (Araçlar/Takvim/Telefon bölümleri) |
| Şifreli geliştirme modu | `modules/developer.py`, `web_chat.py`, `docs/GELISTIRME_MODU.md` |
| Güvenlik ve gizlilik | `modules/privacy.py`, `modules/phone.py`, `web.py`, `tests/test_cleanup_security.py` |
| Hata raporlama | `modules/diagnostics.py` |
| Bağımlılıklar | `requirements.lock.txt`, `requirements.txt`, `requirements-browser.txt` |
| Belgelendirme | `README.md`, `docs/*.md` |

Yöntem: yalnızca okuma ve karşılaştırma. **Projede kalıcı bir kod değişikliği yapılmadı.**

---

## 2. Kaynak ve kurulum doğrulama durumu

**İlke:** Kaynak kod ile çalışan kurulum aynı şey değildir. Güncelleme akışı "eski kurulumun
üzerine kopyala, `baslat.bat` ile aç" mantığındadır; bu yüzden kaynakta bulunan bir davranış,
çalışan kurulumda aktif olmayabilir. Bundan sonra her özellik için iki durum ayrı tutulmalıdır:
**"kaynakta var"** ve **"kurulumda doğrulandı"**.

| Özellik | Kaynakta | Kurulumda doğrulandı | Dayanak |
| --- | --- | --- | --- |
| Şifreli geliştirme kapısı (PBKDF2, kullanıcı başına) | Var | Doğrulanmadı | `modules/developer.py:98` |
| Geliştirme kapısı sesli/yazılı komutla açılamaz | Var | Doğrulanmadı | `modules/developer.py:~524` |
| Yol kısıtı: yalnız kullanıcı klasörleri | Var | Doğrulanmadı | `modules/nxapi.py:_roots/allowed` |
| Görüntü yalnız sorunca tek kare gönderilir | Var | Doğrulanmadı | `modules/vision.py` başlığı |
| Telefon token'ı düz metin (`phone_token.txt`) | Var | Doğrulanmadı | `docs/DENETIM_RAPORU.md` |
| Anahtarlar DPAPI ile şifreli | Var | Doğrulanmadı | `modules/privacy.py:_dpapi` |

**Önerilen doğrulama yöntemi:** Kaynak ağacı ile kurulu ağaç, dosya hash'leriyle karşılaştırılsın.
Projede hazır hash altyapısı vardır (`updater.py`, `modules/git_publish.py`; git-blob sha1).
Karşılaştırma yalnızca proje kaynaklarını kapsamalı; `.venv`, `.jarvis`, kullanıcı verisi, loglar,
önbellekler ve yedekler hariç tutulmalıdır. Sonuç dört grupta raporlanmalıdır:

- **aynı** · **eksik** (kaynakta var, kurulumda yok) · **farklı** (içerik değişmiş) · **fazladan** (kurulumda var, kaynakta yok)

---

## 3. Kritik bulgular

**Yüksek**
1. **Kurulum parity'si doğrulanmamış.** Kaynak ile çalışan kurulumun aynı olduğu gösterilemiyor; her davranış iddiası bu yüzden "kaynakta var" düzeyinde kalıyor. (Bkz. Bölüm 2.)
2. **`.gitignore` yedek ve log kapsamıyor.** *(Düzeltildi — 7 Ekim 2026.)* Mevcut 6 satır `.backups/` ve `kurulum.log` içermiyor; ikisi de yanlışlıkla commit'lenebilir. *(Düzeltme: `*.zip` gibi geniş bir desen eklenmemeli — yalnızca geçici paketler hedeflenmeli; dağıtım paketleri kaybolmasın.)*
3. **Kritik işlemlerde hata nedeni görünmüyor.** *(Temel eklendi — 7 Ekim 2026; kritik handler'lara bağlanması bekliyor.)* `modules/diagnostics.py` bilinçli olarak hata mesajını ve nedenini atmıyor değil, **atıyor**; yalnızca tür + konum yazılıyor. Kullanıcı genel bir başarısızlık cümlesi görüyor, logda neden yok. Hedef sayı azaltmak değil, **açıklanabilirlik**.

**Orta**
4. **Geliştirme kapısında deneme sınırı yok.** *(Eklendi — 7 Ekim 2026.)* `unlock()` PBKDF2-HMAC-SHA256 (310.000 iterasyon, 16 byte salt, sabit-zamanlı karşılaştırma) kullanıyor — iyi. Ancak deneme sayacı yok ve `_AUTH` süreç içidir; yeniden başlatma sayacı sıfırlar. Şifre en az 6 karakter olduğu için kaba kuvvet tamamen engellenmiş değil.
5. **Pencere öne getirme kırılgan ve sessiz.** *(Kısmen — 7 Ekim 2026: artık günlüğe uyarı yazıyor.)* `modules/nxapi.py` ctypes + thread-input attach + son çare F24 kullanıyor. Başarısızlık sessiz olduğu için kullanıcı işlemin gerçekleştiğini sanabilir; bu yüzden önceliği **orta** (düşük değil).
6. **Kopyalanmış PDF okuma mantığı.** `modules/study.py` içindeki ayrı-süreç PDF okuyucu, `docs.read_document`'in PDF kısmının kopyası olduğunu kendi yorumunda belirtiyor — bakım borcu.
7. **Arayüz aksiyonları komut hattına bağlı.** Dosyalar ve Ekran düğmeleri cümleye çevrilip regex/LLM yönlendirmesine gidiyor; sonuç için yoklama gerekiyor.

**Not (DPAPI kapsamı):** Anahtarların DPAPI ile korunması yerindedir, ancak `CryptProtectData`
**Windows kullanıcı hesabına bağlıdır**. Telefon servisi başka bir Windows kullanıcısı veya servis
hesabı altında çalışırsa anahtar çözülemez; bu durumda makine kapsamı ya da ayrı bir kapsam tasarımı ayrıca değerlendirilmelidir.

**Düşük / yapısal**
8. `main.py` 2.533 satır; komut mantığının çoğu tek dosyada ve yüzlerce regex ile yönlendiriliyor.
9. `webui/nx.js` 1.187 satır monolit; küresel durum ve inline HTML şablonları.
10. `NAV` / `APPS` / `TOOLS` giriş noktaları aynı işlevleri elle çoğaltıyor.
11. `study_overview` tek büyük sözlük döndürüyor; sınav analizi tazeliği string birleştirmeyle kurulan imzaya bağlı.

**Olumlu (korunmalı)**
- Çalışma ekranının mimarisi projenin en sağlıklı bölümü: `web_study.py` üç sorumluluğa bölünmüş ve bağımlılıklar `StudyServices` üzerinden **açıkça enjekte ediliyor** — `main.py`'deki geri-dönüş bağı burada yok. Yeni kodlar için şablon budur.
- Gizlilik disiplini: yol kısıtları, `127.0.0.1` + oturum token'ı, `no-store`/`nosniff`/`DENY` başlıkları, 413 sınırı, `privacy.redact` (anahtar/e-posta/IBAN/kart/telefon/T.C.).
- Görü gizliliği: görüntü yalnız soru sorulduğunda tek kare gönderiliyor; önizleme yalnız bilgisayarda.

---

## 4. Önceliklendirilmiş yol haritası

0. **Önkoşul — ortam, proje düzeltmesi değildir.** Önce mevcut Python yolunu ve projenin test çalıştırıcısını doğrula (`run_tests.bat`, `python -m unittest discover -s tests -q`). Yeni kurulum gerekiyorsa bu ayrı bir ortam işidir; kod değişikliği sayılmaz.
1. **Kurulum parity'sini ölç** (Bölüm 2'deki hash karşılaştırması). Diğer her iddianın önkoşulu budur.
2. **Kritik yollarda hata nedenini açıklanabilir yap.** Güvenli sıra: (a) URL sorgu ve fragment kırp, (b) `privacy.redact(..., force=True)` uygula, (c) uzunluğu sınırla, (d) hata türünü ve güvenli durum kodunu logla, (e) kullanıcıya kritik işlemlerde anlaşılır açıklama göster.
3. **`.gitignore`'u hedefli genişlet:** `.backups/`, `kurulum.log`, geçici paket desenleri (ör. `JARVIS-main-*.zip`). Geniş `*.zip` kullanma.
4. **Geliştirme kapısına yeniden başlatmaya dayanıklı deneme sınırı** + artan gecikme.
5. **Pencere öne getirme başarısızlığını görünür kıl**; mümkünse Windows API'sinin resmi yoluna indir.
6. **Kopyalanmış PDF okuyucuyu birleştir**; iki yolun aynı çıktıyı verdiğini test et.
7. **`main.py` ve `nx.js` bölünmesi.** `nx.js` için doğrudan ES modüllerine geçmeden önce **tarayıcı uyumluluğu kontrol edilmeli** — arayüz telefonda da açıldığı için eski mobil WebView/Safari hedefleri ES modüllerini desteklemeyebilir; gerekirse kademeli yedek plan uygulanmalı.
8. Dosya listesi önbelleği, görü önizlemesi akışı, takvimde hedefli render — **yalnızca performans**; güvenlik veya işlev sırasında değil.

---

## 5. Test ve donanım doğrulama sınırları

- **İnceleme anında** (7 Ekim 2026, statik okuma) hiçbir test çalıştırılamadı: bu ortamda kabuk (bash) yok, `python`/`pytest`/`unittest`/`node`/`git` çağrılamadı.
- **Sonradan, kullanıcı koşusuyla doğrulandı (aynı gün):** `python -m unittest discover -s tests -q` → **282 test, tamamı başarılı, 1 atlanan** (8,2 sn); ayrıca 6 webui JS sözdizimi kontrolü, 8 taklit-DOM davranış grubu ve 6 gerçek-Bridge smoke grubu geçti. Ayrıntı: Bölüm 6 çalışma kaydı.
- **Atlanan tek test** bilinen bir ortam kısıtıdır: Gemini Live içe aktarım testi, test ortamındaki sahte Google SDK'sında `Schema` bulunmadığı için çalışmaz; canlı ses oturumunu doğrulamaz.
- Dokümanların kendisi (`docs/BEKLEYEN_ISLER.md`) şunların gerçek cihazda **hâlâ** denenmediğini söylüyor: Windows mikrofonu ve "Hey Jarvis", pencere/kamera işlemleri, canlı model bağlantısı, Playwright tarayıcı, telefon akışı. Test koşusu bunları kapsamaz.
- Otomatik testlerin geçmesi donanım veya canlı servis doğrulamasının yerine geçmez.

---

## 6. Sonraki çalışma kaydı

| Tarih | Kayıt |
| --- | --- |
| 7 Ekim 2026 | Statik inceleme tamamlandı; bu rapor oluşturuldu. |
| 7 Ekim 2026 | **Uygulandı:** `.gitignore` hedefli genişletildi (`.backups/`, `kurulum.log`, `.pytest_cache/`, `*_gecici.zip`, `*.tmp.zip`) — geniş `*.zip` bilinçli olarak kullanılmadı. |
| 7 Ekim 2026 | **Uygulandı:** `modules/diagnostics.py` — güvenli maskeleme zinciri (URL kırpma → `privacy.redact(force=True)` → uzunluk sınırı → güvenli durum kodu) ve `user_message()` eklendi. |
| 7 Ekim 2026 | **Uygulandı:** `modules/developer.py` `unlock()` — hatalı denemeler `access.json`'da sayılıyor; 5. denemeden sonra artan gecikmeli kilit (üst sınır 300 sn). Yeniden başlatma sayacı sıfırlamıyor. |
| 7 Ekim 2026 | **Kısmen uygulandı:** `modules/nxapi.py` — pencere öne getirilemezse artık sessiz kalmıyor, günlüğe uyarı yazıyor. Arayüz bildirimi henüz yok. |
| 7 Ekim 2026 | **Düzeltildi (test bulgusu):** `modules/developer.py` `handle()` — "geliştirme modunu aç" komutu artık **kimlik doğrulanmışsa** alanı açıyor. Önce her durumda `None` dönüyordu; bu, `tests/test_developer.py` (yardımcı `enable()`) ve `tests/developer_smoke.py` ile çelişiyordu. Şifre kapısı hâlâ yalnızca arayüz düğmesinden açılır. |
| 7 Ekim 2026 | **Uygulandı (madde 6 — PDF birleştirme):** `modules/docs.py`'ya `read_pdf_isolated()` taşındı (proje genelinde tek PDF okuma yolu, ayrı süreç); `read_document` artık PDF'i bu yoldan okur. `modules/study.py` `_read_isolated` bu fonksiyona yönlendirir; geri-düşüş, sonsuz zincir kurmayan yerel `_read_pdf_inline` ile yapılır. `docs`/`kb`/`translate`/`study` artık aynı PDF kodunu kullanıyor. |
| 7 Ekim 2026 | **Hazır, çalıştırılmadı:** `scripts/parity.py` gerçek kurulum klasörüyle çalıştırılmayı bekliyor. |
| — | **Bekliyor:** Bölüm 4'teki 7 (`main.py`/`nx.js` bölünmesi — kullanıcı "güvenli yerde bırak" dediği için askıda) ve 8 (performans — ilk kalem aşağıda uygulandı). |
| 7 Ekim 2026 | **Son doğrulama:** PDF birleştirmesinden sonra `run_tests.bat` tekrar koşuldu — 282 test başarılı, tüm gruplar geçti. Bölüm 4'teki uygulanan tüm kalemler testle mühürlendi. |
| 7 Ekim 2026 | **İkinci teyit:** `run_tests.bat` bir kez daha koşuldu — 282 test başarılı (8,3 sn); `test_document_conversion` ve `test_study_*` dahil. PDF birleştirme sonrası şüphe tamamen kapandı. |
| 7 Ekim 2026 | **Uygulandı (madde 8, ilk kalem — dosya listesi önbelleği):** `modules/nxapi.py` `list_files` artık 45 sn TTL'li modül önbelleği kullanır: ilk istekte senkron tarama, bayat önbellekte eski liste anında döner ve arka planda yenileme başlar (`_background_refresh`); `force=True` senkron yeniler, `reset_file_cache()` testler için sıfırlama sağlar. `threading` modül içe aktarması düzeltildi. **Test koşusu görmedi** — bir sonraki `run_tests.bat` ile doğrulanmalı. |

> **Doğrulama (7 Ekim 2026, kullanıcı koşusu):** `python -m unittest discover -s tests -q` →
> **282 test, tamamı başarılı, 1 atlanan (8,2 sn)**. Ayrıca 6 webui JS sözdizimi kontrolü, 8 taklit-DOM
> davranış grubu ve 6 gerçek-Bridge smoke grubu geçti — aralarında `developer_smoke` (şifre, uygulama,
> geri alma) ve `test_cleanup_security` (maskeleme) de var. Bu, bu rapordaki `.gitignore`,
> `diagnostics.py`, `developer.py` (deneme sınırı + handle düzeltmesi) ve `nxapi.py` değişikliklerinin
> **testle doğrulandığı** anlamına gelir. Donanım/canlı servis doğrulaması hâlâ ayrıdır (Bölüm 5).
>
> **Son doğrulama (7 Ekim 2026, PDF birleştirmesi SONRASI koşu):** aynı paket `run_tests.bat` ile
> tekrar koşuldu → **282 test, tamamı başarılı, 1 atlanan (8,4 sn)**, "Tüm test grupları başarılı".
> Böylece `docs.py`/`study.py` PDF birleştirmesi (madde 6) da testle doğrulandı; bu rapordaki tüm
> uygulanan kalemler artık çalışma testlerinden geçmiş durumda.
>
> **İkinci teyit (7 Ekim 2026, PDF birleştirmesi sonrası bağımsız ikinci koşu):** `run_tests.bat`
> bir kez daha koşuldu → **282 test, tamamı başarılı, 1 atlanan (8,3 sn)**, tüm gruplar geçti.
> `test_document_conversion` ve `test_study_*` grupları da bu koşuda başarılı; PDF birleştirmesinin
> doğrulaması için var olan tek zamanda şüphe (koşu sırası) bu ikinci bağımsız koşıyla kapandı.

Bundan sonraki teknik değişikliklerde izlenecek iki temel kural:

1. Her özellik için **"kaynakta var"** ve **"kurulumda doğrulandı"** durumları ayrı tutulur.
2. Hata yakalamada hedef sayı değil, **açıklanabilirliktir**: kritik işlemlerde maskelenmiş ama işe yarar bir neden gösterilir.
