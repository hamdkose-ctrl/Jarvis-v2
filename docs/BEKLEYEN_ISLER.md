# Historical redirect — BEKLEYEN_ISLER

> **AKTİF İŞ LİSTESİ / ROADMAP DEĞİLDİR.**
>
> Güncel iş sırası ve yapılacaklar için tek authority: [`Jarvis_Yol_Haritasi.md`](Jarvis_Yol_Haritasi.md)
>
> Bu dosyanın tarihsel içeriği arşive taşındı: [`archive/roadmaps/BEKLEYEN_ISLER.md`](archive/roadmaps/BEKLEYEN_ISLER.md)

Bu yol yalnız eski belge bağlantılarının kırılmaması için tutulur. Buradaki eski kayıtlar yeni görev açmak için kullanılmaz.

### BRAIN-03 dilim4 — mevcut branch, kapanış açık

`gpt/brain-03-output-diagnose`: çıktı/teşhis model→Core→domain hattı ve eski iki doğal-dil kalıp sahibinin kaldırılması uygulanıyor. Yeni testler model wiring, oturum artifact kimliği, iptal ve gerçek Word kayıt adapterını kapsar; mock başarı gerçek model semantik kabulü değildir. Ücretsiz üretim rotası ön denetimi yalnız ollama adayı buldu (gemini rota dışı, groq/cloudflare ücretsiz hesap teyitsiz); canlı holdout çalışmadı ve kapı gevşetilmedi. Yerel tam validation exit 0 (5.204 Python testi: 5.203 başarılı, 1 platform skip; tüm JS/smoke ve 47 son stability testi başarılı); exact-head Windows CI ve aynı SHA PC watcher kapanış için açık kalır. Kullanıcının ayrı gönderim/PR onayı olmadan push veya PR açılmadı. Dilim5/BRAIN-04'e geçildiği iddia edilmez.

Dilim4 gerçek model kabulü Windows hesabında çalıştırılmak üzere aynı PR'ın CI bootstrap'ına bağlandı. Scriptin normal çağrısı plan gösterir; `--run` üretim rotasında 20 sentetik holdout isteğidir. Rapor artifact'ı commit ve corpus hash'i taşır. Self-hosted runner hesabında etkin Jarvis profili/uygun rota bulunmazsa exit2 ve unmeasured sonucu açık blocker'dır; CI PASS veya mocked wiring ile kapatılamaz.

Gerçek Windows kullanıcı koşusu da unmeasured döndü: Groq FREE_TIER_EVIDENCE_MISSING. Kullanıcı Groq hesabının Free olduğunu ve ödeme yöntemi eklemediğini açıkça doğruladı. Opt-in `confirm_groq_free_plan.py` mevcut per-owner/model evidence kaydını kaynaklı olarak tamamlar; güncel kaynak bilgisi en geç2026-11-15'e kadardır, kota miktarı icat edilmez. Bu işlem gerçek kullanıcının oturumunda yapılmalı; CI servis hesabına profil/anahtar aktarılmaz. Yeni semantik sonuç henüz alınmadı.

Groq kurulum/pacing doğrulaması: 65 ilgili test ve tam yerel validation geçti (5.227 Python testi, 1 platform skip; tüm JS/smoke ve son47 kararlılık testi başarılı). Ruff F821/F822/F823 ve roadmap kontrolleri temiz. Yeni sürümün gerçek Windows/semantik sonucu henüz yoktur.

2a09914 gerçek Windows sonucu: Free kayıt başarılı, ilk Groq HTTP400; 1 istek/0 yanıt, semantik ölçülmedi. Kaynakta süre/token parametre karışıklığı düzeltildi; HTTP JSON gövdesini denetleyen regresyon testinde hata önce üretildi. Yeni Windows/model sonucu henüz yok.

Token/süre düzeltmesi: 41 ilgili test ve tam validation başarılı (5.228 Python testi, 1 platform skip; tüm JS/smoke, son47 test). Ruff ve roadmap kontrolleri temiz. HTTP400 giderildiği gerçek sağlayıcı yanıtıyla henüz doğrulanmadı.

PC deneme tekrarını azaltma: scripts/Run-BrainCheck.ps1 tek seferlik kurulum ve masaüstü Quick/Full kısayolları sağlar. Quick tek çağrı; Full20 örnek, ilk bozuk/yanıtsız yanıt sonrası tekrar yok. Sonuçlar commit/korpus/kapsam ile kalıcı arşivlenir. Mevcut kullanıcı Free kaydı değiştirilmez. Yeni PowerShell çalıştırması bu Linux ortamında doğrulanmadı; gerçek PC/model sonucu açık kalır.

Quick/Full operatör paketi doğrulaması: 42 ilgili runner/model/index testi başarılı; Ruff F821/F822/F823, diff ve iki roadmap kontrolü temiz. Uygulama modülleri değişmedi; bu paket için yerel tam validation tekrarlanmadı. Yeni SHA Windows CI/watcher ve PowerShell kısayol kabulü bekleniyor.

Kullanıcı ad36ca1 tam PC raporunu paylaştı:20 gerçek yanıt/20 geçersiz proposal; başarısızlık şema/sürüm katmanında, anlam başarısı ayrıştırılamadı. 66fcd34 Quick/Full kısayol kurulumu Windows kullanıcısında başarılı. Yeni model koşusu henüz yok. Prompt çıktı sözleşmesi açık JSON schema ile sunuldu ve metinsiz yanıt şekli tanısı eklendi; parser kabul koşulları aynı kaldı. Yeni Quick yanıtı gerekli; toplu test tekrarlanmadı.

Yanıt sözleşmesi paketi:39 ilgili test ve tam yerel validation başarılı (5.233 Python testi,1 platform skip;tüm JS/smoke ve son47 test). Ruff temiz. Son prompt alan açıklaması sonrası ilgili39 test yeniden geçti. Windows/model kabulü yeni Quick raporuna bağlıdır.
