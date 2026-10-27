# Jarvis UI / Core Business Authority Boundary

**Kapsam:** Aşama 0–4 mimari sınırı  
**Amaç:** Web/desktop UI katmanının presentation/interaction rolünde kalmasını, business/decision/execution authority'nin canonical backend/Core'da yaşamasını garanti etmek.

## Canonical kural

UI business logic veya authority taşımaz. UI:

- canonical backend/Core sözleşmelerini çağırır,
- kullanıcı girdisini ve açık kullanıcı seçimini iletir,
- dönen state/evidence/result bilgisini gösterir,
- loading, sekme, görünürlük, renk/icon, basit form şekil doğrulaması gibi presentation/interaction mantığı içerebilir.

UI değişimi feature davranışını değiştirmemelidir. Provider/model fallback, permission ALLOW/DENY, GoalState lifecycle, Finance business/risk kararı, source conflict, worker routing, task completion, scheduler business rule, execution authority ve memory policy kararları UI katmanında tanımlanamaz.

Bu kural "UI hiçbir koşul yazamaz" anlamına gelmez. Örneğin backend'in `state='approval'` cevabına göre Onayla düğmesini göstermek presentation'dır; fakat bu onayın gerçekten geçerli olup olmadığına, hangi execution yoluna gideceğine veya hangi state geçişine izin verileceğine UI karar veremez. Backend aynı isteği UI olmadan da aynı canonical kurallarla değerlendirebilmelidir.

## Canonical contract prensibi

Yeni mega-schema kurulmaz. UI-facing özellikler mevcut canonical sözleşmeleri reuse eder. Alanın mevcut sözleşmesi izin veriyorsa UI örneğin şunları tüketebilir:

- Provider/model: `saved_model`, `effective_model`, `installed_models`, `fallback_active`, `reason`
- Permission: `decision`, `reason_code`, `requires_approval`, `scope`
- Research: `claims`, `sources`, `conflict`, `uncertainty`, `evidence`
- Finance: `facts`, `risk`, `decision`, `reason_code`

Bu alan adları yeni zorunlu ortak schema değildir; amaç kararın UI'da yeniden üretilmemesi, ilgili domain/Core sözleşmesinden gelmesidir.

## UI silinse testi

Definition of Done için presentation-only özellikler hariç şu soru zorunludur:

> Bu feature'ın mevcut UI katmanı tamamen silinse backend/core davranışı ve canonical sonucu yaşamaya devam eder mi?

Cevap "hayır" ise UI/Core business authority sınırı ihlal edilmiştir.

## Guard yaklaşımı

`modules.architecture_guard` UI Python bridge/shell dosyalarının statik `modules.*` import dependency edge'lerini AST ile inceler. Keyword, fonksiyon adı veya mesaj metni taramaz.

- `ARCH-006`: yeni bir UI dosyası Core business-authority modülüne doğrudan bağımlılık eklerse BLOCKER.
- `ARCH-W003`: bugün var olan, ayrı migration gerektiren exact UI→authority dependency edge'i baseline borcu olarak görünür kalır.
- Baseline dosya bazında genel izin değildir. Aynı dosyaya yeni authority dependency eklenirse `ARCH-006` olur.
- Presentation/query/configuration servisleri otomatik olarak business authority sayılmaz. Örneğin `ui_jobs` durum sorgusu veya backend state'ine göre UI render etme guard kapsamında yasak değildir.

Guard davranış doğruluğunu kanıtlamaz. Backend'in isteği gerçekten yeniden doğruladığı runtime/unit testlerle ayrıca kanıtlanır.

## Aşama 0–4 geriye dönük audit

Audit tabanı: `0352ce1c7b583d38b491a38301689d47928e7657` (`main`). İncelenen yüzey: `web.py`, `web_*.py`, `webui/`, `gui.py`, `main.py`, `launcher.py` ve bunların Aşama 0–4 Core bağımlılıkları.

| Faz | Sonuç | Kod kanıtı | Değerlendirme |
|---|---|---|---|
| Faz 0 | **VIOLATION** | `web_tasks.py::team_control` | UI bridge, goal/task control isteğinin geçerliliğini ve hangi lifecycle eyleminin iletileceğini kendisi değerlendiriyor. Bu gerçek business/execution authority; ayrı migration PR'ı gerekir. |
| Faz 1 | **PASS** | `web_models.py` user/provider ayar girişleri backend `llm`/`smart_router` servislerine delege ediliyor; auditte UI içinde bağımsız fallback/provider selection motoru bulunmadı. | Kullanıcı seçimi UI interaction'dır; automatic provider/fallback kararı Core'da kalmalıdır. |
| Faz 2 | **VIOLATION** | `web_tasks.py::team_control` | Approval state, control token ve task agent uygunluğu UI bridge içinde karar kapısı olarak kullanılıyor. UI yalnız approval isteğini canonical control servisine iletmelidir. |
| Faz 3 | **DEBT** | `web_tasks.py::team_control`, `web_tasks.py::team_verify` | UI doğrudan Goal/execution internallerini okuyor ve lifecycle/evidence yorumluyor. Audit sırasında doğrudan `goal_state_store` writer bulunmadı; canonical writer authority Core'da. Ayrı facade/service migration'ı gerekir. |
| Faz 4 | **DEBT** | `web_tasks.py::team_verify` | UI bridge hangi tamamlanmış çıktıları verify edeceğini seçip doğrulama sonuçlarını topluyor. Bu bugün task completion state'ini değiştirmiyor, bu yüzden kritik execution authority değil; canonical verification/query servisine taşınmalı. Faz 4 multi-source worker/roadmap koduna bu PR dokunmaz. |

Bitmiş Faz 0/2/3 yalnız eski roadmap metni nedeniyle yeniden açılmamıştır; yukarıdaki sonuçlar güncel kodun UI/Core sınırı açısından ayrı mimari audit sınıflandırmasıdır.

## Bulgular

### A — Kritik

1. `web_tasks.py::team_control`
   - UI bridge `goal_executor.latest`, `goal_executor.control_key`, `task_agents._load` ve task/goal state alanlarını kullanarak `cancel/resume/approve/answer` akışının geçerliliğine karar veriyor.
   - Task approval için bekleyen step/receipt eşleşmesini ve `publish|browser` agent sınırlamasını UI bridge değerlendiriyor.
   - Neden kritik: UI değişikliği backend'e hangi kontrol isteğinin ulaşacağını ve hangi lifecycle/approval akışının kabul edileceğini değiştirebilir.
   - Ayrı PR: **Evet.** Canonical backend control service/facade oluşturulmalı veya mevcut Core entrypoint reuse edilerek `web_tasks.py` yalnız input iletmelidir.

### B — Teknik borç

1. `web_tasks.py::team_verify`
   - UI bridge job/output seçimi yapıyor ve `goal_tools.verify` / `task_results.verify` sonuçlarını kendi döngüsünde birleştiriyor.
   - Şu an canonical task completion state'i değiştirmediği için güvenli borç; fakat UI silinse bu verification use-case'i de kayboluyor.
   - Ayrı PR: **Evet.** Read-only canonical verification/query service'e taşınmalı.

2. `web_tasks.py` direct authority dependencies
   - `goal_executor`, `goal_tools`, `task_agents`, `task_results`, `execution_record` dependency edge'leri `ARCH-W003` baseline olarak sabitlendi.
   - Baseline yalnız mevcut borcu görünür tutar; yeni dependency edge'ine izin vermez.

### C — Normal presentation / interaction

- `web.py::Hub`: backend olaylarını SSE istemcilerine dağıtma, activity/feed görünümü tutma.
- `web.py::_self_action`: nav/widget/window gösterimi ve UI restart interaction'ı.
- `web.py::Sampler`: UI için CPU/bellek/ağ/hava durumu ölçümü ve gösterim state'i.
- `web_models.py::llm_status`: backend status contract'ını UI'ya taşıma.
- `web_models.py` user-selected provider/model ayarlarının backend setter/configuration servislerine iletilmesi; automatic fallback kararı UI'da yapılmadığı sürece interaction'dır.
- `webui/team-center.js`: backend state'e göre buton, label, loading ve görünürlük seçimi. Butonun görünmesi authority değildir; backend her control isteğini canonical olarak yeniden doğrulamak zorundadır.
- `gui.py`: Komut Merkezi'ni başlatma ve açılış hatasını gösterme.
- `launcher.py`: startup/recovery supervisor; ürün feature business authority'si değildir.
- `main.py`: UI değil, authoritative `EngineContext` için compatibility facade'dır.

## Gelecek UI'lar

Yeni hologram, web veya desktop UI aynı canonical backend contract'larını tüketir. UI katmanı yeni provider router, permission gate, GoalState reducer, Finance karar motoru, source-conflict resolver, worker router veya completion authority kuramaz.

Yeni UI ihtiyacı Core'da olmayan bir karar gerektiriyorsa çözüm UI içinde karar yazmak değil, ilgili domain/Core'da canonical contract oluşturmak veya mevcut contract'ı genişletmektir.
