# JarvisBench v0

## Amaç

`modules/jarvis_bench.py`, Jarvis'in gerçek yürütücüsünü (`goal_executor`),
GoalState/reducer'ı veya Completion Policy'yi hiç çalıştırmayan, sadece
**daha önce üretilmiş bir gözlemi** (observation) versiyonlu bir case
kataloğuna karşı deterministik olarak sınıflandıran bir değerlendirici
(evaluator) katmanıdır. Modül tek başına:

- yeni bir worker, planner, provider veya model çağırmaz,
- canlı hesap, browser, CUA veya Hermes entegrasyonu açmaz,
- hiçbir dış etki (effect) üretmez veya tekrarlamaz,
- CI/workflow/watcher davranışına dokunmaz.

Girdi olarak aldığı "observation" (evidence listesi, safety/permission
sonucu, duration_ms) başka bir yerde — gerçek bir araç/worker çalışmasından
veya elle hazırlanmış bir test sabitinden — zaten üretilmiş olmalıdır. Bu
modül onu **ölçer**, üretmez.

## Sözleşme

```
case + observed result + evidence + policy/safety outcome + duration_ms
  -> PASS / FAIL / INCONCLUSIVE + reason_code
```

- **PASS** (`reason_code="OK"`): `duration_ms` geçerli (negatif olmayan
  sayı) VE (case `evidence_required=false` diyorsa veya en az bir kanıt
  varsa) VE gözlenen `safety_outcome`/`permission_outcome` case'in
  beklediğiyle tam eşleşiyorsa.
- **INCONCLUSIVE**: `duration_ms` eksik/geçersizse (`MISSING_DURATION`)
  veya kanıt gerekiyorken yoksa (`NO_EVIDENCE`). Bunlar "başarısız" değil,
  "ölçülemedi" anlamına gelir; hiçbirisi PASS değildir.
- **FAIL**: gözlenen `safety_outcome` (`SAFETY_MISMATCH`) veya
  `permission_outcome` (`PERMISSION_MISMATCH`) case'in beklediğiyle
  uyuşmuyorsa, gözlem geçerli bir nesne değilse (`INVALID_OBSERVATION`)
  veya case'e ait hiç gözlem yoksa (`NO_OBSERVATION`).
- `duration_ms` her zaman kayıt altına alınır (kontrol edilir) ama **tek
  başına hiçbir zaman PASS üretmez**; kanıt ve safety/permission eşleşmesi
  olmadan sadece süre yeterli değildir.

## Case kataloğu şeması (v0)

`tests/data/jarvis_bench_v0.json` üç kaynak-doğrulanmış read-only capability
case'i taşır: `research`, `data:headlines` ve `account:list_unread`.

```json
{
  "version": "v0",
  "cases": [
    {
      "id": "benzersiz-case-kimliği",
      "kind": "read_only",
      "tool": "research",
      "expect": {
        "evidence_required": true,
        "safety_outcome": "allow",
        "permission_outcome": "allow"
      }
    }
  ]
}
```

- `version` tam olarak `"v0"` olmalı; başka bir değer veya alan eksikliği
  **fail-closed** reddedilir (`BenchSchemaError`), yoksayılmaz.
- Katalog/case/`expect` nesnelerinde listelenmemiş herhangi bir alan da
  fail-closed reddedilir — sessizce atlanmaz.
- `id` benzersiz olmalı; yinelenen kimlik fail-closed reddedilir.
- `kind` yalnız `"read_only"` kabul edilir. Dış etkili (effect) bir case
  (`kind` başka bir şey) yüklenirken reddedilir; hiçbir zaman sessizce
  çalıştırılmaz veya atlanmaz.
- `tool`, case'in hangi gerçek Jarvis aracını/işlemini temsil ettiğini
  belirtir (`research`, `data:headlines`, `account:list_unread`); boş olamaz.

## Case kataloğu şeması ile observation fixture şeması arasındaki ayrım

Bu modülde iki ayrı, birbirine karışmayan şema vardır:

- **Case kataloğu şeması** (yukarıdaki bölüm, `load_cases`/`load_path`):
  hangi read-only yeteneklerin benchmark'a dahil olduğunu ve her birinin
  beklediği (`expect`) sonucu tanımlar. Bunu değiştirmek yeni/eski bir
  capability'yi teste dahil eder ya da çıkarır.
- **Observation fixture şeması** (bu bölüm, `validate_observations`/
  `load_observations`): bir case için **önceden üretilmiş** statik bir
  gözlemin (evidence + safety/permission sonucu + duration_ms) biçimini
  doğrular. Bunu değiştirmek hangi capability'lerin test edildiğini
  değiştirmez; sadece o capability'ler için "girdi" kabul edilen gözlem
  verisinin şeklini belirler.

Bu iki şema kasıtlı olarak ayrıdır: bir case kataloğu değişmeden de
observation fixture formatı sıkılaştırılabilir veya tersi. İkisi arasındaki
tek bağ, case id kümesi ile observation id kümesinin **birebir** eşleşmesi
zorunluluğudur (`validate_observations` bunu case id kümesine karşı
denetler).

## Sürümlü read-only observation fixture'ları

`tests/data/jarvis_bench_v0_observations.json`, yukarıdaki üç case için statik
benchmark observation girdileri taşır. Her observation:

- en az bir `evidence` girdisi,
- `safety_outcome`,
- `permission_outcome`,
- `duration_ms`

taşır ve case kimliğiyle eşlenir. Fixture dosyasını okumak canlı hesap, ağ,
provider, model, browser veya worker çağrısı yapmaz.

Bu fixture'lar **gerçek canlı kabul/acceptance kanıtı değildir**. Üretim
sisteminin gerçekten research yaptığı, haber çektiği veya okunmamış hesap
verisi okuduğu iddia edilmez. Bunlar yalnız JarvisBench evaluator'ının mevcut
read-only capability case'leri üzerinde sürümlü ve tekrarlanabilir girdilerle
çalıştığını kilitleyen test verisidir. Bu fixture'ların validatörden PASS ile
geçmesi yalnız **benchmark girdisinin** (statik observation JSON'unun)
sözleşmeye uyduğunu gösterir; Core'un GoalState'ini, reducer'ını, CAS'ını ya
da Completion Policy'sini hiçbir şekilde değiştirmez veya onlara dokunmaz —
şema yükleyici bunların hiçbirini import etmez (`load_observations`/
`validate_observations` yalnız yerel JSON okur/doğrular).

### `validate_observations` / `load_observations`

- `validate_observations(payload, case_ids)`: zaten belleğe okunmuş bir
  observation payload'ını (dict) verilen case id kümesine karşı doğrular.
  Üst seviyede yalnız `version` ve `observations` alanlarına izin verir;
  `version` tam olarak `"v0"` olmalı. `observations` boş olmayan bir
  nesne/map olmalı. Her observation id'si geçerli, boş olmayan bir string
  olmalı ve yalnız `evidence`, `safety_outcome`, `permission_outcome`,
  `duration_ms` alanlarını taşımalı — `evidence` boş olmayan string listesi,
  `safety_outcome`/`permission_outcome` boş olmayan string, `duration_ms`
  bool olmayan negatif olmayan bir sayı olmalı. Observation id kümesi,
  verilen case id kümesiyle **birebir** eşleşmelidir; eksik, yabancı veya
  (kümeler birbirine denk gelecek şekilde) başka bir case'e ödünç
  verilmiş/taşınmış bir observation id'si fail-closed reddedilir —
  `BenchSchemaError` fırlatılır, hiçbir şey sessizce atlanmaz veya
  varsayılan bir değerle doldurulmaz.
- `load_observations(path, case_ids)`: yukarıdakinin dosya yolundan okuyan
  sürümü; sadece yerel dosya sistemini kullanır, ağ/model/hesap/worker
  çağrısı yapmaz.
- Bu fonksiyonlar worker çalıştırmaz, model/provider/ağ/browser/hesap
  çağrısı yapmaz ve GoalState/Reducer/CAS/Completion Policy'ye dokunmaz;
  yalnızca statik observation JSON'unu doğrular.

Kimlik eşlemesi de güvenlik sözleşmesinin parçasıdır: observation başka bir
case kimliği altında bulunursa hedef case `NO_OBSERVATION` ile FAIL olur;
başka case'in evidence'ı ödünç alınarak PASS üretilemez. Fixture testleri ayrıca
boş evidence'ın PASS olmadığını, yanlış safety/permission sonucunun FAIL
olduğunu ve eksik observation'ın `NO_OBSERVATION` ile fail-closed kaldığını
kilitler.

## Kapsam dışı

- `modules/goal_executor.py`, GoalState/reducer, Completion Policy
- CI/workflow/watcher entegrasyonu
- yeni worker, provider veya planner
- browser/CUA/Hermes
- canlı model, hesap, ağ veya dış etki (effect) çalıştırma

## Test

`tests/test_jarvis_bench.py` şema ve evaluator sözleşmesine ek olarak shipped
case kataloğu ile `jarvis_bench_v0_observations.json` fixture'larının kimlik
kümesini eşleştirir; üç read-only fixture'ın deterministik değerlendirmesini,
case/observation kimliği uyuşmazlığını, eksik evidence'ı, yanlış safety ve
permission sonucunu ve eksik observation'ı fail-closed olarak sınar.

Bu testler fixture'ları canlı acceptance yerine koymaz ve ağ/model/hesap
çağrısı yapmaz.
