# Hoca modu (AGENTS.md alan notları)

Plan: `raporlar/hoca-modu-plan-2026-10-18.md` (Hamdi 2026-10-18: seçenek B; önce A kısmı küçük PR'larla, altyazı ayrı PR). Hiçbiri PC'de denenmedi.

## Hoca çalışma alanı — tasarım kararı, 25 Ekim 2026

Hamdi'nin kararı: mevcut "Çalışma" sayfası (`PAGES.study`, webui/nx.js — kaynaklar/kitap yükleme, çıkmış soru analizi, quiz, yanlışlarım, deneme, plan, ilerleme, konuya göre otomatik Vikipedi+YouTube paneli) ve mevcut Hoca sekmesi (ders/adım anlatımı, kontrol sorusu, zayıf konu tekrarı) **tek bir "Hoca" ekranında birleşiyor**. Hiçbir mevcut özellik atılmıyor; "Çalışma" adı ve sayfası kalkıyor, yerine "Hoca" geçiyor. Dosyalar ekranından tamamen bağımsız: kendi kitap/çıkmış soru/ders dosyası deposu var, genel dosyalarla hiç karışmaz.

Üstüne eklenen (Hamdi'nin ilk tasarımından, PC ekran rehberliği/adım replay maddesi çıkarılmış hâliyle):
- Ders/dönem/hedef yapısı: kitap atılsa da atılmasa da herhangi bir öğrenci (üniversite/LGS/vb.) bir konuyla çalışabilsin.
- Syllabus/not'tan ödev-sınav-deadline çıkarma; takvim ve görev planı; büyük ödevi küçük parçalara bölme.
- GPA/puan projeksiyonu; "kaldığım yerden devam" (oturum hafızası).
- Takvim/görev değişiklikleri onaylı yapılır; mevcut `docs/agents/mail-takvim.md` izin/onay hattı kullanılır, Hoca'ya özel ayrı bir onay kuralı yazılmaz.
- Ekran rehberliği ve öğrenilen adım replay'i **yok** — bu PC Worker'ın kapsamı (bkz. `docs/agents/dosya-belge.md`'deki PC Worker ayrımı), Hoca'da hiç olmayacak.

Netleşen tasarım ayrıntıları:
- **Ders vs konu:** "ders" geniş kapsam (ör. "Matematik"); "konu" (ör. "türev") bunun altında, mevcut `modules/hoca.py`'nin ders planı/adım yapısı. LGS'de de aynı ayrım.
- **Sınav takibi isteğe bağlı ve otomatik:** soru sorulmaz; derse bir "çıkmış soru" kaynağı eklenince kendiliğinden açılır. Proje bazlı bir üniversite dersinde hiç açılmaz.
- **Seviye** (LGS/lise/üniversite/genel) ders eklenirken bir kez sorulur; kitap yoksa anlatım bu seviyeye göre ayarlanır.
- **Oturum hafızası:** anlaşılmayan nokta + çözülen soru + sonraki adım. Tekrar aralığı (1-3-7 gün, `modules/studyexam.py`) değişmedi.
- **Web araştırması:** Vikipedi+YouTube paneli (`modules/studymedia.py`) aynen kalıyor. Genel web araştırması için Tavily API kullanılacak (tek kullanıcılı kurulum olduğu için tek bir paylaşılan anahtar yeter, kullanıcı başına ayrı anahtar gerekmez) — ücretsiz, aylık 1000 sorgu, kartsız; Google Custom Search yeni müşteriye kapandığı ve Brave'in ücretsiz katmanı Şubat 2026'da kalktığı için tercih edilmedi. Gerçek sorgu kalitesi Hamdi'nin PC'sinde denenecek (bulut ortamından `api.tavily.com`'a erişim yok).

Uygulama sırası (rehberlik maddesi çıkarılmış hâliyle):
1. Domain sözleşmesi: ders, oturum, kaynak, hedef, ilerleme, ödev/deadline
2. Salt-okunur kaynak + ders anlatımı (kitap yoksa model+web, seviyeye göre)
3. Oturum hafızası, soru/alıştırma/tekrar planı
4. Dönem haritası, takvim, görev, GPA
5. Onaylı takvim/görev değişiklikleri (mail-takvim.md izin hattı)
6. Sesli Hoca modu

## Domain sözleşmesi v1 — 25 Ekim 2026

- `modules/hoca_workspace.py`: 1. adım, yalnız veri modeli. Model çağrısı, UI, dönem haritası/takvim hesaplaması yok. `profile.data["hoca_courses"]` içinde ders listesi tutar; mevcut `modules/hoca.py`'nin `profile.data["hoca"]` (aktif ders/adım) anahtarına dokunmaz, ikisi sonraki adımda bağlanacak.
- `add_course(profile, name, level)`: ders ekler (`LEVELS`: lgs/lise/üniversite/genel, bilinmeyen değer "genel"e düşer). Aynı adla (büyük/küçük harf duyarsız) ikinci ders reddedilir, boş ad reddedilir. `exam_enabled` başta her zaman `False`.
- `add_source(profile, course_id, source_type, ref, label)`: `SOURCE_TYPES` (kitap/pdf/video/web/çıkmış_soru) dışı tür reddedilir. `çıkmış_soru` eklenince `exam_enabled` otomatik `True` olur — ayrıca sorulmaz, geri alınmaz (bu adımda kaldırma yok).
- `add_assignment`/`list_assignments`: ders başına ödev/deadline kaydı; `due` şimdilik serbest metin (takvime bağlanması 4. adımda), bilinmeyen `origin` "manual"a düşer.
- `record_session`/`get_session`: konu başına oturum hafızası — `unclear`/`solved` listeye eklenir (en çok 20, eski düşer), `next_step` üzerine yazılır (tek güncel durum). Tekrar aralığı mantığına dokunmadı.
- Test: `tests/test_hoca_workspace.py` (18 test, model/ağ gerektirmez). Motora/UI'a bağlanmadı, gerçek PC'de denenmedi.

## Salt-okunur kaynak v1 — modules/hoca.py bağlantısı, 25 Ekim 2026

- Hamdi'nin kararı (C): hem `modules/hoca.py` (adım-adım) hem `modules/study.py:lesson()` (uzun anlatım) motoru kalıyor; kullanıcı mod seçiyor. Bu PR yalnız `hoca.py` tarafını `hoca_workspace`'e bağladı — `study.py:lesson()`'ın per-ders kaynağa bağlanması ayrı, yakın bir sonraki iş (bkz. aşağıdaki "Sırada" notu).
- Eski genel kaynak deposu (`study.py`'nin `docs` listesi) **taşınmadı**: Hamdi'nin kararı, eski kaynaklarda hangi derse ait olduğu hiç kayıtlı olmadığı (tahmin edilemez) ve önemli bir veri olmadığı için taşıma/migrasyon yapılmayacak. Yeni Hoca ekranı sıfırdan, kendi per-ders deposuyla (`hoca_workspace.py`) başlıyor; eski depo olduğu yerde duruyor, kullanılmıyor.
- `hoca_workspace.read_source_text(ref)`: ikinci bir dosya okuyucu kurulmadı, mevcut `modules/file_worker.extract()` (salt-okunur, `file_ops._roots()` izin kapsamı) yeniden kullanıldı. Okunamayan/izin dışı/desteklenmeyen dosya sessizce boş dönmez, `HocaWorkspaceError` fırlatır.
- `hoca_workspace.course_context(course)`: dersin `kitap`/`pdf` türündeki kaynaklarını birleştirip `modules/hoca.py:start()`'ın beklediği `{"text","label","full"}` biçiminde döner; okunamayan tek tek kaynak sessizce atlanır (`warnings`), hiçbiri okunamazsa `None` (kaynaksız yola düşülür). Video (`hoca_video.py`, resmî YouTube yolu) ve web (henüz yok, Tavily/Vikipedi paneli ayrı) bu fonksiyona dahil değil.
- `hoca.start(profile, topic, level="", source=None, course_id=None)`: `course_id` verilirse ve `level`/`source` açıkça verilmemişse, dersin seviyesi ve `course_context` kendiliğinden kullanılır. Açıkça verilen `level`/`source` her zaman önceliklidir (üzerine yazılmaz). Bilinmeyen `course_id` `HocaError` olarak patlar.
- Test: `tests/test_hoca_workspace.py`'de `SourceReadingTests` (6 test, izole tmp klasör + `file_worker.allowed_roots` yaması), `tests/test_hoca.py`'de `HocaWorkspaceIntegrationTests` (6 test, model taklit). Gerçek kitap/PDF ve gerçek PC'de denenmedi.

**Sırada:** `study.py:lesson()`'ın (uzun anlatım motoru) da `course_id` ile per-ders kaynağı kullanması — bu ayrı, yakın bir sonraki adım.

## Uzun anlatım motoru bağlantısı — 25 Ekim 2026

- `study.py:lesson(profile, topic, course="", mk="", simpler=False, course_id=None)`: `course_id` verilirse dersin `hoca_workspace`'teki kitap/pdf kaynakları (`course_context`) anlatıma `[DERS KAYNAĞI · ...]` bloğu olarak eklenir; `course` adı açıkça verilmemişse dersin kayıtlı adı kullanılır. Bilinmeyen `course_id` `ValueError` olarak patlar (bu modülün diğer hataları gibi).
- `no_book` artık ya `hoca_workspace` kaynağı ya da eski genel kitap deposu (`study.py`'nin kendi `docs` listesi) varsa `False`'tur — ikisi birbirinden bağımsız, biri yeterli. Eski genel depo bu adımda da taşınmadı/dokunulmadı; yalnız yeni per-ders kaynak eklendi.
- `hoca.py:start()`'tan farklı olarak burada "açıkça verilen `source` her zaman öncelikli" kuralı yok — `lesson()`'ın zaten kendi `_search_items` tabanlı kitap arama mekanizması var, `course_ctx` ona ek bir blok olarak eklenir, onun yerine geçmez.
- Test: `tests/test_study_hoca_workspace.py` (5 test, model taklit, izole tmp klasör). Gerçek kitap/PDF ve gerçek PC'de denenmedi.
- Hoca'nın iki motoru (adım-adım `hoca.py` + uzun anlatım `study.py:lesson()`) artık ikisi de per-ders kaynağa bağlı; sırada oturum hafızası/soru-alıştırma/tekrar planının (3. madde) UI ve akış tarafı var.

## Oturum hafızası v1 — otomatik kayıt (Seçenek A), 25 Ekim 2026

- Hamdi'nin kararı (A): oturum notu her zaman otomatik kaydedilir, kullanıcıdan bir şey istenmez — "soru/alıştırma akışına bağlı" (B) seçeneği kitapsız/sınavsız genel derslerde hiç tetiklenmeyeceği için elenmiş oldu.
- `modules/hoca.py` (adım-adım motor): `course_id` verilen ders artık `lesson["course_id"]`'de saklanıyor. Son adım bitince (`advance`) `hoca_workspace.record_session(..., next_step="Ders tamamlandı; yeni konu seçilebilir.")` otomatik çağrılır. Kontrol sorusu yanlış cevaplanınca (`grade`) mevcut zayıf-konu işaretlemesine ek olarak `unclear=<adım başlığı>` ve `next_step=<"bu adımı tekrar et">` kaydedilir.
- `modules/study.py:lesson()` (uzun anlatım motoru): normal anlatım bitince `next_step=<"konu anlatıldı">`; `simpler=True` (öğrenci anlamadı, sadeleştirilmiş tekrar) çağrısında `unclear=<konu>` kaydedilir.
- **Resume hint:** derse (aynı `course_id`+konu) tekrar girildiğinde önceki oturum `hoca.start()`'ın döndürdüğü sözlükte `resume` anahtarı olarak (varsa) geri verilir; UI bunu "kaldığın yerden devam" olarak gösterebilir. `study.py:lesson()` ayrıca önceki `unclear` notu varsa (ve `simpler` değilse) bunu modele "şurası net değildi" notu olarak otomatik ekliyor — kullanıcıdan tekrar sorulmuyor.
- `course_id` verilmeyen (eski) çağrılarda `hoca_workspace`'e hiç dokunulmaz — geriye dönük uyumluluk korunur.
- Test: `tests/test_hoca.py`'de `SessionMemoryTests` (5 test), `tests/test_study_hoca_workspace.py`'de `LessonSessionMemoryTests` (4 test). Gerçek PC'de denenmedi; UI tarafında "kaldığın yerden devam" bandı henüz yok (bu adım yalnız veri/akış, arayüz ayrı bir iş).

## Ödev parçalama v1 — 4a, 25 Ekim 2026

- Hamdi'nin kararı: "Dönem haritası, takvim, görev, GPA" (4. madde) tek PR'da yapılamayacak kadar geniş olduğu için 4a (ödev parçalama) → 4b (dönem haritası görünümü) → 4c (GPA/not projeksiyonu) sırasıyla küçük adımlara bölündü; sırayla gidiliyor.
- `hoca_workspace.decompose_assignment(profile, course_id, title, due="", context="")`: büyük bir ödevi/projeyi tek bir model çağrısıyla 2-6 küçük alt göreve böler. Asıl ödev her zaman `manual` kökenli olarak eklenir (model çağrısından önce); alt görevler `decomposed` kökenli, `parent_id`'si asıl ödeve işaret eden ayrı kayıtlardır. Model planı eksik/bozuk gelirse (2'den az alt görev, JSON bozuk, model hatası) **hiçbir alt görev yazılmadan** `HocaWorkspaceError` fırlatır — yarım kayıt bırakılmaz (asıl ödev kalır, kullanıcı isterse elle alt görev ekleyebilir).
- `add_assignment` artık `parent_id` parametresi alıyor (yalnız `decomposed` görevlerde dolu) ve `origin` kümesine `"decomposed"` eklendi (`manual`/`syllabus`/`decomposed`).
- Bu, `hoca_workspace.py`'ye ilk kez bir model çağrısı (`llm.ask`) giren fonksiyon — modülün üst docstring'i bunu yansıtacak şekilde güncellendi (geri kalan her şey hâlâ salt veri/okuma).
- Henüz takvime/gerçek bir tarihe yazmıyor (`due` serbest metin olarak kalıyor); takvim bağlantısı 5. maddenin (onaylı takvim değişikliği, `mail-takvim.md` izin hattı) işi.
- Test: `tests/test_hoca_workspace.py`'de `DecomposeAssignmentTests` (5 test, model taklit). UI'a bağlanmadı, gerçek PC'de denenmedi.
- Düzeltme (aynı gün): `except Exception` bloğunda eksik olan `_record_failure` diagnostik çağrısı eklendi (`test_cleanup_security.py:test_every_broad_catch_has_diagnostic` bunu zorunlu kılıyor; PR #341'in ilk CI koşusu bu yüzden kırmızıydı).

## Dönem haritası görünümü v1 — 4b, 25 Ekim 2026

- `hoca_workspace.term_overview(profile, include_done=False)`: tüm derslerin ödev/deadline'larını tek listede, tarihe göre sıralı döner. Model çağrısı yok — yalnız var olan `list_assignments` verisini düzenler (4a'daki gibi yeni bir model çağrısı eklemedi).
- Her öğe orijinal ödev kaydının bir **kopyası** + `course_id`/`course_name` ile zenginleştirilmiş hâli; asıl kayıt mutasyona uğramaz.
- Sıralama: tanınabilir tarihliler (tam `YYYY-MM-DD`) önce ve kronolojik; serbest metin/boş tarihliler (ör. "gelecek hafta") sonda, eklenme sırasıyla — tarih ayrıştırma denemesi yok, yalnız biçim kontrolü.
- `include_done=False` (varsayılan) tamamlanmış ödevleri listeden düşürür; `True` ile hepsi görünür.
- Test: `tests/test_hoca_workspace.py`'de `TermOverviewTests` (6 test). UI'a bağlanmadı; sırada 4c (GPA/not projeksiyonu) var.

## Ödev/sınav bazlı not kaydı — 4c-1, 25 Ekim 2026

- Hamdi'nin kararı: GPA/not projeksiyonu (4. madde) "basit kredi-ağırlıklı ortalama" yerine "detaylı: ödev/sınav bazlı projeksiyon" ile yapılacak; bu da 4c-1 (not kaydı + ders notu) ve 4c-2 (kredi ile genel ortalama) olarak ikiye bölündü, sırayla gidiliyor.
- `hoca_workspace.set_assignment_grade(profile, course_id, assignment_id, score, max_score=100, weight=1)`: bir ödeve/sınava not girer. Var olan notun üzerine yazar — geçmiş not tutulmaz, tek güncel değer. `max_score` 0'dan büyük olmalı; `score`/`weight` negatif olamaz. `score`, `max_score`'u aşabilir (bonus puan). Model çağrısı yok.
- `hoca_workspace.course_grade(profile, course_id)`: notu girilmiş ödevlerin ağırlıklı ortalamasını (100 üzerinden, farklı `max_score`'lar yüzdeye çevrilip normalize edilir) döner. Hiç not girilmemişse `value=None` — uydurma sayı üretilmez. `graded_count`/`total_count` ile notu olan/dersteki toplam ödev sayısı ayrıca görünür (eksik veri sessizce gizlenmez).
- Test: `tests/test_hoca_workspace.py`'de `AssignmentGradeTests` (11 test). UI'a bağlanmadı; sırada 4c-2 (kredi ile genel ortalama) var.

## Kredi ile genel ortalama — 4c-2, 25 Ekim 2026

- `hoca_workspace.set_course_credit(profile, course_id, credit)`: derse kredi/AKTS kaydeder (0 veya pozitif; 0 = "kredisiz/henüz girilmedi", genel ortalamaya katılmaz).
- `hoca_workspace.gpa_projection(profile)`: kredisi girilmiş VE en az bir notu olan (`course_grade` ile) derslerin kredi-ağırlıklı genel ortalaması. Kredisi veya notu eksik dersler `excluded`'te nedeniyle (`kredi_yok` / `not_yok`) birlikte görünür — sessizce atlanmaz, ortalamayı da etkilemez. Hiçbir ders uygun değilse `value=None`.
- Model çağrısı yok, yalnız hesap. 4c (GPA/not projeksiyonu) bu adımla tamamlandı; sıradaki 5. madde (onaylı takvim/görev değişikliği).
- Test: `tests/test_hoca_workspace.py`'de `GpaProjectionTests` (8 test). UI'a bağlanmadı.

## Sesli Hoca modu v1 — 6. adım, 25 Ekim 2026

- Hamdi'nin kararı: 5. madde (onaylı takvim/görev değişikliği) ertelendi — Hoca'nın ders/ödev kayıtları henüz hiçbir sohbet komutuna/ekrana bağlı değil, yani onaylanacak bir "takvime yazma" eylemi yok. Sırada 6. madde (Sesli Hoca modu) var.
- Sorun: genel sesli okuma sınırı (`engine_output._short_for_speech`, 400 karakter) ders anlatımını çoğu zaman yarıda keser — bir öğretmen modunda bu önemli bir kayıp.
- Çözüm: yeni ayar `hoca_voice_full` (varsayılan **kapalı**, AGENTS.md'nin "yeni ses davranışı ayarla açılır olmalı" kuralı gereği). Açıkken `engine_tools._study_intent`, Hoca'dan gelen cevabı `runtime._session().speech_override`'a tam metin olarak yazar (`richtext.speakable` ile temizlenmiş); `engine_loop.py`'deki mevcut `speech_override` mekanizması (başka yerlerde de kullanılan, ör. çeviri bildirimi) bunu 400 karakterlik kısaltmayı atlayıp olduğu gibi okur. Kapalıyken davranış hiç değişmez.
- Model çağrısı yok, ek Gemini/Groq isteği eklenmedi (kota). Ayar `web.py`'de `hoca_enabled` ile aynı yerde okunur/yazılır (`settings()`/`settings_save`); arayüzde henüz bir düğmesi yok (Hoca'nın hiç ekranı yok).
- Test: `tests/test_hoca.py`'de `HocaEngineHookTests` içine 3 yeni test (ayar kapalı/açık/cevapsız) ve `HocaBridgeTests`'e 1 yeni test (ayar kaydı). Gerçek ses/PC'de denenmedi.

## Ödev hatırlatma (5. madde) — "hazır olsun" sürümü, 25 Ekim 2026

- Hamdi'nin kararı: 5. madde (onaylı takvim/görev değişikliği) daha önce "UI olmadan kullanılacak yer yok" diye ertelenmişti; Hamdi "ama hazır olsun bari" dedi — fonksiyon şimdi yazıldı, bir sohbet komutuna/ekrana henüz bağlanmadı.
- `modules/main_planner.py::_hoca_assignment_reminder(runtime, course_id, assignment_id, time='09:00')`: bir Hoca ödevini gerçek hatırlatmaya çevirir. Ödevin kayıtlı `due` tarihini (YYYY-MM-DD) ve verilen saati birleştirip mevcut `_reminder_or_confirm`'e (bu dosyada zaten var olan, mail-takvim.md'nin çakışma-sorma hattı) devreder — **Hoca'ya özel ayrı bir onay kuralı yazılmadı**, Hamdi'nin kararına uygun. Saat biçimi geçersizse 09:00'a düşer; `due` boşsa/tanınmayan biçimdeyse (`YYYY-MM-DD` değilse) açık Türkçe hata verir, sessizce yanlış tarihe yazmaz.
- `hoca_workspace.get_assignment(profile, course_id, assignment_id)`: tek bir ödev kaydına salt-okunur erişim (bu fonksiyon için eklendi).
- Model çağrısı yok. Jarvis'in kendi hatırlatma kaydına yazar (Google Takvim'e değil — sistemin geri kalanıyla aynı).
- Test: `tests/test_hoca.py`'de `HocaAssignmentReminderTests` (6 test, `_reminder_or_confirm` taklit edilerek yalnız yeni kod test edildi), `tests/test_hoca_workspace.py`'de `get_assignment` için 2 test. Hiçbir sohbet komutu/ekran düğmesi yok; gerçek PC'de denenmedi.

## Ders kaydı ve plan — 18 Ekim 2026
- `modules/hoca.py`: ders = konu + 2-8 adım (`start` tek `llm.ask` çağrısı, `parse_plan` JSON doğrular). Kayıt kullanıcı profilinde (`profile.data["hoca"]["lesson"]`, tek aktif ders; yeni `start` bitmemiş dersin yerine geçer). `active/current_step/advance`.
- Model yanıtı bozuk/eksikse ya da çağrı hata verirse `HocaError` (Türkçe mesaj) fırlar ve hiçbir şey kaydedilmez; sessizce düşülmez. Ollama gerekmez, kaynak yüklemek gerekmez.
- Henüz sohbet/ses girişi, konu kilidi denetimi, kontrol sorusu, tekrar ve arayüz yok (sonraki adımlar). Çekirdek `engine_tools._study_intent`'e dokunmadan önce vizyon thread'ine sorulur.
- Test: `tests/test_hoca.py` (model taklit; gerçek model planı denenmedi).
- `context_for(profile)`: aktif dersin konu/adım/başlık/hedefini en çok 600 karakterlik, tek satırlı ve talimat olmadığını belirten alıntılı veri olarak verir; profil değişmez, model/ağ çağrısı yoktur, ders yoksa/bitmişse boştur. Motora henüz bağlanmadı; gerçek PC'de denenmedi.

## Konu kilidi, kontrol sorusu ve zayıf konu — 18 Ekim 2026
- `hoca.intent(metin)`: `next` / `change` / `stay`. Yalnız açık komutlar ("sonraki konuya geç", "konuyu değiştir", tek başına "geç"/"ilerleyelim") adım değiştirir; konuya benzerlik tahmin edilmez, "Osmanlı geç dönem" gibi cümleler `stay` kalır. Sohbete bağlama (çekirdek) sonraki PR'da.
- `check_question` aktif adım için tek soru üretir (1 model çağrısı) ve bekleyen soruyu saklar; bekleyen soru varken yeniden sorulursa model çağrılmaz. `grade` cevabı değerlendirir (1 çağrı): doğruysa sonraki adım, yanlışsa adım aynı kalır ve `weak` listesine yazılır. Adım başına en çok 2 çağrı. Bozuk model yanıtı `HocaError`dır ve ilerletmez.
- Zayıf konu aralığı `studyexam` ile aynı: 1/3/7 gün, iki doğru tekrar = öğrenildi (`due_reviews`, `review_result`). Test: `tests/test_hoca.py` (model taklit; gerçek model ve PC denenmedi).

## Sohbet girişi — 18 Ekim 2026 (vizyon thread'i onayladı)
- `hoca.handle(profile, metin, enabled)`; `engine_tools._study_intent` en başta çağırır (motor sırasına dokunulmadı). Ayar `hoca_enabled` (varsayılan açık; yalnız açık söyleniş yakalanır; ayar ekranı düğmesi arayüz PR'ında). Kapalıyken hiçbir cümle yakalanmaz.
- Başlatma: "hoca modu: hücre", "hoca modu" (konu sorar, model yok), "mitokondri konusunu öğret". Aktif ders varken yalnız şunlar yakalanır: "sonraki adım/konuya geç", tek başına "geç"/"ilerleyelim", "konuyu değiştir/dersi bitir", "cevap: …" / "cevabım: …" (bekleyen soru varken), "bilmiyorum/pas" (modelsiz, adım zayıf konuya yazılır), "zayıf konularım". Başka her cümle ("hava nasıl", dersle ilgili serbest soru dahil) normal yola gider.
- Adım başına en çok 2 model çağrısı: `teach` (anlatım + soru birlikte) ve `grade`. Hata `HocaError` mesajı olarak gösterilir, ilerletmez.
- Bilinen eksik: dersle ilgili serbest sorular ("mitokondri ne işe yarar") normal sohbete gider, ders bağlamı modele verilmiyor; sonraki iş. Test: `tests/test_hoca.py` (`HocaChatTests`, `HocaEngineHookTests`: hoca kapalı/açık, alakasız cümle, aktif ders + komut; model taklit). `_study_intent` başka bir erken kural tarafından önce yakalanabilir mi, gerçek PC'de denenmedi.
- Bilinen sınır: çıplak "devam"/"devam et" hedef motorunun `RESUME_COMMANDS` listesindedir (`engine_commands`, hoca'dan önce çalışır); bu yüzden derste "sonraki adım" ya da "geç" denir, "devam" hoca tarafından yakalanmaz.

## Video ve altyazı kaynağı — 18 Ekim 2026 (Hamdi: resmî yol)
- `modules/hoca_video.py`. Video indirilmez, YouTube'un gayriresmî altyazı adresleri kullanılmaz. `hoca modu: video <bağlantı>`: kullanıcının kendi YouTube anahtarıyla resmî `videos.list` (part=snippet, 1 kota birimi) başlık, kanal, bölümler (açıklamadaki `0:00 Giriş` satırları) ve açıklamayı alır. Videonun konuşması bilinmez; model bu konuda uyarılır ve kullanıcıya söylenir. Anahtar yoksa/API hata verirse `HocaError` (anahtar yoksa .srt/.vtt/.txt yolunu önerir).
- Tam altyazı: `hoca modu: kaynak "<dosya yolu>"` (.srt, .vtt, .txt, .md, .pdf, .docx, .rtf, .odt, .html; en çok 8 MB). Yol yalnız `file_ops._roots()` klasörleri altındadır (Masaüstü, İndirilenler, Belgeler, Resimler, Jarvis Dosyaları; `..` kaçışı çözülür). SRT/VTT'de sıra numarası, zaman çizgisi ve etiketler atılır, ardışık tekrar tek satıra iner.
- Kaynak metin en çok 60 000 karakter, ~2500'lük parçalara bölünür ve profilde dersle birlikte durur; ders bitince/bırakılınca silinir. Plan isteminde kaynağın başı, her adımda yalnız o adıma düşen parçalar (en çok ~6000 karakter) gider; kaynaktaki talimatlar uygulanmaz ve kaynakta olmayan uydurulmaz uyarısı eklenir. Ek model çağrısı yok.
- "video", "kaynak", "altyazı" ile başlayan sıradan konular ("hoca modu: video oyunları", "kaynak enerjisi") kaynak sayılmaz; video için bağlantı, dosya için tırnak/yol gerekir.
- Test: `tests/test_hoca_video.py` (API ve dosya taklit). Gerçek YouTube API'si, gerçek altyazı dosyaları ve PC'de denenmedi; videoda "altyazı kapalı/otomatik" ayrımı yok (otomatik altyazı resmî yoldan alınamaz).

## Arayüz sekmesi — 18 Ekim 2026
- Çalışma sayfasında "Hoca" sekmesi (`hocaHtml`, `webui/nx.js`): konu kutusu + Başla, aktif ders (adım listesi, anlatım, kontrol sorusu, cevap kutusu, Sonraki adım / Bilmiyorum / Dersi bırak), zayıf konular (tekrar zamanı rozeti), "Sohbet komutları" aç/kapat. Düğmeler yeni bir yol açmaz: `say()` ile aynı sohbet komutlarını gönderir ("hoca modu: X", "cevap: …", "sonraki adım"), yani ders sohbet ekranında ilerler; sekme durumu gösterir.
- Veri `study_overview()['hoca']` (= `hoca.snapshot`, model çağırmaz). Ayar `hoca_enabled` (varsayılan açık) `settings()` ve `settings_save` içindedir; sekmedeki düğme onu yazar.
- Test: `tests/hoca_behavior.js` (`JS_GROUPS`'ta), `tests/test_hoca.py` (`HocaSnapshotTests`, `HocaBridgeTests`). Ekranda görsel olarak ve gerçek PC'de denenmedi; ders cevabından sonra sekmenin kendiliğinden yenilenmesi yok (sekmeye yeniden girince/yenile ile güncellenir).
