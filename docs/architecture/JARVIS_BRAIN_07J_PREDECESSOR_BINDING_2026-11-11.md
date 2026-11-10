# BRAIN-07J — Canonical predecessor output binding (11 Kasım 2026)

**Durum:** Dar, read-only kanıt köprüsü; gerçek bağımlı worker dispatch kapalı.
**Ana plan:** `docs/Jarvis_Yol_Haritasi.md`, BRAIN-06/07. Bu belge ikinci Scheduler veya alternatif plan otoritesi tanımlamaz.

## Neden

BRAIN-07D canonical audit + WorkerResult CAS ile `dependent` düğümünün önkoşullarının başarılı olduğunu doğrular. Ancak başarı audit'inin varlığı, `ExecutionRecord.outputs[predecessor]` içindeki *gerçek* metin/dosya referansı/metadata'nın aynı kabul edilmiş worker sonucuyla eşleştiğini tek başına kanıtlamaz. Özellikle crash/resume ya da ayrı writer sonrası, canonical root success ile değişmiş journal output karıştırılmamalı.

## Dar değişiklik

- `worker_result_hook.wrap_output`, **yalnız yeni planlı ve başarılı** WorkerResult'ın tek `evidence[0]` satırına `output_sha256` ekler. Hash, temiz sonuç JSON'undan, deterministic UTF-8/sorted-key/minified JSON formatında alınır; `_worker_result` transport metadata dahil değildir. Eski plansız v1 ve başarısız sonuç şemaları değişmez.
- Yeni `modules/dependency_evidence.py::bind_predecessor_outputs` yalnız snapshot tabanlı bir doğrulama yardımcısıdır. `goal_plan_gate.revalidate`, `ready_read_only_candidates`, aynı plan-version/owner/job ve tek canonical başarı evidence'ını gerektirir. Her doğrudan dependency için ExecutionRecord çıktısının `state=done`, doğrulama metadata'sı ve hash'i canonical kabul edilen kayıtla eşleşir; ardından `goal_tools.verify(output,owner)` **tekrar** çalışır. Kopyalanmış input verir, iş başlatmaz.
- Eski kabul edilmiş fakat `output_sha256` taşımayan sonuçlar **topoloji açısından başarılı kalabilir**, ancak otomatik dependent input olarak kullanılamaz. İlgili çıkışın yeni kanıt kabul/reconcile politikası ayrı güvenlik kararıdır; eski başarıya sessizce hash üretilmez.

## Red / fail-closed matrisi

| Durum | Karar |
| --- | --- |
| Same-SHA canonical accept + değişmemiş journal output + başarılı domain verifier | Yalnız doğrulanmış kopya döner |
| Eksik/stale journal output, değiştirilmiş text veya verification metadata | Reddet |
| Eski plan-versiyonundan kalan sonuç, user intent replan veya paused/cancelled | Reddet |
| Hatalı/başarısız veya eksik predecessor, eksik `output_sha256` | Reddet |
| Canonical audit/evidence sahteciliği veya sonradan değişmiş kanıt dosyası | Reddet |
| Direct root seçimi, effectful/unknown capability | Predecessor handoff yok |
| Planlı sonucu başka `command_id` altında tekrar kullanma | Reddet |

## Devamında ayrıca gerekenler

Bu PR, `runtime_worker_result.prepare` içindeki dependency-node production deny'ını kaldırmaz; `worker_result_commit` dependents'ı da reddetmeye devam eder. Gerçek DAG dispatch için **mevcut** yürütücünün authenticated outputs journal'ı elde etmesi; `NodeCandidate` ile stale/version fence, permission, gerekliyse typed ResourceLease, worker execution identity, proof-bound dependencies, CAS accept + ExecutionRecord save atomikliği ve cancellation/recovery'nin aynı zincirde sınanması gerekiyor.

Testler gerçek geçici canonical GoalState/CAS üstünde sahte read-only sonuçları kullanır. Hash ve audit eşleşmesi gerçek, domain verifier yerine kullanılan mock **gerçek servis/PC readback kanıtı değildir**. PR merge için exact-head CI ve aynı SHA gerçek-PC watcher sonucunu kullanıcı bildirecektir; başarılı derlemeyi tek başına uçtan uca DAG kabulü saymayın.
