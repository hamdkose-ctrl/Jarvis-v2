# Jarvis Otonom / Serbest Runtime v1.1 — Uygulama Planı

Tarih: 2 Kasım 2026
Durum: **DESIGN FROZEN — IMPLEMENTATION NOT STARTED**
Canonical tasarım: `docs/architecture/JARVIS_AUTONOMOUS_FREE_RUNTIME_V1_1.md`

> **ROADMAP AUTHORITY DEĞİLDİR.** Jarvis-v2’nin tek aktif uygulama yol haritası `docs/Jarvis_Yol_Haritasi.md` dosyasıdır. Bu belge yalnız Otonom / Serbest v1.1 için scoped uygulama paketlerini ve kabul kapısını tanımlar.

## Yol haritasındaki yeri

Bu çalışma mevcut Faz 0–12'nin yerine geçmez ve yeni bir authority omurgası kurmaz. Fazların yetenek/capability gelişimini kesen yeni bir numaralı faz değildir; mevcut Core/GoalState/RuntimeEvent/worker yeteneklerinin üstüne gelen **yatay çalışma katmanıdır**.

Kısa ayrım:

- **Fazlar:** Jarvis *ne* yapabiliyor?
- **Otonom / Serbest:** Jarvis izin verilen işi *nasıl kendi kendine sürdürüyor ve organize ediyor?*

## Başlama kapısı

Uygulamaya şu iki koşul kapanmadan başlanmaz:

1. **Faz 0–4 gerçek closeout** — güncel main üzerinde kod bağlantısı, legacy temizlik, exact-head doğrulama ve gerekli gerçek-PC acceptance.
2. **Canonical Brain closeout** — kullanıcı girişlerinin canonical Brain → Core sınırında tek semantic authority ile kapanması; açık migration borçlarının bitmesi.

Bu kapı yalnız sıralama kuralıdır. Otonom/Serbest tasarımı hazırdır fakat 0–4 veya Brain scope'una autonomy kodu sızdırılmaz.

## Design-freeze kararları

- Kullanıcıya yalnız `OTONOM` ve `SERBEST` görünür.
- Brain güçlü proposal üretir ama authority değildir; permission/effect/budget/provider/data-egress/canonical state/completion Core'dadır.
- Jarvis'in varsayılanı ilerlemektir; düşük riskli/reversible belirsizlikte makul varsayımla devam eder ve varsayımı kaydeder.
- V1 Serbest delegation **flat depth=1**'dir; child başka child açmaz, gerektiğinde Core'a sibling uzman proposal'ı döndürür.
- `Jarvis dur` = `PAUSED`, `Devam et` = revalidation sonrası resume, `İptal et` = terminal cancel. Pause/Cancel autonomous wake'ten **önce** uygulanır.
- Duplicate wake tek reasoning turuna coalesce edilir.
- Mid-flight steering mevcut Goal'ı çöpe atmadan constraint update yapar; evidence korunur, steering permission/budget/privacy genişletemez.
- Partial artifact'ler sonuç geldikçe panelde gösterilir; her partial result notification üretmez.
- Micro-feedback kısa ve anlamlıdır; heartbeat / “hâlâ çalışıyorum” spam'i yoktur.
- Child/worker tüketimi parent Goal budget'ından harcanır.
- Meaningful progress varsa bir defalık bounded `+2 grace turn` kullanılabilir; bu user budget artışı değildir.
- Budget biterse yapılan iş kaybolmaz: partial result + `WAITING_FOR_BUDGET`.
- Bekleme active budget tüketmez; uzun takip Goal'ları event/timer sonrası küçük execution slice ile uyanır.
- Quota bittiğinde ücretli modele sessiz fallback yoktur; `WAITING_FOR_QUOTA`.
- Local read ile data egress ayrıdır. LLM, HTTP, URL/query, **search query**, form, upload, mail/message, webhook ve external API write outbound policy'den geçer.
- Derived summary/compact projection kaynak privacy sınıfını miras alır.
- Credential/secret model/context/evidence/query/form/log'a çıkmaz; yalnız kendi credential-aware auth transport'u kendi yetkili servisine taşıyabilir.
- External web/PDF/mail/tool içeriği `UNTRUSTED_DATA`'dır; instruction authority kazanamaz.
- Risk sınıfını Brain değil Core Effect/Risk Matrix belirler.
- Unknown external effect blind retry edilmez; reconcile edilemiyorsa kullanıcıya döner.
- Small/Medium ve deterministik completion şartları geçen işte gereksiz semantic verifier çağrısı yapılmaz; verifier Large/conflict/low-confidence durumuna saklanır.
- Yeni fikirler otomatik v1.1 scope'una eklenmez; backlog/kalite önerisi olarak tutulur.

## Başlangıç budget profilleri

| Profil | Brain turn | Worker komutu | Aktif çalışma | Toplam child |
| --- | ---: | ---: | ---: | ---: |
| Küçük | 4 | 6 | 15 dk | 1 |
| Orta | 8 | 16 | 60 dk | 3 |
| Büyük | 16 | 40 | 4 saat | 6 |

Serbest V1 sınırları:

- `MAX_PARALLEL_CHILDREN = 2`
- `MAX_PARALLEL_CLOUD_LLM = 1`
- `MAX_DELEGATION_DEPTH = 1`

## Uygulama paketleri

Mevcut repo PR numaralarıyla karışmaması için paketler `OTO-*` / `SER-*` adıyla takip edilir. Bunlar scoped uygulama paketleridir; diff büyürse daha küçük PR'a bölünebilir.

### OTONOM

1. **OTO-1 — Mode + Control Plane**
   - AutonomyMode
   - Pause/Resume/Cancel
   - stop gate
   - temel invariants
   - autonomous wake bundan önce açılmaz

2. **OTO-2 — Risk / Privacy / Egress contracts**
   - Effect/Risk Matrix
   - source classification
   - taint propagation
   - credential/log redaction
   - outbound/search-query egress gate

3. **OTO-3 — ContinuationWake + Controller**
   - deterministic precheck
   - wake reasons
   - paused event retention
   - duplicate wake coalescing

4. **OTO-4 — Budget**
   - profiles
   - parent accounting
   - grace reserve
   - partial result on exhaustion

5. **OTO-5 — Quota-aware runtime**
   - provider/account quota scope
   - `WAITING_FOR_QUOTA`
   - reset wake
   - no paid fallback

6. **OTO-6 — Brain continuation robustness**
   - proposal contract
   - malformed output recovery
   - repeated proposal suppression

7. **OTO-7 — Steering + Assumptions + Micro-feedback**
   - mid-flight steering
   - authority-safe constraint update
   - assumption ledger
   - concise feedback

8. **OTO-8 — Streaming + Notification**
   - partial artifacts
   - panel flow
   - notification dedup

9. **OTO-9 — Completion + Compaction + Otonom acceptance**
   - deterministic fast completion
   - conditional semantic verifier
   - privacy-preserving compact projection
   - Otonom acceptance

### SERBEST

1. **SER-1 — SubGoal + Direct Child runtime**
   - flat depth=1
   - child result bridge
   - parent budget

2. **SER-2 — Child lifecycle**
   - progress lease
   - active TTL
   - sleep/resume
   - stale fencing
   - parallel limit

3. **SER-3 — Sibling orchestration**
   - sequential/parallel sibling delegation
   - cloud concurrency=1
   - mode downgrade/upgrade

4. **SER-4 — PC/Core + Windows acceptance**
   - ComputerWorker Core gate
   - pause/cancel/stale result
   - real Windows acceptance

## Acceptance kapısı

En az şu sınıflar kanıtlanmadan runtime tamam sayılmaz:

- autonomous Goal + event/timer wake
- pause → pause sırasında event → resume, event kaybolmaz
- cancel ve cancel sonrası late result
- duplicate wake
- malformed Brain output
- repeated rejected proposal
- budget exhaustion → partial result
- quota exhausted → wait → resume
- streaming artifact + notification dedup
- mid-flight steering ve yanlış steering sınıflandırmasında evidence korunması
- prompt injection
- private data URL/query/form/**search query** exfiltration block
- private summary/projection unauthorized cloud block
- credential model/arbitrary HTTP/log block
- sleep/resume
- restart
- unknown external effect no blind retry
- direct child + sibling orchestration
- parent budget accounting
- cloud LLM concurrency=1
- gerçek Windows/ComputerWorker Core gate acceptance

## Not

Bu kayıt uygulama başlangıcı değildir. Öncelik değişmedi:

```text
Faz 0–4 closeout
        +
Canonical Brain closeout
        ↓
OTO-1 ... OTO-9
        ↓
Otonom gerçek-PC acceptance
        ↓
SER-1 ... SER-4
        ↓
Serbest gerçek-PC acceptance
```
