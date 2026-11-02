# Jarvis Brain PR10c — Kapanış Kanıtı — 2026-11-02

Bu belge PR #495 (`gpt/brain-pr10c-final-cutover`) için final cutover kanıtını kaydeder. Ürün davranışı veya authority sözleşmesi değiştirmez; yalnız kod/test head'inde doğrulanan sonucu ve merge kapılarını belgeler.

## Base ve doğrulanan kod/test head'i

- Base `main`: `e1d6de3cdb3e484ae68cb67da074404f8159f17d` (PR #494 merge)
- Doğrulanan kod/test head'i: `ccb4ed13a15b0ad5c2865c43319d9aeedffb43b7`
- PR: #495
- Branch: `gpt/brain-pr10c-final-cutover`

## Windows CI

`ccb4ed13a15b0ad5c2865c43319d9aeedffb43b7` için GitHub Windows workflow:

- Workflow: `Windows testleri`
- Run: #1180
- Run id: `41354986276`
- Sonuç: **success**
- Roadmap drift: PASS
- Roadmap completion evidence: PASS
- Python/Node doğrulaması: PASS
- Syntax: PASS
- `modules.validation` / Python + JavaScript + smoke: PASS
- Playwright Chromium bootstrap: PASS
- Yerel model canlı kabul bootstrap: PASS

İlk PR head'inde görülen `ExplicitOutputFormatParityTests` Windows long-path / 8.3 short-path farkı ürün hatası değildi. Test `os.path.samefile(...)` ile gerçek dosya kimliğini doğrulayacak şekilde düzeltildi; metin, label, istenen format ve `session.last_doc` iddiaları korunmuştur.

## Gerçek iş-PC watcher

Aynı kod/test SHA için watcher yorumu:

- Commit: `ccb4ed13a15b`
- Genel durum: **passed**
- Validation: **passed**

Dolayısıyla CI ve gerçek-PC kanıtı aynı kod/test head'ine aittir.

## Acceptance kapısı

Canonical Brain acceptance havuzu 465 senaryodur. PR10c ölçümü:

- same: 340
- better: 38
- accepted: 87
- regression: 0
- error: 0
- missing: 0
- dead permits: 0
- expectations met: 301 → 339

Reviewer denetiminde kabul izinlerinin yalnız senaryo ID'sine bağlı olması yetersiz bulundu: aynı ID ileride başka bir `changed` karara kayarsa eski gerekçe onu yanlışlıkla yeşile çevirebilirdi. PR #495 içinde bu açık kapatıldı.

Canlı accepted diff kümesi artık deterministik SHA-256 fingerprint ile pinlidir:

`01261287329bc0fc8b3c11e257ebe397b87891a1f16e1439d9662af4338a3e27`

İlgili dosyalar:

- `tests/data/brain_acceptance_baseline.json` — baseline kararları
- `tests/data/brain_acceptance_accepted_changes.json` — canlı id → gerekçe izinleri
- `tests/data/brain_acceptance_accepted_fingerprint.txt` — exact accepted diff kümesi fingerprint'i
- `tests/data/brain_acceptance_kabul_gecmisi.json` — append-only gerekçe/audit geçmişi

Kapı yalnız `changed` id'nin izinli olmasına bakmaz; varsayılan repo kabul setinde exact diff fingerprint de eşleşmelidir. Aynı senaryo ID'sinin diff'i değişirse acceptance kırmızı olur. `dead_permit` kontrolü ayrıca korunur.

## Routing coverage reviewer düzeltmesi

`tests/test_routing_sentences.py` içinde legacy `task` beklenen satırların herhangi bir non-`None` canonical claim ile otomatik geçebilmesi fazla genişti. PR #495 içinde:

- genel `task` eşdeğerliği yalnız action sınıfındaki canonical claim'lerle sınırlandı;
- `chat`, `clarify`, `None` ve bilinmeyen claim genel task eşdeğeri değildir;
- yalnız iki önceden incelenmiş, hedefi çözülmemiş dosya isteği exact allowlist ile `task → clarify` eşdeğeri sayılır:
  - `bu PDF'yi Word belgesine dönüştür`
  - `Bu iki dosyayı karşılaştır, farkları maddeler halinde çıkar.`

Bu iki durumda canonical davranış hedef uydurmak yerine dosya hedefini sormaktır. Yeni bir task→clarify sürüklenmesi bu exact allowlist dışında sessizce geçemez.

## Test kapsamı sonucu

PR10c review'ünde legacy testleri yalnız silerek yeşile çeviren bir yol tespit edilmedi. Kritik retarget örnekleri yeni canonical authority'yi doğrudan ölçmektedir:

- freshness: Understanding + Core plan ve false-positive `kur` koruması;
- router hızlı yolları: Understanding/Core/Fast Gate;
- pending target/history: canonical `ActiveContext` provenance ve state'in tüketilmemesi;
- work-mode davranışı: action-first CAPABILITY/task, açıklama sorularının CHAT kalması;
- dosya çeviri/format: canonical file target, dil ve Core doğrulaması;
- Live: aynı `prepare → handoff → Core` sınırı, owner/request fence ve özel semantic executor bypass'larının yokluğu;
- learned rules: permission/JIT/effect authority'yi geçemez;
- ikinci semantic authority: production AST guard'larıyla fail-closed.

## Fiziksel legacy retirement

PR10c production ağacında aşağıdaki ikinci semantic-authority yollarını emekli eder:

- `modules/router.py`
- `modules/work_modes.py`
- `modules/freshness.py`
- `engine_tools.route` / `intent_router`
- `app_actions.reference_context`
- `main_documents._resolve_doc`
- legacy `doc_summary` / `doc_insight` / `doc_convert` / `doc_translate` dispatch yolları
- `brain_entry._install_route_guard`
- acceptance harness `_legacy_router()` observation'ı

Canonical sınıflandırılmış istek kapısı `brain_entry.route_command`'dır ve bağlı Brain kararını Core handler şekline projekte eder; ham metinden ikinci bir niyet üretmez.

## Bilinçli kalan borçlar

Bunlar PR10c içinde gizlenmez ve Brain/Faz 11'in merge öncesi otomatik ✅ sayılmasına neden olmaz:

1. Foto follow-up relation kararı bounded `_PHOTO_INTENT` kelime listesiyle surface katmanında kalıyor; unrelated mesaj pending foto tarafından consume edilmez, ancak relation hükmü henüz canonical Understanding'e taşınmış değildir.
2. `engine_intents.dispatch` içinde 17 yetim case etiketi envanter/cleanup borcu olarak duruyor; ikinci semantic authority değillerdir.
3. Notes arama/özetleme domain borcu açık kalır.

Planlı bir PR10d yoktur; bu borçlar kanıtsız silme veya scope genişletme gerekçesi değildir.

## Final merge kapısı

Bu belge bir docs-only evidence commit'i oluşturduğu için branch head'i `ccb4ed13...` SHA'sından ileri taşınacaktır. Bu nedenle PR #495 merge'e hazır sayılmadan önce **belgenin bulunduğu nihai exact head SHA** için de:

1. Windows CI PASS,
2. aynı exact SHA gerçek iş-PC watcher PASS,
3. final diff/test-coverage review PASS,
4. Hamdi'nin açık merge onayı

gereklidir.

Nihai docs-only head'in CI/watcher sonucu PR gövdesine veya PR yorumuna kaydedilir; yalnız kendi SHA'sını belgeye yazmak için yeni commit açılıp sonsuz kanıt döngüsü oluşturulmaz.
