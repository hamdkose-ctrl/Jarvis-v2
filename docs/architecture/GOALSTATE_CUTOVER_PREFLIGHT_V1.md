# GoalState cutover preflight checker v1

Durum: **salt-okunur preflight aracı**. Bu doküman ve `modules/goalstate_cutover_preflight.py`
gerçek bir cutover yapmaz; disk üzerindeki mevcut legacy/canonical çiftlerini değiştirmeden
tarar ve "cutover güvenli mi?" sorusuna yapılandırılmış bir cevap döndürür.

Kaynak sözleşme: `docs/architecture/GOALSTATE_CUTOVER_V1.md`. Bu araç o dokümandaki
identity/terminal/missing-state/projection/rollback kararlarını **almaz**; sadece bugünkü
disk durumunun o kararlara göre nerede uyuştuğunu/uyuşmadığını gösterir.

## Ne yapar

`modules.goalstate_cutover_preflight.scan(owner_root)`:

- `owner_root` dizinindeki legacy `<16-hex-id>.json` job kayıtlarını,
  `modules/goal_state_save_hook.py`'daki aynı dosya adı ve owner-namespace kuralıyla tarar.
- Her legacy kayıt için yanındaki canonical sidecar'ı (`<job_id>.goalstate.json`) arar ve
  `modules/goal_state_compat.py` ile `modules/goal_state.py` sözleşmesine göre karşılaştırır.
- Job id'ye göre sıralanmış deterministik bir rapor döndürür:

```python
{
  'rows': [
    {'job_id': '...', 'reason_code': '...',
     'legacy_state': '...', 'canonical_state': '...'},
    ...
  ],
  'counts': {
    'OK': 0,
    'INVALID_LEGACY_RECORD': 0,
    'UNKNOWN_LEGACY_STATE': 0,
    'MISSING_CANONICAL': 0,
    'CANONICAL_CORRUPT': 0,
    'IDENTITY_MISMATCH': 0,
    'STATE_DIVERGENCE': 0,
    'TERMINAL_DIVERGENCE': 0,
  },
  'ok': bool,
}
```

Rapor `owner_root` yolunu veya owner adını içermez. `counts` anahtar sırası sabittir;
`rows` her zaman `job_id` sırasındadır.

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
| `OK` | Legacy hedef state ile canonical state eşleşiyor ve canonical identity (`owner`, `job_id`, `goal`, `execution_mode='agent'`) compatibility projection ile uyumlu. |
| `INVALID_LEGACY_RECORD` | Dosya adı `16-hex.json` desenine uysa da içerik okunamıyor/parse edilemiyor, zorunlu alanlar eksik, `id` dosya adıyla uyuşmuyor veya `owner` dizin adıyla uyuşmuyor. |
| `UNKNOWN_LEGACY_STATE` | Legacy `state`, `goal_state_compat._STATE_MAP`'te karşılığı olmayan bir değer. Bilinmeyen ham state değeri rapora yazılmaz. |
| `MISSING_CANONICAL` | Legacy kayıt geçerli ama yanında `<job_id>.goalstate.json` yok. |
| `CANONICAL_CORRUPT` | Canonical sidecar var ama UTF-8/JSON olarak çözülemiyor veya `goal_state.validate()` sözleşmesini geçemiyor. Ham bayt/istisna metni rapora yazılmaz. |
| `IDENTITY_MISMATCH` | Canonical `owner`/`job_id`/`goal` veya compatibility için beklenen `execution_mode='agent'` legacy projection ile uyuşmuyor. |
| `STATE_DIVERGENCE` | Identity tutuyor ama legacy hedef state ile canonical state farklı ve iki taraf da terminal değil. |
| `TERMINAL_DIVERGENCE` | State'ler farklı ve legacy hedef veya canonical state'ten en az biri terminal (`done`/`cancelled`). Terminal↔terminal farklılığı da bu sınıfa girer. |

Legacy→canonical state eşlemesi tamamen `modules/goal_state_compat._STATE_MAP`'ten okunur;
bu araç kendi eşleme tablosunu taşımaz, böylece iki yer birbirinden sapamaz.

## Hata davranışı

- Tek bir bozuk/geçersiz kayıt taramanın tamamını düşürmez; o kayıt için fail-closed bir
  satır (`INVALID_LEGACY_RECORD` veya `CANONICAL_CORRUPT`) üretilir, tarama diğer kayıtlarla
  devam eder.
- Geçersiz/yok olan `owner_root` veya owner dizininin taranamaması
  `goalstate_cutover_preflight.PreflightScanError` fırlatır; mesaj sabit ve güvenlidir, dosya
  içeriği veya ham istisna metni taşımaz.

## Rapor gizliliği

Her satır yalnız güvenli metadata taşır: `job_id`, `reason_code` ve bilinen state etiketleri.
Aşağıdakiler rapora yazılmaz:

- owner adı veya owner dizin yolu,
- legacy `request`, `blocker`, `question` veya bilinmeyen ham state değeri,
- canonical `goal`, `blocker`, `evidence`, `audit` içeriği,
- ham dosya baytları veya parse/validation exception metni.

Identity karşılaştırması bu alanları bellekte okuyabilir; yalnız eşleşip eşleşmediği
`IDENTITY_MISMATCH` reason-code'u olarak dışarı çıkar.

## Kapsam dışı

- Gerçek cutover switch'i / dual-write authority değişikliği.
- Legacy dosyayı silme, düzeltme veya yeniden yazma.
- `modules/goal_executor.py`, `goal_state_compat.py`, `goal_state_store.py` davranış değişikliği.
- Reducer/CAS, `WorkerResult`, permission/effect, `RuntimeEvent`, watcher/CI.
- Otomatik repair veya rollback; bu araç sadece okur ve raporlar.

İlk gerçek cutover PR'ı bu aracın raporunu kanıt olarak kullanabilir, ama
`docs/architecture/GOALSTATE_CUTOVER_V1.md` içindeki geçiş kapısını (identity/terminal/
missing/projection/rollback kararları) kendisi yerine getirmez.
