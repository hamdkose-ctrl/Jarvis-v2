# Hoca modu (AGENTS.md alan notları)

Plan: `raporlar/hoca-modu-plan-2026-10-18.md` (Hamdi 2026-10-18: seçenek B; önce A kısmı küçük PR'larla, altyazı ayrı PR). Hiçbiri PC'de denenmedi.

## Ders kaydı ve plan — 18 Ekim 2026
- `modules/hoca.py`: ders = konu + 2-8 adım (`start` tek `llm.ask` çağrısı, `parse_plan` JSON doğrular). Kayıt kullanıcı profilinde (`profile.data["hoca"]["lesson"]`, tek aktif ders; yeni `start` bitmemiş dersin yerine geçer). `active/current_step/advance`.
- Model yanıtı bozuk/eksikse ya da çağrı hata verirse `HocaError` (Türkçe mesaj) fırlar ve hiçbir şey kaydedilmez; sessizce düşülmez. Ollama gerekmez, kaynak yüklemek gerekmez.
- Henüz sohbet/ses girişi, konu kilidi denetimi, kontrol sorusu, tekrar ve arayüz yok (sonraki adımlar). Çekirdek `engine_tools._study_intent`'e dokunmadan önce vizyon thread'ine sorulur.
- Test: `tests/test_hoca.py` (model taklit; gerçek model planı denenmedi).
