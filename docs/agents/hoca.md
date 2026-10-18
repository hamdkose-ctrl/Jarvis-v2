# Hoca modu (AGENTS.md alan notları)

Plan: `raporlar/hoca-modu-plan-2026-10-18.md` (Hamdi 2026-10-18: seçenek B; önce A kısmı küçük PR'larla, altyazı ayrı PR). Hiçbiri PC'de denenmedi.

## Ders kaydı ve plan — 18 Ekim 2026
- `modules/hoca.py`: ders = konu + 2-8 adım (`start` tek `llm.ask` çağrısı, `parse_plan` JSON doğrular). Kayıt kullanıcı profilinde (`profile.data["hoca"]["lesson"]`, tek aktif ders; yeni `start` bitmemiş dersin yerine geçer). `active/current_step/advance`.
- Model yanıtı bozuk/eksikse ya da çağrı hata verirse `HocaError` (Türkçe mesaj) fırlar ve hiçbir şey kaydedilmez; sessizce düşülmez. Ollama gerekmez, kaynak yüklemek gerekmez.
- Henüz sohbet/ses girişi, konu kilidi denetimi, kontrol sorusu, tekrar ve arayüz yok (sonraki adımlar). Çekirdek `engine_tools._study_intent`'e dokunmadan önce vizyon thread'ine sorulur.
- Test: `tests/test_hoca.py` (model taklit; gerçek model planı denenmedi).

## Konu kilidi, kontrol sorusu ve zayıf konu — 18 Ekim 2026
- `hoca.intent(metin)`: `next` / `change` / `stay`. Yalnız açık komutlar ("sonraki konuya geç", "konuyu değiştir", tek başına "devam"/"geç") adım değiştirir; konuya benzerlik tahmin edilmez, "Osmanlı geç dönem" gibi cümleler `stay` kalır. Sohbete bağlama (çekirdek) sonraki PR'da.
- `check_question` aktif adım için tek soru üretir (1 model çağrısı) ve bekleyen soruyu saklar; bekleyen soru varken yeniden sorulursa model çağrılmaz. `grade` cevabı değerlendirir (1 çağrı): doğruysa sonraki adım, yanlışsa adım aynı kalır ve `weak` listesine yazılır. Adım başına en çok 2 çağrı. Bozuk model yanıtı `HocaError`dır ve ilerletmez.
- Zayıf konu aralığı `studyexam` ile aynı: 1/3/7 gün, iki doğru tekrar = öğrenildi (`due_reviews`, `review_result`). Test: `tests/test_hoca.py` (model taklit; gerçek model ve PC denenmedi).

## Sohbet girişi — 18 Ekim 2026 (vizyon thread'i onayladı)
- `hoca.handle(profile, metin, enabled)`; `engine_tools._study_intent` en başta çağırır (motor sırasına dokunulmadı). Ayar `hoca_enabled` (varsayılan açık; yalnız açık söyleniş yakalanır; ayar ekranı düğmesi arayüz PR'ında). Kapalıyken hiçbir cümle yakalanmaz.
- Başlatma: "hoca modu: hücre", "hoca modu" (konu sorar, model yok), "mitokondri konusunu öğret". Aktif ders varken yalnız şunlar yakalanır: "sonraki adım/konuya geç", tek başına "devam"/"geç", "konuyu değiştir/dersi bitir", "cevap: …" / "cevabım: …" (bekleyen soru varken), "bilmiyorum/pas" (modelsiz, adım zayıf konuya yazılır), "zayıf konularım". Başka her cümle ("hava nasıl", dersle ilgili serbest soru dahil) normal yola gider.
- Adım başına en çok 2 model çağrısı: `teach` (anlatım + soru birlikte) ve `grade`. Hata `HocaError` mesajı olarak gösterilir, ilerletmez.
- Bilinen eksik: dersle ilgili serbest sorular ("mitokondri ne işe yarar") normal sohbete gider, ders bağlamı modele verilmiyor; sonraki iş. Test: `tests/test_hoca.py` (`HocaChatTests`, `HocaEngineHookTests`: hoca kapalı/açık, alakasız cümle, aktif ders + komut; model taklit). `_study_intent` başka bir erken kural tarafından önce yakalanabilir mi, gerçek PC'de denenmedi.
