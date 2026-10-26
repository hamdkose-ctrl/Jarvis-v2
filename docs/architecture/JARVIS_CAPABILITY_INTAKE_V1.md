# Jarvis Capability Intake v1

Bu belge, `Jarvis_Master_Hasat_Listesi`ndeki 705 adayın tamamını aynı anda
uygulama planına çevirmek için değil, yakın dönemde ele alınacak adayları aynı
ölçütle değerlendirmek içindir. Master liste korunur; bu belge yalnız ilk
dalganın karar kaydıdır. 705 maddenin tamamı ikinci dalgada
`JARVIS_CAPABILITY_INTAKE_WAVE2_V1.md` içinde kayda geçmiştir.

## Değişmez Core sınırı

Yeni bir capability aşağıdaki hattın dışında karar veya yan etki başlatamaz:

```text
Jarvis Core
→ DecisionContext / Permission / Effect Policy
→ Worker veya Adapter
→ WorkerResult + Evidence / Receipt
→ Core State Reducer / Completion Policy
```

Worker başarısı global tamamlanma değildir. Dış kod, skill, plugin, MCP veya
agent ikinci bir Core, GoalState yazarı ya da izin otorisi olamaz.

## Intake kapısı

Bir aday `AL` veya `UYARLA` olmadan önce şu kanıtlar gerekir:

1. Kaynak sürümü/commit'i ve lisansı sabitlenir.
2. Windows, Python, Node ve dependency uyumu doğrulanır.
3. Çalıştırma sınırı belirlenir: read-only, local write, external write veya
   physical.
4. Capability'nin Worker/Adapter bağlanma noktası belirlenir.
5. Permission, Effect, Evidence/Receipt ve Completion koşulları yazılır.
6. Gerçek acceptance/benchmark senaryosu belirlenir.

`AL`, doğrudan kontrolsüz import anlamına gelmez. Kaynak, sürüm ve güvenlik
kapısından sonra bile yalnız bir adapter sınırından kullanılır.

## Karar etiketleri

| Etiket | Anlamı |
|---|---|
| `AL` | Kanıtlı kaynak, lisans ve runtime uyumu var; adapter pilotuna alınabilir. |
| `UYARLA` | Yararlı fikir veya bileşen var; Jarvis sözleşmesine adaptasyon gerekir. |
| `BİZDEKİ KALSIN` | Mevcut Jarvis parçası stratejik baseline'dır; dış aday benchmark olarak kalır. |
| `ALMA` | Mevcut biçimiyle güvenlik/mimari/uyum şartını karşılamaz. |
| `ERTELENMİŞ` | Önkoşulu veya lifecycle tasarımı henüz yoktur. |

## İlk dalga: 20 aday

| # | Aday | Mevcut gerçek durum | Karar | Önkoşul / ilk acceptance |
|---|---|---|---|---|
| 1 | Completion Policy | Completion kontrolleri `goal_executor` içinde dağınık. | `UYARLA` | Worker success tek başına `done` olamaz. |
| 2 | Normalize failure fingerprint + replan budget | Turn bütçesi var; ortak fingerprint yok. | `UYARLA` | Yeni kanıt olmadan aynı hata tekrar etmez. |
| 3 | 429/Ollama/offline failure path | Router/cooldown var; bazı hedef çıktılarında ham hata yolu var. | `UYARLA` | Güvenli Türkçe sınıflama, ücretli fallback yok. |
| 4 | JarvisBench v0 | Ortak benchmark sözleşmesi yok. | `BİZDEKİ KALSIN` | Görev, kanıt, güvenlik ve süre metriği. |
| 5 | Read-only research/news worker | Kaynak/tarih/publisher doğrulaması kısmi mevcut. | `UYARLA` | Tek seferlik araştırma evidence veya waiting. |
| 6 | Legacy GoalState cutover | Compatibility projection sürüyor. | `UYARLA` | Canonical state tek kaynak; Completion pilotundan sonra. |
| 7 | UIA Computer observation | Calculator/Notepad odaklı dar pilot mevcut. | `BİZDEKİ KALSIN` | Pencere/UIA/screenshot gözlem benchmark'ı. |
| 8 | Dış CUA backend | Kaynak/sürüm/pin henüz kanıtlı değil. | `UYARLA` | Aynı PC görevlerinde UIA baseline'a karşı ölçüm. |
| 9 | Playwright Browser read-only | Dar approval'lı browser hattı mevcut. | `BİZDEKİ KALSIN` | Snapshot/DOM/evidence acceptance. |
| 10 | Hermes browser provider | Ayrı Hermes runtime'a bağlı. | `ERTELENMİŞ` | BrowserWorker adapter benchmark'ından sonra. |
| 11 | File/document read | Parçalı okuma/dönüşüm yolları mevcut. | `UYARLA` | Gerçek dosya → artifact/evidence zinciri. |
| 12 | Finance read-only | Kaynak/fiyat testleri mevcut, ayrı domain kararı var. | `UYARLA` | Freshness/source + yatırım tavsiyesi vermeme. |
| 13 | Skills manifest/discovery | Güvenli skill lifecycle yok. | `ERTELENMİŞ` | Sandbox, provenance ve read-only skill pilotu. |
| 14 | Plugin lifecycle | Eski `plugins.py` kullanıcı Python'unu doğrudan import eder. | `ALMA` | Bu mekanizma büyütülmez; güvenli plugin tasarımı gerekir. |
| 15 | MCP client | `capability_hub` referans kataloğudur, client değildir. | `ERTELENMİŞ` | Sandbox sonrası fixed read-only adapter. |
| 16 | Delegation/sub-agent | Specialist isimleri var; lifecycle/fencing yok. | `ERTELENMİŞ` | Completion + cutover sonrası bounded child result. |
| 17 | Kanban | Queue/heartbeat parçaları var; Core Job yerine geçemez. | `ERTELENMİŞ` | Delegation sonrası yalnız görünüm/koordinasyon. |
| 18 | Cron/durable subscription | Event altyapısı var, production subscription producer yok. | `ERTELENMİŞ` | Gerçek subscription lifecycle tasarımı. |
| 19 | Gmail/Calendar/Gateway write | Kısmi bağlantılar var. | `ERTELENMİŞ` | Exact target, intent, receipt, reconcile. |
| 20 | Social/physical/finance write | Yok veya dar prototip. | `ERTELENMİŞ` | `external_write` + receipt + gerçek acceptance. |

## Hermes değerlendirmesi

`NousResearch/hermes-agent` MIT lisanslıdır. Master listedeki `v0.22.5`
artık commit SHA'ya sabittir: `bf0203a794a07aac3ff764972ab9087baa4e4f4e`
(kanıt: `JARVIS_CAPABILITY_INTAKE_WAVE2_V1.md`).
Güncel Hermes ana dalı aktif değişir; kendi agent, gateway, Electron desktop,
plugin, skill ve delegation runtime'ını birlikte taşır. Ayrıca güncel bağımlılık
tanımları Python 3.14 merkezlidir; Jarvis Windows runtime'ı Python 3.13'tür.

Bu nedenle ilk karar `AL` değildir: Hermes, sürümü sabitlenmiş kaynak incelemesi
ve izole benchmark sonrası yalnız Worker/Adapter adayı olabilir. Doğrudan Jarvis
Core'un yerine veya içine import edilmez.

## Sıra

```text
Provider dayanıklılığı
→ Completion Policy + read-only research/news pilotu
→ Legacy GoalState cutover
→ JarvisBench v0
→ ComputerWorker read-only / CUA benchmark
→ BrowserWorker read-only
→ Sandbox → Skill/Plugin/MCP → Delegation
```

Bu belge yeni capability kurmaz; yalnız hangi adayın hangi güvenlik ve acceptance
kapısından geçeceğini sabitler.
