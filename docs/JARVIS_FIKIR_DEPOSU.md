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
