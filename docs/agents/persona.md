# Persona ve sunum tercihleri — BRAIN-09

## Sunum ve tercih sahipliği

Brain anlamı önerir, Core kaydı benimser. `persona_contract` yalnız sürümlü salt-okunur sözleşme/vocabulary'dir; `persona` mevcut Profile/SessionState üzerinde Core sunum servisidir. Model/Router/provider, yeni agent/store/Scheduler değildir.

Tek semantik modelin `brain-understanding.v2` zarfında opsiyonel `presentation` listesi: key/value/scope/exact evidence_quote. Eski zarf boş listeye eşdeğer. Sözleşme dışı/hassas key, serbest değer, model confidence/owner/saat veya kullanıcı cümlesinde olmayan kaynak alıntısı tüm öneriyi reddettirir. Brain'in önerisi Core request_scope'ta owner/RID/original text/MODEL_DECIDED ile tekrar doğrulanır. Core provenance, digest, tarih ve güveni kendisi üretir; ham alıntı diske gitmez.

Sıra turn > session > explicit > fresh/high-confidence learned > default. Turn exact RID; session mevcut owner SessionState ve en çok24saat, resetle biter. Explicit kalıcı kullanıcı/UI tercihi; learned ayrı30günlük öneridir. Tekrarlanan farklı request'lerde aynı değer için güven .4/.6/.8/1 olur; .8 öncesi uygulanmaz. Son32 request kimliğiyle replay sayılmaz. Learn toggle kapalıysa tentative öğrenme yazılmaz. Hassas özellik, hedef/alıcı, onay, permission, privacy, risk veya completion çıkarımı/yetkisi yoktur; progress/notification/initiative yalnız anlatım üslubudur ve mandatory durum/onay gizleyemez.

Mevcut `Profile.system_prompt` tüm sağlayıcılara aynı sabit persona sözleşmesini ve çözülmüş sunumu verir. Eski zorunlu2–3cümle çelişkisi ve `learning_feedback` regex yazarı kaldırıldı. Mevcut onaylı facts/rules korunur; raw rules ve kaynak metni persona yetkisi değildir. Eski non-default prefs değerleri read-compatible UI tercihi sayılır; tarih/provenance uydurulmaz. Eski default orta için explicit irade varsayılmaz; UI'dan orta seçilirse artık explicit metadata yazılır.

Kalıcı yeni tercih/silme, mevcut Profile RLock + file_resource_guard altında diskteki son JSON'la birleşir, aynı Profile atomic save kullanılır; disk hatasında bellek geri alınır. Başka eski Profile mutator'larının tamamı için process-serializability iddiası değildir. Yeni genel storage migration yoktur.

Kullanıcı akışı: Brain prepare→Core handoff scope→mevcut chat/image/system_prompt. Liste/reset mevcut learning.manage intent'indedir; tüm style yazımları top-level presentation veya mevcut UI pref_set'ten gelir. Hafıza ekranında9 kapalı seçim, etkin kaynak ve learned öneri silme vardır; geç owner cevabı ve eski DOM kontrolü yeni kullanıcıya uygulanamaz. Core batch çocuklarında presentation yeniden benimsenmez; parent scope paylaşılır.

Testler: `test_brain_09_persona.py`, `persona_preferences_behavior.js`, komşu model/Core/learning/owner testleri. Full validation, exact-source Windows CI ve gerçekPC watcher ayrı kanıt türleridir. Canlı modelde karakter kalitesi ve Brain-11 ürün kabulü mock/provider sınır testinden geçmiş sayılmaz. Plan: `docs/architecture/BRAIN_09_SINGLE_PR_PLAN_2026-11-14.md`.
