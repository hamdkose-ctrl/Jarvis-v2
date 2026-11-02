# Photo Follow-up Relation Canonicalization — Design

## Intent
PR10c sonrası açık kalan tek surface-bağlı semantic istisnayı kapatmak: telefondan gelen ve `Ne yapayım?` diye bekleyen fotoğraf için sonraki kullanıcı cümlesinin fotoğrafla ilgili olup olmadığına artık `engine_commands` içindeki `_PHOTO_INTENT` regex'i değil canonical Understanding karar verecek.

## Goals
- Pending foto follow-up relation hükmünü `brain_understanding` içinde üretmek.
- Exact iptal davranışını mevcut `brain_gates` bounded state protokolünde bırakmak.
- 600 sn TTL, owner izolasyonu, foto execution (`_photo_action`) ve unrelated mesajın pending'i düşürüp normal canonical akışta devam etmesi davranışını korumak.
- `_PHOTO_INTENT` runtime semantic authority'sini kaldırmak.

## Non-goals
- Yeni resolver, store, router veya foto worker kurmak.
- Foto vision/execution davranışını değiştirmek.
- Pending foto timeout politikasını değiştirmek.
- PR10c'de açık kalan 17 orphan dispatch etiketi veya notes arama/özetleme borcuna dokunmak.

## Constraints
- Brain semantic proposal üretir; Core/domain execution authority değişmez.
- `State exists != next utterance belongs to that state` invariantı korunur.
- Açık uçlu relation kararı Exact State Gate'e taşınmaz.
- Unrelated mesaj pending foto tarafından consume edilmez.
- Önce RED test, sonra minimal production değişikliği.

## Approaches

### A — Relation grammarını Understanding'e taşı, handler yalnız canonical sonucu tüketir — SEÇİLDİ
Pending photo state `ActiveContext`te zaten `pending_photo` olarak görünüyor. Understanding, yalnız bu state varken foto follow-up semantiğini tanır ve `ConversationRelation.ANSWER_TO_PENDING` üretir. `engine_commands` pending-photo branch'i exact cancel için canonical state protocolünü, devam için bound Understanding relation'ını tüketir. `_PHOTO_INTENT` runtime regex'i silinir.

Trade-off: Mevcut foto follow-up kelime/ifade sözlüğü tamamen yok olmaz; fakat tek semantic authority olan Understanding'e taşınır. Bu, migration hedefiyle uyumludur ve davranış parity'sini korur.

### B — Resolver pending foto artifact'ını her follow-up'ta hedef olarak bağlasın — REDDEDİLDİ
`bunu analiz et` için uygun olsa da `analiz et`, `ne yazıyor`, `özetle` gibi zamirsiz cevaplar resolver hedefi gerektirmeden pending soruya doğal cevaptır. Resolver'ı relation authority'sine dönüştürmek scope ve authority karışıklığı yaratır.

### C — Foto follow-up kelime listesini Exact State Gate'e taşı — REDDEDİLDİ
Exact State Gate yalnız bounded/exact protokoller içindir. `analiz et`, `ne yazıyor`, `bu nedir` gibi açık uçlu semantik cevapları gate'e taşımak `state exists != next utterance belongs to that state` kuralını zayıflatır.

## Files
- `modules/brain_understanding.py`: pending-photo follow-up relation tanımı.
- `modules/engine_commands.py`: `_PHOTO_INTENT` yerine bound canonical decision tüketimi; TTL ve execution korunur.
- `modules/engine_runtime.py`: `_PHOTO_INTENT` runtime regex'ini kaldırır.
- `tests/test_brain_photo_followup_relation.py`: canonical relation + handler davranışı + unrelated/cancel/TTL parity.
- `docs/Jarvis_Yol_Haritasi.md`: foto follow-up relation borcunu kapatma kanıtı, merge öncesi 🔄 olarak.
- `docs/architecture/JARVIS_BRAIN_MIGRATION_MAP_V1.md`: Phone photo entry matrix truth-sync.

## Success
- Pending foto + foto follow-up cümlesi → Understanding `ANSWER_TO_PENDING`; handler aynı foto path ile `_photo_action` çağırır.
- Pending foto + unrelated mesaj → relation `NEW_REQUEST`; pending düşer; foto action çağrılmaz; normal canonical akış devam eder.
- Exact cancel → `phone_photo.cancel` bounded protocol; foto action çağrılmaz.
- Expired pending photo → foto follow-up consume edilmez.
- `_PHOTO_INTENT` üretim kodunda yok.
- Focused tests + full validation + exact-head Windows CI + same-SHA PC watcher PASS.
