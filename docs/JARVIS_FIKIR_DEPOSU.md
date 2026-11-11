# Jarvis — Fikir Deposu

> **ROADMAP DEĞİLDİR — FİKİR / BACKLOG HAVUZUDUR.**
>
> Jarvis-v2'nin tek aktif uygulama yol haritası: [`Jarvis_Yol_Haritasi.md`](Jarvis_Yol_Haritasi.md)
>
> Buraya eklenen hiçbir fikir otomatik olarak roadmap'e veya uygulama işine dönüşmez. Yalnız Hamdi açıkça **“aktar”** dediğinde ana yol haritasına alınır.

Kaynak: Hamdi'nin `Jarvis - Fikir Deposu` belgesi. Repo kaydı, fikirleri tek aktif roadmap'den ayrı tutmak için oluşturuldu.

**Not:** Bu belgedeki `ADAY / DOĞRULANACAK / DOĞRULANDI / AKTARILDI / ELENDİ` etiketleri fikir değerlendirme durumudur; güncel kodda uygulanmış/tamamlanmış olma kanıtı değildir. Uygulama gerçeği ayrıca güncel `main` ve ana roadmap üzerinden doğrulanır.

## Amaç

İnternette görülen fikirleri hemen yol haritasına taşımadan önce burada toplamak, sadeleştirmek ve gerektiğinde doğrulamak.

## Çalışma kuralı

- Buraya eklenen hiçbir fikir otomatik olarak yol haritasına geçmez.
- Önce sadeleştirilir ve aday olarak tutulur.
- Gerekirse Jarvis kodu ve mevcut yol haritasıyla karşılaştırılır.
- Yalnız Hamdi açıkça **“aktar”** dediğinde yol haritasına alınır.

## Durumlar

`ADAY → DOĞRULANACAK → DOĞRULANDI → AKTARILDI`

Alternatif son durum: `ELENDİ`.

## Fikirleri okuma şekli

Her fikir şu yedi soruya cevap verir:

1. Hangi faza ait?
2. Bizde zaten ne var?
3. Yeni fikir ne ekliyor?
4. Bize ne kazandırıyor?
5. Ne zaman yapılmalı?
6. Ücretsiz yapılabiliyor mu?
7. Karar ne: `AL / UYARLA / ZATEN VAR / ELE`?

**Kural:** İyi fikir olması yetmez. Önce kaynak gerçekten okunur ve özellik kanıtlanır; araştırılmamış veya kanıtı doğrulanmamış hiçbir şey fikir olarak alınmaz. Sonra mevcut yol haritasındaki yeri kontrol edilir ve yalnız gerçek boşluk alınır. Ücretsiz yol doğrulanmamışsa `AL` kararı verilmez; zorunlu ücretli çözüm Hamdi istemedikçe elenir. Zamanı gelmemiş iş erkenden koda sokulmaz. Yol haritasına ancak Hamdi açıkça **“aktar”** dediğinde geçer.

---

## Geçerli ana fikir listesi — 10 madde

Bu belge için aktif ve doğrulanmış ana liste aşağıdaki 10 fikirdir. Yeni adaylar Hamdi açıkça onaylamadan bu listeye eklenmez.

1. **F-009** — Ücretsiz/kota-aware provider yönlendirme kuralları
2. **F-011** — Proaktif günlük briefing davranışı
3. **F-002** — Finance: analiz → işlem planı → risk → kullanıcı onayı
4. **F-005** — Gerçek hata → kalıcı regression/eval testi
5. **F-004** — Agent durma kuralları
6. **F-006** — Bağımsız salt-okunur kod reviewer
7. **F-010** — Güvenli PC bakım ve temizlik işi
8. **F-003** — Memory ≠ Task State ≠ Context
9. **F-007** — Motion Studio + ileri 3D film yeteneği
10. **F-008** — İş yapan çekirdek uzman ajan takımı

---

## F-009 — Ücretsiz/kota-aware provider yönlendirme kuralları

- **Faz:** 1 — Provider dayanıklılığı; mevcut `smart_router` / `failure_policy` üzerine kalite katmanı.
- **Bizde:** Provider routing, işe göre model seçimi, 429/cooldown/fallback ve fail-closed davranışı zaten var. Yeni gateway veya yüzlerce provider gerekmiyor.
- **Ne ekliyor:** quota-aware seçim; strict zero-cost routing; provenance/evidence tutan free-tier katalog; gerçekten ücretsiz ve hard-stop garantili rotayı ayrı güven bayrağıyla doğrulama.
- **Kazanç:** “free sanıp ücret çıkması”, ölü/bitmiş free tier'e yönelme ve kota bitmiş sağlayıcıda gereksiz tekrar azalır.
- **Ne zaman:** Faz 1 bakım/genişletme işi; Faz 0–4 sırasını bozmaz. Ayrı OmniRoute gateway kurulmaz.
- **Maliyet:** ÜCRETSİZ YOL DOĞRULANDI — OmniRoute MIT; inference kotası üçüncü taraf sağlayıcı hesap/uygunluğuna bağlıdır. Bilinmeyen model ücretsiz varsayılmaz.
- **Karar:** AL / UYARLA — quota-aware, strict zero-cost, evidence/catalog ve hard-stop guarantee fikirleri; mevcut Jarvis router korunur.
- **Durum:** DOĞRULANDI — tarihsel fikir durumu; uygulama gerçeği değildir.
- **Kaynak:** https://github.com/cheaper-inference/OmniRoute

## F-011 — Proaktif günlük briefing davranışı

- **Faz:** 2 — Cron/RuntimeEvent/fanout üzerine kullanıcıya düzenli operasyon özeti.
- **Bizde:** Zamanlama, RuntimeEvent, bildirim/fanout, GoalState ve worker sonuçları var.
- **Ne ekliyor:** Belirlenen saatte tamamlanan işleri, bekleyen onayları, hata/engelleri, geciken/açık işleri ve önemli değişiklikleri tek kısa eyleme dönük briefing halinde sunmak; gerekirse en önemli sonraki adımı önermek. Yeni görev motoru kurmaz.
- **Kazanç:** Kullanıcı yalnız sorunca durum anlatan değil, gerektiğinde proaktif özet veren Jarvis.
- **Ne zaman:** Scheduler/RuntimeEvent akışı sağlamlaştıktan sonra.
- **Maliyet:** ÜCRETSİZ UYARLANABİLİR — mevcut altyapıyla; zorunlu ücretli servis yok.
- **Karar:** AL / UYARLA — günlük briefing davranışı; ayrı CEO-GPT/CRM/dashboard mimarisi değil.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak:** https://moritz.ceogpt.de/unternehmen/#system

## F-002 — Finance: analiz → işlem planı → risk → kullanıcı onayı

- **Faz:** 3/4 Finance; salt-okuma Finance sonrasında.
- **Bizde:** Salt-okuma piyasa/varlık analizi ve FinanceWorker yönü var.
- **Ne ekliyor:** giriş/stop/hedef planı, pozisyon boyutu, PASS/BLOCK risk kontrolü ve açık kullanıcı onayı. Broker/emir yok.
- **Kazanç:** yalnız yorum değil, disiplinli karar desteği; gerçek para hareketi ayrı kalır.
- **Ne zaman:** Etap 1 Faz 3/4 ile; Etap 2 salt-okuma Finance sağlamlaştıktan sonra. Broker/paper/live emir ayrı karar.
- **Maliyet:** ÜCRETSİZ YOL DOĞRULANDI — kaynak repo MIT; temel public veri için kayıt/API anahtarı gerekmiyor. Broker kapsam dışı.
- **Karar:** UYARLA.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak:** https://github.com/Jakeschincariol/day-trader-skill
- **Önemli kaynak:** https://github.com/Jakeschincariol/day-trader-skill/blob/main/trader-timemachine/SKILL.md

## F-005 — Gerçek hata → kalıcı regression/eval testi

- **Faz:** 5 — Güvenilirlik ve gözlem.
- **Bizde:** Validation, testler, CI ve değerlendirme fazı var.
- **Ne ekliyor:** Gerçek kullanımda çıkan önemli hatayı kalıcı test senaryosuna çevirmek; yalnız final cevap değil doğru worker/tool, argüman, izin kapısı, yasak adım ve kaynak kullanımını da kontrol etmek.
- **Kazanç:** Aynı hatanın geri gelme olasılığı azalır; kalite ölçülebilir olur.
- **Ne zaman:** Faz 5.
- **Maliyet:** TAMAMEN ÜCRETSİZ.
- **Karar:** AL.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak notu:** AI Agents sunumu + AI App Stack blueprint.

## F-004 — Agent durma kuralları

- **Faz:** 6 — Sandbox, skill, kod ajanı.
- **Bizde:** Bazı işlerde adım/tur sınırları var.
- **Ne ekliyor:** Ortak durma nedenleri: hedef tamamlandı, maksimum adım, süre doldu, bütçe/token sınırı, kullanıcı onayı gerekiyor, kurtarılamaz hata.
- **Kazanç:** Sonsuz döngü ve aynı hatayı tekrar tekrar deneme azalır; Jarvis neden durduğunu bilir ve bildirir.
- **Ne zaman:** Faz 6.
- **Maliyet:** TAMAMEN ÜCRETSİZ — runtime sınırı/reason-code sözleşmesi.
- **Karar:** UYARLA.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak notu:** AI Agents sunumu + AI Assistant Setup Guide.

## F-006 — Bağımsız salt-okunur kod reviewer

- **Faz:** 6 — Sandbox, skill, kod ajanı.
- **Bizde:** Düşen test → kod → full validation → diff/CI kontrolü var.
- **Ne ekliyor:** Kodu yazan ajan dışında, kodu değiştiremeyen ayrı reviewer; correctness, security, test, hata yönetimi ve maintainability bulgularını kanıtla verir. Edit sonrası ilgili doğrulama hook'u çalışabilir.
- **Kazanç:** Ajanın kendi yazdığını kendi onaylaması riski azalır.
- **Ne zaman:** Faz 6, kod ajanıyla birlikte.
- **Maliyet:** TAMAMEN ÜCRETSİZ UYARLANABİLİR.
- **Karar:** AL / UYARLA.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak notu:** Claude Code starter kit + AI Agents sunumu.

## F-010 — Güvenli PC bakım ve temizlik işi

- **Faz:** 9 — Tam PC kontrolü; bakım/temizlik alt yeteneği.
- **Bizde:** PC kontrolü ve dosya/klasör işlemleri hedefte var; risk sınıflı bakım akışı ayrı doğrulanmış yetenek değil.
- **Ne ekliyor:** Windows geçici dosyaları, tarayıcı/thumbnail/Windows Update cache, Recent kısayolları ve Recycle Bin gibi alanları tarama; silmeden önce boyut/risk raporu; seçmeli temizlik; kilitli dosyayı atlama; Documents/Desktop/Downloads ve program kurulum klasörlerini varsayılan kapsam dışı bırakma; gerçek silme öncesi kullanıcı onayı.
- **Kazanç:** bakım işi görünür dry-run/risk/onay kapısıyla Jarvis'e gelir.
- **Ne zaman:** Faz 9; önce salt-okuma tarama/rapor, sonra onaylı temizlik.
- **Maliyet:** TAMAMEN ÜCRETSİZ — ATSMATRIX-PC-CLEANER MIT; Python/Windows yerel araçlarıyla uyarlanabilir.
- **Karar:** AL / UYARLA — bağımsız cleaner kopyalanmaz; davranış PC worker'a uyarlanır.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak:** https://github.com/anyel1to/ATSMATRIX-PC-CLEANER

## F-003 — Memory ≠ Task State ≠ Context

- **Faz:** 11 — Profiller, hafıza, context; çekirdek kuralı Faz 0 ile ilişkili.
- **Bizde:** Hafızanın GoalState yerine geçmemesi fikri roadmap'de var.
- **Ne ekliyor:** Memory = uzun vadeli bilgi; Task State = mevcut işin kaldığı yer; Context = modele o anda verilen çalışma bağlamı ayrımını açıklaştırır.
- **Kazanç:** Uzun işin kaldığı yer kaybolmaz, geçici bilgi hafızayı kirletmez, hafıza yürütme authority'sine dönüşmez.
- **Ne zaman:** Kural şimdi korunur; ayrıntılı uygulama/test Faz 11.
- **Maliyet:** TAMAMEN ÜCRETSİZ.
- **Karar:** UYARLA.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak notu:** AI Agents sunumu.

## F-007 — Motion Studio + ileri 3D film yeteneği

- **Faz:** 12 — Medya/video.
- **Bizde:** Yerel sahneli video, görsel + altyazı + ses montajı ve FFmpeg tabanı var.
- **Ne ekliyor:** İş türüne göre Remotion / GSAP / SVG / Lottie / Three.js / Canvas seçimi; frame-exact ve tekrar üretilebilir render; render öncesi/sonrası görsel QC; Whisper zamanlama; teknik/bilimsel anlatım için Three.js + Blender alt yeteneği.
- **3D alt yetenek:** Ayrı büyük sistem değil; Motion Studio içinde makine/anatomi/molekül/teknik anlatım, gerçek/lisanslı asset, exploded view/cut-away, frame doğrulama ve kanıt raporu.
- **Kazanç:** Mevcut video alanını ikinci kez kurmadan profesyonel ve doğrulanabilir üretim hattı.
- **Ne zaman:** Faz 0–6'yı bölmeden medya alanı açıldığında.
- **Maliyet:** ÜCRETSİZ YOL DOĞRULANDI — MIT kaynaklar; Remotion, GSAP/HTML, SVG, Lottie, Three.js, Canvas, Whisper, FFmpeg, Chromium/Puppeteer, Blender. After Effects zorunlu değil. Asset lisansı/atıf korunur.
- **Karar:** AL / UYARLA — Motion Studio ana madde, 3D Film Studio alt yetenek.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak:** https://github.com/megomaged/claude-motion-studio
- **3D kaynak:** https://github.com/megomaged/claude-3d-film-studio

## F-008 — İş yapan çekirdek uzman ajan takımı

- **Faz:** 6–7 — Sandbox/skill/kod ajanı ve sub-agent/Kanban; mobil uzman Faz 9–12 telefon/Android işleriyle.
- **Bizde:** Worker yapısı, kod ajanı yönü, test/CI akışı ve bazı uzman yollar var. Ama hedef yüzlerce rol değil, doğrudan iş teslim eden küçük ekip.
- **Ne ekliyor:** 10 çekirdek rol: Kod Ajanı, Code Reviewer, Codebase Explorer, Incident/SRE Ajanı, Voice AI Ajanı, Search/RAG Ajanı, Mobile/Android Ajanı, Build/CI Fixer, Security Reviewer, E2E/Acceptance Runner.
- **Kazanç:** Genel persona yığını yerine gerçek görev alanı olan küçük uzman ekip; mevcut worker/izin/GoalState mimarisi korunur. Doc Updater ve Refactor Cleaner sürekli ajan değil, gerektiğinde yardımcı rol.
- **Kod ajanı çalışma kuralı:** Yeni kod son seçenek. Önce gerçekten gerekli mi, projede/reuse var mı, stdlib/platform/native/kurulu paket çözüyor mu, daha küçük diff olur mu bakılır; sonra en az çalışan kod yazılır. Güvenlik, veri kaybı önleme, hata yönetimi ve erişilebilirlik azaltılmaz.
- **Ek kalite kuralları:** Testi geçirmek için testi değiştirme; yeni kütüphane/framework'ü repoda doğrula; ortam sorununu ürün koduna yamalama; aynı başarısız yaklaşımı körlemesine tekrarlama.
- **Ajan izolasyonu:** Mümkün olduğunda ayrı terminal/workspace; başka ajanın geçici dosyasına/aktif değişikliğine karışma; ortak repo gerekiyorsa sahiplik sınırı açık.
- **Kanıtlı teslim:** Değişiklik, doğrulama ve sonuç tek standart paketle verilir; uygun olduğunda test/validation/CI, ekran görüntüsü/artefakt, değişen dosyalar ve kalan risk birlikte sunulur.
- **Temizlik/audit:** Ölü/fazla kod delete/native/stdlib/reuse/yagni/shrink türlerinde raporlanabilir; otomatik silinmez. Dinamik import/string yol/script/CI/harici kullanım aranır; emin silme ayrı PR ve tam validation/build-test-lint/gerçek kabul sonrası merge.
- **Ne zaman:** Kod/ajan Faz 6–7; Incident/SRE Faz 5; Voice/Search ilgili fazlarda; Mobile/Android telefon işi aktifleşince. Faz 0–4'ü bölmez.
- **Maliyet:** TAMAMEN ÜCRETSİZ UYARLANABİLİR — agency-agents MIT; affaan-m/ECC MIT; Ponytail rehberi açık kaynak/MIT olarak not edilmiş. Ücretli model/servis zorunlu değil; Jarvis'in ücretsiz/yerel sağlayıcılarıyla uyarlanabilir.
- **Karar:** AL / UYARLA — yalnız iş yapan çekirdek roller; yüzlerce genel/pazarlama/persona ajanı değil.
- **Durum:** DOĞRULANDI — fikir değerlendirme durumu.
- **Kaynak:** https://github.com/msitarzewski/agency-agents
- **Ek kaynak:** https://github.com/affaan-m/ECC
- **Ponytail kaynak/rehber:** kullanıcı tarafından sağlanan “Ponytail ile gereksiz kodu bul” PDF; resmi kaynak olarak DietrichGebert/ponytail not edilmiş.

---

## Kaynak değerlendirme eki — VoiceStudio (11 Kasım 2026)

Hamdi'nin “alınabilecek olanları doğrula, gerçekten değerliyse fikir dosyasına yaz” isteğiyle kaydedildi. **Aktif 10 maddelik ana liste değiştirilmedi; bu ek uygulama emri veya roadmap aktarımı değildir.** Aşağıdaki `DOĞRULANDI` ifadesi yalnız belirtilen kaynak davranışını kapsar, gerçek Türkçe ses/Windows performansı veya Jarvis entegrasyonu anlamına gelmez.

İncelenen kaynak: [`debpalash/VoiceStudio@c85a866f19dfddd6a31c50f88ee2e08e644c77ea`](https://github.com/debpalash/VoiceStudio/tree/c85a866f19dfddd6a31c50f88ee2e08e644c77ea). Jarvis karşılaştırma tabanı: `main@4928f78`; ses temeli `voice_core.py`, `voice_runtime.py`, `voice_offline.py`. Bu üç dosyanın `1a96749` sonrasındaki main farkında değişiklik görülmedi.

### VS-01 — Ses motorunun efektif cihazı ve çalışamama nedenini gösterme

- **Faz:** Voice Core cihaz/performans gözlemi; mevcut ses rollout'u ve yük kabulüyle birlikte değerlendirilecek.
- **Bizde:** Seçili ses/model kimliği, dosya/Piper executable kontrolü, bounded ses kuyruğu, adapter hatası ve insan duyumlu ses probe'u var. Ayrı ses kuyruğu veya yeni model yönlendiricisi gerekmiyor.
- **Ne ekliyor:** Motorun yalnız model dosyası varlığını değil, bildirilen/doğrulanan çalışma yolunu (`accelerated`, `cpu_fallback`, `cpu_only`, `unavailable`, `unknown`) ve nedenini göstermesi. “GPU bulundu” ile “bu motor GPU'da çalışabilir” ayrı. Jarvis'te bilgi ölçülmediyse `unknown`; CPU'ya düşüş görünür olmalı, fakat ses kimliği kendiliğinden değişmemeli.
- **Kazanç:** Ağır yerel modelle birlikte ses yavaşladığında gerçek cihaz/bellek/uygunluk nedenini ayırma; kurulu görünen fakat kullanılamayan motoru hazır göstermeme.
- **Ne zaman:** Mevcut ses adapter'ı ve durum ekranı üzerinde; ayrı kontrol paneli, worker veya Scheduler açmadan. Gerçek Windows yük ölçümünü tamamlandı saydırmaz.
- **Ücretsiz yapılabilir mi:** Evet, mevcut adapter durum sözleşmesi ve platform kontrolleriyle tasarım uyarlanabilir; zorunlu ücretli servis veya VoiceStudio kurulumu yok. VoiceStudio AGPL kodu kopyalanmadı. Model/GPU doğrulaması ayrıca ölçülecek.
- **Karar:** **UYARLA.** Sadece cihaz/uygunluk görünürlüğü; bütün VoiceStudio model yöneticisini almak veya kurulu ses hattını değiştirmek değil.
- **Durum:** **DOĞRULANDI — kaynakta saf durum çözümleme davranışı/testleri.** Gerçek donanımda tespit doğruluğu henüz ölçülmedi.
- **Kanıt:** [`engine_routing.py`](https://github.com/debpalash/VoiceStudio/blob/c85a866f19dfddd6a31c50f88ee2e08e644c77ea/backend/services/engine_routing.py), [`device_caps.py`](https://github.com/debpalash/VoiceStudio/blob/c85a866f19dfddd6a31c50f88ee2e08e644c77ea/backend/core/device_caps.py), [`test_engine_routing.py`](https://github.com/debpalash/VoiceStudio/blob/c85a866f19dfddd6a31c50f88ee2e08e644c77ea/tests/test_engine_routing.py). Fake host/engine matrisi ve event loop'u bekletmeyen async çözümleme testleri çalıştırıldı; fiziksel GPU çıkarımı yapılmadı.

### VS-02 — İsteğe bağlı yerel TTS/STT sağlayıcı sınırı ve talep üzerine ses akışı

- **Faz:** Voice Core adapter genişlemesi; gerçekten ikinci motor veya ayrı yerel servis ihtiyacı oluştuğunda.
- **Bizde:** Tek VoiceCoordinator, Piper adapter'ı, cümle parçalama ve generation/iptal çiti var. Bu özellikler yeniden yapılmayacak. Mevcut ses sahibi ve profile voice/rate otoritesi korunacak.
- **Ne ekliyor:** İleride farklı yerel motorun aynı adapter sınırına bağlanabilmesi için sabit motor/ses kimlikli speech-provider sözleşmesi; PCM delta/terminal hata, bağlantı kapanınca sonraki cümlelerin üretilmemesi. TTS sağlayıcı servisi Jarvis'in Brain/Core/Scheduler'ı veya ikinci player'ı olmaz.
- **Kazanç:** Yeni motorun ağır bağımlılıklarını Jarvis sürecinden ayırabilme, bütün metin yerine hazır parçayı sunabilme, terk edilmiş yanıtın sonraki cümlelerine gereksiz üretim yapmama. Kazanç motor/ölçüme bağlıdır; mevcut Piper'dan hızlı olduğu iddia edilmez.
- **Ne zaman:** Mevcut ses dikey akışı tamamlandıktan sonra ve somut motor ihtiyacıyla. Kullanılacak ikinci motor yokken yeni servis/protokol katmanı kurulmaz; ilk bağlantı koşullu genişleme fikridir.
- **Ücretsiz yapılabilir mi:** Protokol/tasarım mevcut Jarvis adapter'larıyla ücretsiz uyarlanabilir; OpenAI-compatible ses API'si OpenAI hesabı/ücretli servisi gerektirmez. Belirli modelin kullanım lisansı ayrıca doğrulanır. VoiceStudio uygulamasını dağıtmak/kod kopyalamak ayrı AGPL değerlendirmesidir; bu kayıt onu onaylamaz.
- **Karar:** **UYARLA — ihtiyaç olduğunda.** Bütün VoiceStudio'yu alma, otomatik model indirme veya mevcut ses motorunu değiştirme kararı yok.
- **Durum:** **DOĞRULANDI — protokol kaynakta mevcut, streaming helper davranışı izole olarak çalıştırıldı.** Tam HTTP/ASR/model/hoparlör denemesi yapılmadı.
- **Kanıt:** [`agentic-voice.md`](https://github.com/debpalash/VoiceStudio/blob/c85a866f19dfddd6a31c50f88ee2e08e644c77ea/docs/agentic-voice.md), [`openai_compat.py`](https://github.com/debpalash/VoiceStudio/blob/c85a866f19dfddd6a31c50f88ee2e08e644c77ea/backend/api/routers/openai_compat.py). Kaynak `_stream_speech_pcm` ve yardımcıları AST ile izole edilip sahte renderer ile çalıştırıldı: ilk PCM sonraki cümle üretiminden önce geldi; generator kapanınca sonraki cümleler üretilmedi; SSE sıra/terminal olayları doğrulandı; kısmi üretim hatası başarılı `done` yerine hata verdi. Bu test devam eden native inference'ın anında durmasını kanıtlamaz.

### Alınmayan parçalar ve kanıt sınırı

- **VoiceStudio bütünü:** Şimdilik **ELE / ENTEGRE ETME**. Mevcut Jarvis'e ek desktop uygulaması, ayrı profil/model yöneticisi ve büyük ML bağımlılıkları için kanıtlanmış net kazanç yok. Karar kaynak incelemesine dayanır, uygulamanın genel kalitesine dair hüküm değildir.
- **AEC'yi hazır çözüm saymak:** **ELE.** [`aec.py`](https://github.com/debpalash/VoiceStudio/blob/c85a866f19dfddd6a31c50f88ee2e08e644c77ea/backend/services/aec.py) NLMS+double-talk içeriyor ve kendisi production-grade DSP olmadığını söylüyor. Ek sentetik deney: 16 kHz/20 ms frame, 4 sn echo-only sinyal, gain .45; son 600 ms'de 5 ms yankı gecikmesi için 9,27 dB, 50 ms için -0,16 dB azaltma. Oda/mikrofon/gerçek konuşma testi değildir. Jarvis full-duplex/AEC kabulünü kapatmaz.
- **Türkçe motorları ana ses yapmak:** **DOĞRULANACAK, AL kararı yok.** MOSS-TTS-Nano/VoxCPM2 belgelerinde Türkçe var; kendi PC'mizde kalite, ilk ses gecikmesi, yük ve exact ağırlık lisansı doğrulanmadı. Kaynak dil listesi tek başına ses kalitesi kanıtı değildir; ana fikir listesine eklenmedi.
- **Lisans ayrımı:** [`LICENSE-NOTICE.md`](https://github.com/debpalash/VoiceStudio/blob/c85a866f19dfddd6a31c50f88ee2e08e644c77ea/LICENSE-NOTICE.md) uygulama AGPL-3.0-only, bundled kod ve indirilen ağırlıkların ayrı koşullarını açıklıyor. Varsayılan OmniVoice ağırlıkları için non-commercial koşullar belirtiliyor. Ücretsiz tasarım uyarlaması, bütün modeller için sınırsız kullanım hakkı demek değildir.
- **Çalıştırılan upstream test kapsamı:** İzole ortamda `test_aec.py` ve `test_engine_routing.py` seçiminin saf NumPy/host-matrix kısmı: **47 passed**. Torch/model-loader bağımlı **10 test seçime alınmadı**. İlk geniş koşu ortamın yazılamayan varsayılan data dizini ve eksik Torch nedeniyle 10 hata verdi; bu durum ürün hatası sayılmadı. Son koşu geçici data dizini ve açık test seçimiyle yapıldı. Ek streaming kontrolleri yukarıda belirtilen kaynak fonksiyonlarıyla yapıldı; bütün upstream suite veya çalışan API kabulü değildir.

**Gelecek uygulama koşulu:** Önce mevcut Jarvis'te gerçek boşluk yeniden kontrol edilir. Uyarlama yapılırsa aynı kullanıcı yeteneğinin mevcut sahibi genişletilir; ikinci ses kuyruğu/konuşmacı/ayar otoritesi eklenmez. Eski yolun emekliliği, owner/voice kimliği, iptal ve gerçek oynatma kabulü birlikte ele alınır. Bu ek nedeniyle aktif yol haritası değiştirilmedi.
