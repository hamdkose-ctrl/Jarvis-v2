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
