# Karar 3 planı — tek JARVIS kişiliği: sunumun tek sahibi — 18 Kasım 2026

## Karar

Kimlik, üslup, teslim kanalı ve anlatım biçimi **tek yerden** üretilir: `modules/persona.py`
(`persona.prompt`) ve sözcük listesi olarak `modules/persona_contract.py`. Yüzeyler kendi
*içerik* sözleşmelerini yazar; sunum cümlesini hiçbir yüzey yeniden yazmaz. "Tek kişilik"
budur: aynı JARVIS, dokuz sunum tercihinin ve kanalın tek sahibi olarak her yanıtı kurar.

Korunan ilkeler: Brain yalnız karar önerir, yürütme/onay yetkisi Core'dadır; sunum tercihi
yetki vermez; kullanıcı onayı model tarafından üretilemez; persona hiçbir işlem, model çağrısı
veya yeni kota harcaması başlatmaz (salt metin bestecisi).

## Değişiklik

**Tek besteci.** `persona.prompt(profile, *, session=None, channel='yazı', notation='düz')`
sırayla şunları yazar: `Persona {VERSION}` + sözleşme metni (`FIXED`), tek kimlik cümlesi,
`Kullanıcı tercihi: yanıt uzunluğu=<değer>` cümlesi, yedi tercihin sahibin cümlesi
(`contract.STYLE`), kanal teslim cümlesi ve anlatım biçimi cümlesi. Eski ham `key=value`
dökümü (`Sunum ayarları ...`) kaldırıldı; tercih artık modele gittiği cümleyle görünür.

**Kanallar.** `contract.CHANNELS` / `DELIVERY_OF`: `yazı`/`web`/`scheduler` → ekran metni
(liste/başlık/kod kullanılabilir), `ekran` → ekran yanıtı (Markdown başlığı ve emoji yok,
adımlar `1), 2)`), `ses`/`telefon` → düz cümle + (verbosity `uzun` değilse) iki cümle tavanı ve
"ayrıntısını ekrana yazayım mı?" teklifi, `bildirim` → `notification` tercihinin bütçesi
(`kısa` tek cümle, `normal` önem sırasıyla en fazla altı cümle). Liste dışında bir kanal veya
anlatım değeri `ValueError` verir; hiçbir yüzey sessizce "bilinmeyen kanal" sınıfına düşmez.

**Anlatım biçimi.** `notation='düz'` (varsayılan) LaTeX'i yasaklayıp Unicode/düz metin ister;
`notation='latex'` `\( ... \)` ve gerçek sembolleri ister. Cümlenin tek sahibi `persona`;
`persona.notation_text(...)` ile yalnız yapıt sözleşmeleri (kod üretimi) de aynı cümleyi alır.

**Silinen mükerrer sahipler.** `Profile.system_prompt` kimlik + kod bloğu + LaTeX cümleleri;
`engine_tools._sys_prompt`'un kendi "Bu soru sesle soruldu…" bloğu (artık kanalı motordan
alıyor: `runtime._cur_source`); `main_documents._photo_action` `photo_sys` kimlik/format
metni; `main_planner._daily_briefing` "Sen … asistansın / En fazla 6 cümle / Madde işareti,
başlık ya da emoji kullanma" metni; `worktrack._SYS` kimlik + "Sesli okunacak: madde işareti…"
+ görev başına cümle bütçeleri; `study._system` "Sen JARVIS Çalışma Modusun" kimliği ve kendi
LaTeX/sembol cümlesi (artık `profile` zorunlu parametre ve `notation='latex'`).

**Sonuç sunumu.** `result_presentation` yanıt uzunluğu sözcük listesini ve karakter bütçesini
`persona_contract.PREFERENCES['verbosity']` / `PREVIEW_CHARS` / `preview_limit`'ten alır;
kendi `('kısa','orta','uzun')` tuple'ı ve 400/1200/6000 sayıları oradan silindi.

**Kapanan gerçek boşluk.** Telefon yanıtı `phone.speakable` ile seslendirildiği hâlde hiçbir
ses kısayı almıyordu; `telefon` kanalı artık `ses` sınıfıyla aynı cümleyi görür. Görme yanıtları
(`engine_intents`) da gerçek komut kanalını taşır.

**Kasden kapsamdışı.** Planlama/JSON zarfları (`task_plan_contracts._SYSTEM`, `goal_executor.SYSTEM`,
`translate`, `math_tutor`, `pc_guide`, `hoca._SYSTEM`) yetenek sözleşmesidir: kimlik cümlesi
taşımaz, üslubu yeniden tanımlamaz. `codegen`'in "tek ```dil bloğu" kuralı `_extract`'ın çıktı
şemasıdır (sunum değil); LaTeX cümlesi sahibinden gelir. Yapıt biçimi olan sayı sınırları da kişilik
cümlesi değildir: `codegen`'in "3 cümlelik kullanım notu", `folder_analysis`'ın klasör özeti "en çok
4 cümle" şekli ve `study`'nin kilitli konuya dönüşte "en fazla 3 kısa cümle" pedagolojisi üretinin
yapısıdır; sahibin cümleleriyle çakışmaz ve kullanıcıya teslim yine `result_presentation` bütçesinden
geçer. Core yetki ve dış veri fence'leri
kişilik metni değildir, `Profile.system_prompt`'ta durur.

## Kanıt

- `tests/test_karar3_single_persona.py` (38 test; ağ/model/işlem gerektirmez): kimlik cümlesinin
  yüzey başına birebir sayımı, dokuz tercihin cümleye dönmesi, ham `key=` dökümünün yokluğu,
  kanal × verbosity × notification matrisi, oturum ve tur kapsamlarının doğru istekte cümleye
  girmesi, bilinmeyen kanal/anlatım `ValueError`, OWNED statik taraması (hiçbir `modules/*.py`
  sahibin cümlelerini yeniden yazmıyor), brief/worktrack/study/photo/codegen bağlamaları,
  preview bütçesinin sözleşme tablosundan gelmesi ve `preview_limit` girdi doğrulaması.
- `tests/test_brain_09_persona.py` (21 test) yeni sözlükle ölçüyor: benimsenen `teknik` tercihi
  sahibin cümlesiyle modele gider ve `technical_detail=teknik` dökümü üretilmez; `yanıt uzunluğu=`
  etiketi ile "uzun tercihi 2-3 cümle tavanıyla çelişmez" korumaları sürüyor.
- Bağlanan diğer süitler: `test_study_recent_exams` (`_system` artık `profile` ister),
  `test_brain_10_results`, `test_f011_daily_briefing_completion`, `test_worktrack_brief_line`,
  `test_study_final_and_github_pull`, `test_learning_install`, `test_brain_pr10c_final_cutover`,
  `test_brain_photo_core_cutover` — birlikte 165 test OK.
- Tam `modules.validation` otoritesi; sonuç bu PR'ın exact head'i için kaydedilir.
- Canlı kabul (Bitti kuralı 3/4): gerçek PC'de sesli sohbet, telefon ve günlük brifing gecesi +
  exact-SHA Windows CI ve aynı SHA PC watcher "passed". Merge tek başına "bitti" değildir.

Alan notları: `docs/agents/persona.md` (Karar 3 paragrafı, sunumun tek sahibi) ve
`docs/agents/arayuz.md` (Hafıza ekranındaki dokuz tercih). Önceki karar: Karar 2 Aşama A/B/C
(`CANONICAL_STAGE_C_SINGLE_EXECUTOR_PLAN_2026-11-18.md`).
