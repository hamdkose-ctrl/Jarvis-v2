# GoalState cutover preflight checker v1

Durum: **salt-okunur preflight aracı**. Bu doküman ve `modules/goalstate_cutover_preflight.py`
gerçek bir cutover yapmaz; disk üzerindeki mevcut legacy/canonical çiftlerini değiştirmeden
tarar ve "cutover güvenli mi?" sorusuna yapılandırılmış bir cevap döndürür.

Kaynak sözleşme: `docs/architecture/GOALSTATE_CUTOVER_V1.md`. Bu araç o dokümandaki
identity/terminal/missing-state/projection/rollback kararlarını **almaz**; sadece bugünkü
disk durumunun o kararlara göre nerede uyuştuğunu/uyuşmadığını gösterir.

## Ne yapar

`modules.goalstate_cutover_preflight.scan(owner_root)`:

- `owner_root` dizinindeki (örn. `~/.jarvis/.../<owner>/`) legacy `<16-hex-id>.json` job
  kayıtlarını, `modules/goal_state_save_hook.py`'daki aynı isimlendirme ve owner-namespace
  kuralıyla tarar.
- Her legacy kayıt için yanındaki canonical sidecar'ı (`<job_id>.goalstate.json`) arar ve
  `modules/goal_state_compat.py` ile `modules/goal_state.py` sözleşmesine göre karşılaştırır.
- Job id'ye göre sıralanmış, deterministik bir rapor döndürür:

```python
{
  'root': '<owner dizini>',
  'rows': [
    {'job_id': '...', 'owner': '...', 'reason_code': '...',
     'legacy_state': '...', 'canonical_state': '...'},
    ...
  ],
  'counts': {'OK': 3, 'MISSING_CANONICAL': 1, ...},
  'ok': bool,
}
```

## Salt-okunur garanti

- Hiçbir dosya yazılmaz, silinmez veya taşınmaz.
- `goal_state_store.create` / `compare_and_swap` / `compensate` çağrılmaz.
- Legacy kayıt onarılmaz veya normalize edilmez.
- GoalState değiştirilmez; `goal_state_compat.project`/`advance`/`sync` çağrılmaz (yalnız
  `_STATE_MAP` salt-okunur olarak kullanılır).
- Worker, model, provider veya ağ çağrısı yapılmaz.
- `tests/test_goalstate_cutover_preflight.py::test_scan_does_not_modify_any_file`, taramadan
  önce/sonra her dosyanın mtime + içerik hash'ini karşılaştırarak bunu doğrular.

## Desteklenen reason-code'lar

| Kod | Anlamı |
|---|---|
| `OK` | Legacy hedef state ile canonical state eşleşiyor, identity tutuyor. |
| `INVALID_LEGACY_RECORD` | Dosya adı `16-hex.json` desenine uysa da içerik okunamıyor/parse edilemiyor, zorunlu alanlar eksik, `id` dosya adıyla uyuşmuyor veya `owner` dizin adıyla uyuşmuyor. |
| `UNKNOWN_LEGACY_STATE` | Legacy `state`, `goal_state_compat._STATE_MAP`'te karşılığı olmayan bir değer. |
| `MISSING_CANONICAL` | Legacy kayıt geçerli ama yanında `<job_id>.goalstate.json` yok. |
| `CANONICAL_CORRUPT` | Canonical sidecar var ama UTF-8/JSON olarak çözülemiyor veya `goal_state.validate()` sözleşmesini geçemiyor. Ham bayt/istisna metni rapora yazılmaz. |
| `IDENTITY_MISMATCH` | Canonical `owner`/`job_id`/`goal`, legacy `owner`/`id`/`request` ile birebir eşleşmiyor. |
| `STATE_DIVERGENCE` | Identity tutuyor ama legacy hedef state ile canonical state farklı (terminal uyuşmazlığı hariç). |
| `TERMINAL_DIVERGENCE` | Canonical state terminal (`done`/`cancelled`) iken legacy hedef state hâlâ aktif (terminal değil). `STATE_DIVERGENCE`'tan daha özel olarak raporlanır. |

Legacy→canonical state eşlemesi tamamen `modules/goal_state_compat._STATE_MAP`'ten okunur;
bu araç kendi eşleme tablosunu taşımaz, böylece iki yer birbirinden sapamaz.

## Hata davranışı

- Tek bir bozuk/geçersiz kayıt taramanın tamamını düşürmez; o kayıt için fail-closed bir
  satır (`INVALID_LEGACY_RECORD` veya `CANONICAL_CORRUPT`) üretilir, tarama diğer kayıtlarla
  devam eder.
- Geçersiz/yok olan `owner_root` veya beklenmeyen bir I/O hatası
  `goalstate_cutover_preflight.PreflightScanError` fırlatır; mesaj sabit ve güvenlidir, dosya
  içeriği veya ham istisna metni taşımaz.

## Rapor gizliliği

Her satır yalnız `job_id`, `owner`, `reason_code` ve state **etiketlerini** (`legacy_state`,
`canonical_state` — sabit enum değerleri) taşır. Legacy `request`/`blocker`/`question` metni,
canonical `goal`/`blocker`/`audit` içeriği veya herhangi bir ham dosya baytı rapora hiçbir
koşulda yazılmaz.

## Kapsam dışı

- Gerçek cutover switch'i / dual-write authority değişikliği.
- Legacy dosyayı silme, düzeltme veya yeniden yazma.
- `modules/goal_executor.py`, `goal_state_compat.py`, `goal_state_store.py` davranış değişikliği.
- Reducer/CAS, `WorkerResult`, permission/effect, `RuntimeEvent`, watcher/CI.
- Otomatik repair veya rollback; bu araç sadece okur ve raporlar.

İlk gerçek cutover PR'ı bu aracın raporunu kanıt olarak kullanabilir, ama
`docs/architecture/GOALSTATE_CUTOVER_V1.md` içindeki geçiş kapısını (identity/terminal/
missing/projection/rollback kararları) kendisi yerine getirmez.
