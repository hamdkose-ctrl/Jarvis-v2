# BRAIN-09 — Persona ve kullanıcı adaptasyonu, tek PR

Taban main `1cc32a858b42fc90001f01d1638c5e55691572b1`; #626/#627/#625 birleşmiştir. Başlangıçta açık PR yoktur (`gh pr list`). Hamdi Brain-09'un tek PR'da uygulanmasını onayladı; yeniden onay veya ayrı persona/Router işi açılmaz.

## Seçenek ve karar

A: Yeni persona agent/store/prompt zinciri. İkinci karar ve veri sahibi doğurur; seçilmedi.
B: Mevcut Brain zarfına kapalı presentation önerisi, Core'un mevcut Profile/SessionState sahipliğine bağlanması ve mevcut system_prompt tüketicisinin sürümlü sözleşmeye geçirilmesi. Seçilen yol budur. Ek model çağrısı, dependency, Scheduler, GoalState veya effect yetkisi yoktur.

## Sözleşme ve üretim akışı

- Sabit dürüstlük, sakinlik, eleştirel değerlendirme, inisiyatif ve uygun mizah sürümlü sözleşmedir; davranış tercihi izin/onay/gizlilik/tamamlanma hükmünü ezemez.
- Yalnız kapalı sunum anahtar/değerleri: uzunluk, resmiyet, teknik ayrıntı, bilgilendirme, inisiyatif üslubu, eleştirellik, bildirim üslubu, hitap ve mizah. Hassas özellik veya ham talimat çıkarımı yoktur.
- Tek Brain çağrısı mevcut v2 zarfta isteğe bağlı `presentation` listesi önerir. Eski zarf boş listeye eşdeğerdir. Her kayıt özgün kullanıcı cümlesinden exact quote taşır; model owner/RID/saat/confidence yazmaz. Core tekrar doğrular, provenance'ı kendisi bağlar.
- `turn` yalnız exact RID; `session` mevcut owner SessionState ömrü; `explicit` mevcut Profile kalıcı alanı; `learned` ayrı süreli ve güvenli öneri. Öncelik turn > session > explicit > yeterince tekrarlanmış/fresh learned > default. Session/turn, kalıcı açık tercihi silmez. Tek seferlik kısa istek kalıcı persona tercihi yazmaz; mevcut sohbet geçmişi ve onaylı bilgi-adayı akışı kendi veri sözleşmesinde kalır.
- Learned güveni modelden alınmaz: farklı kullanıcı isteklerindeki aynı kapalı tercih gözlemleriyle Core hesaplar; düşük güven uygulanmaz. Provenance/digest/time/expiry saklanır, ham kullanıcı metni veya hassas çıkarım saklanmaz.
- UI verbosity aynı Core kayıt sahibine gider; eski prefs.verbosity read-compat korunur. Tercihler listelenir, değişir, silinir; reset bir tercih yazımıdır ve başarıdan önce kalıcı kayıt tamamlanmalıdır.
- Core scope → mevcut chat/image/profile prompt ve sağlayıcı adapterı; provider değişimi aynı persona sözleşmesini korur. Kaynak/belge/araç cevabı salt veri; kendi başına tercih yazarı değildir.
- Legacy chat-sonrası `learning_feedback` regex yazarı kaldırılır; onaylı facts/rules mağazası korunur ve ham kaynak metni sabit persona talimatı değildir. Sabit 2–3 cümle zorlaması kaldırılır; seçilen uzunluk gerçekten sunum talimatını belirler.

## Kabul

Önce gerçek üretim seam'inde RED; sonra tek model önerisi→Core→Profile/Session→chat adapter regresyonları. Owner/RID, reset, düşük güven/expiry, conflict, restart/readback, disk hatasında rollback, legacy/UI uyumu, kaynaktan injection ve yetki sınırı negatifleri. Mandatory full validation + guard/roadmap/Ruff, exact-source Windows CI ve gerçek PC watcher ayrıca kaydedilir. Canlı sağlayıcı karakter tutarlılığı veya Brain-11 insan kabulü mock testten geçmiş sayılmaz. Sonuçlar PR metadata ve bu belgeye kanıt türüyle yazılır.

## Kaynak dondurma öncesi doğrulama

İlk11 regresyon mevcut kaynakta5FAIL/5ERROR ile RED: sabit kısa-cümle çelişkisi, alıntılanan ham feedback'in kalıcı kurala dönüşmesi ve eksik typed tercih API'si. Son kapsam21 yeni Python regresyonu; gerçek EngineContext→prepare→tek semantik model çağrısı→Core→chat prompt, gerçek Profile JSON/readback/rollback, mevcut batch çocukları ve UI native Bridge dahil. İlgili253 Python testi PASS; arayüz persona davranış testi PASS; Ruff F821/F822/F823/Architecture Guard/roadmap/diff PASS. Yeni exact-source full validation/Windows/PC kanıtı bu sayılarla karıştırılmadan PR'da kaydedilecektir.
