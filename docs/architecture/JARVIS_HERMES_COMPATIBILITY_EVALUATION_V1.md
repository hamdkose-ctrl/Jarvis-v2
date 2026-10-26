# Jarvis ↔ Hermes Teknik Uyumluluk ve İzolasyon Değerlendirme Sözleşmesi v1

**Durum:** Değerlendirme sözleşmesi taslağı — bağlayıcı intake/izolasyon kapısı.
**Kapsam:** Bu belge yalnız Hermes'in (NousResearch/hermes-agent sınıfı dış
agent runtime'ı) Jarvis sürecine **doğrudan import edilmeden önce** geçmesi
gereken teknik uyumluluk ve izolasyon değerlendirme kriterlerini tanımlar.

Kapsam dışında kalanlar: Hermes'in gerçek clone/install/import işlemi,
dependency/requirements değişikliği, worker/runtime/permission/GoalState kodu,
CI/watcher/AGENTS.md/test değişikliği. Bu belge hiçbirini başlatmaz; yalnız
"geçmeden önce karşılanması gereken kapı"yı yazar.

**İlişkili belgeler:**
- `docs/architecture/JARVIS_CAPABILITY_INTAKE_V1.md` — Hermes'in ilk dalga
  kararı (`ERTELENMİŞ`/değerlendirme) ve "Intake kapısı" genel kriterleri.
- `docs/architecture/JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md` — Hermes kabul
  edilse bile hangi Core kararlarını asla üstlenemeyeceği (adapter authority
  sınırı). Bu belge onunla **çelişmez**: adapter boundary "kabul edilirse ne
  yapamaz"ı, bu belge "kabule giden yolda hangi kanıt ve izolasyon gerekir"i
  tanımlar. İkisi birlikte okunur.
- `docs/architecture/JARVIS_EXECUTION_ARCHITECTURE_V1.md` — Core'un tek
  decision/completion authority olduğu ana mimari (§3, §5.1, §6, §10–§13,
  §15, §30, §31).

---

## 1. Kaynak/doğrulama kanıtı

### 1.1 Repo, lisans, ref — doğrulanan kısım

Aşağıdaki kanıt bu değerlendirme sırasında (2026-10-25, web araması ve GitHub
sayfası taraması ile) doğrulanmıştır:

| Alan | Doğrulanan değer | Kanıt |
|---|---|---|
| Repo URL | `https://github.com/NousResearch/hermes-agent` | GitHub repo sayfası; ayrıca `https://hermes-agent.nousresearch.com` resmî doküman sitesi bu repoyu kaynak olarak gösterir. |
| Lisans | MIT (`LICENSE` dosyası repo kökünde) | Repo sayfasındaki "License: MIT" rozeti ve "License — MIT, see LICENSE" bölümü; ayrıca geçmişte "fix: restore missing MIT license file" commit'i. |
| main HEAD (doğrulama anında) | `571a5911ae6aaa05ef3df53bf0f6720c4556c24a` (40 karakter hex, "fix(gateway): a process watcher runs in its owning profile's scope..." — Oct 24 2026) | GitHub repo sayfasının "Latest commit" bloğu. |
| Repo ölçeği | 58.286+ commit, 2644 branch, 221 tag (doğrulama anında) | Aynı sayfa. |
| Python (installer) | Kurulum betiği Python 3.14'ü PM (paket yöneticisi) üzerinden kendi kurar ("The source installer delegates Python 3.14, Node.js, npm, ripgrep, FFmpeg, and Python dependencies to PM"). | `hermes-agent.nousresearch.com/docs/guides/python-library` ve repo README kurulum bölümü. |
| Windows desteği | README: "Windows: Native Windows is fully supported — the PowerShell one-liner above installs everything." Ayrıca `docker-compose.windows.yml`, `hermes_dir_acl.py`, `runtime_bootstrap_windows.py`, `gateway_windows.py` gibi Windows'a özgü modüller mevcut. | Repo README ve dosya ağacı. |

### 1.2 BLOCKED: master listedeki `v0.22.5` sabit referansı doğrulanamadı

`JARVIS_CAPABILITY_INTAKE_V1.md`'nin Hermes değerlendirmesi, master listedeki
adayın `v0.22.5` olarak kayıtlı olduğunu belirtir. Bu değerlendirme sırasında:

- Hermes repo'sunun **gözlemlenen** release/tag biçimi tarih tabanlıdır
  (örn. `v2026.7.7`, `v2026.9.7`), `v0.22.5` biçiminde semver değildir.
- Bu nedenle master listedeki `v0.22.5` etiketi ile repodaki gerçek tag
  şeması arasında bir **uyuşmazlık** gözlenmiştir; bu değerlendirme bunu
  düzeltmez, yalnız kaydeder.

**BLOCKED: `v0.22.5` referansı bu depoda doğrulanamadı — gözlemlenen tag
şemasıyla (`v2026.X.Y`) uyuşmuyor.** Gerçek bir benchmark turu başlamadan
önce şu adım zorunludur: master listedeki referansın hangi gerçek tag'e
karşılık geldiği netleştirilmeli veya master liste kaydı güncellenmelidir.
Bu netleştirme olmadan hiçbir pilot, "doğrulanmış sürüm" iddiasıyla
başlayamaz (madde 2, aşağıda).

**Çözüldü (2026-10-26):** `v0.22.5` tag'i upstream'de bulundu ve commit
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`'ye sabitlendi. Lisans,
`requires-python` ve tag kanıtı `JARVIS_CAPABILITY_INTAKE_WAVE2_V1.md`
"Hermes sürüm referansı" bölümündedir. Yukarıdaki BLOCKED kaydı tarihçe
olarak korunur.

### 1.3 Ref sabitleme kuralı (ileride yapılacak her pilot için)

- `main` HEAD **asla** benchmark referansı olarak kullanılmaz: repo saatte
  birden fazla commit alıyor (doğrulama anında son commit "39 dakika önce");
  `main`'e pin etmek tekrarlanabilir bir ölçüm sağlamaz.
- Benchmark yalnız **imzalı bir release tag'ine** (örn. `v2026.9.7` veya daha
  yenisi, doğrulama zamanında güncellenmiş hâli) veya o tag'in tam commit
  SHA'sına pinlenir.
- Seçilen tag/SHA, lisans dosyasının içeriği (MIT metni, telif satırı) ve
  `requires-python`/kurulum betiğinin o tag'deki tam hâliyle birlikte
  değerlendirme kaydına **eklenir**; yalnız URL yetmez.

---

## 2. Python sürümü, Windows uyumluluğu, bağımlılık yüzeyi

| Boyut | Hermes (gözlem) | Jarvis Windows runtime | Uyum durumu |
|---|---|---|---|
| Python | Kurulum betiği Python 3.14'ü kendi yönetir; ayrıca bir commit mesajı "core modules import again on Python 3.11-3.13" diyerek bazı modüllerin 3.11–3.13 ile de çalıştığını ima eder (ayrıntı doğrulanmadı). | Python 3.13 (sabit, `requirements.lock.txt`). | **Uyumsuz/belirsiz.** Hermes'in varsayılan kurulum yolu 3.14 hedefler; Jarvis 3.13'tedir. Hangi alt modüllerin 3.13 ile çalıştığı ayrı kanıt gerektirir — tahmin edilmez. |
| Node/npm | Kurulum betiği Node.js ve npm'i de kurar (Electron desktop app, gateway). | Jarvis'in çekirdek runtime'ı Node'a bağımlı değildir (yalnız `webui/*.js` davranış testleri Node ile çalışır). | Jarvis için ek, izole bir bağımlılık yüzeyi — ana sürece eklenmez. |
| Paket yöneticisi | Kendi "PM" aracı (Hermes'e özel), pip/uv/Playwright/Chromium/FFmpeg/ripgrep gibi birçok ikili indirir. | Jarvis `requirements.lock.txt` + `pip --no-deps` disiplinini kullanır (`scripts/linux_test_kurulum.sh`). | Hermes'in kendi PM'si Jarvis'in kilitli pip disiplinine **asla** karışmaz; ayrı sanal ortam/worktree şarttır (bkz. §3). |
| Yüzey genişliği | Monorepo: agent, gateway, Electron desktop, CLI, cron, browser automation (Playwright/Chromium), optional-mcps, Docker, Windows-native paket. | Jarvis tek süreçli masaüstü asistanı + web arayüzü. | Hermes'in yüzeyi Jarvis'in ihtiyacından kat kat büyük; yalnız kullanılacak **tek bir** alt yüzey (örn. browser worker) izole edilmeden bütün paket asla kurulmaz. |
| Windows | README "fully supported" diyor; Windows'a özgü modüller var ama antivirüs/Defender `uv.exe` false-positive uyarısı gibi bilinen sürtünmeler de dokümante. | Jarvis hedefi Windows. | Native destek iddiası var; gerçek PC'de doğrulama olmadan "sorunsuz" kabul edilmez. |

Bu tablo **doğrulanmış gözlem**dir, kabul kararı değildir. Intake kapısının
madde 2'si ("Windows, Python, Node ve dependency uyumu doğrulanır") bu
tabloyla kısmen karşılanır; tam karşılanması için §4'teki izole
benchmark zorunludur.

---

## 3. Jarvis process'ine doğrudan importun neden yasak olduğu

`JARVIS_CAPABILITY_INTAKE_V1.md`'nin "Değişmez Core sınırı" bölümü ve
`JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md` §1–§2 zaten bağlayıcıdır: dış kod,
skill, plugin, MCP veya agent ikinci bir Core, GoalState yazarı ya da izin
otoritesi olamaz. Bu değerlendirme bunu, **Hermes'in somut özellikleriyle**
teknik gerekçeye bağlar:

1. **Kendi karar/execution motoru taşır.** Hermes kendi agent, gateway,
   cron, Electron desktop ve delegation runtime'ını birlikte taşıyan bir
   monorepo'dur (§1.1, §2). Jarvis'in ana sürecine import edilirse, bu
   motorun kendi iç durumu (`TurnRunner`, gateway profile scope, process
   watcher, cron delivery) Jarvis'in `goal_state.v1`/Core State Reducer
   hattının **dışında** ikinci bir yürütme otoritesi olarak çalışır —
   `JARVIS_EXECUTION_ARCHITECTURE_V1.md` §3'teki dokuz münhasır Core
   kararının (kim, ne, tek/çok adım, hangi domain, hangi izin, hangi durum,
   yeniden deneme/uzlaşma, tamamlanma, teslim) hiçbirini devretmez.
2. **Bağımlılık yüzeyi çakışır/taşar.** Hermes kendi PM'si ile pip, uv,
   Playwright/Chromium, FFmpeg, ripgrep, Node/npm kurar; Jarvis'in kilitli
   `requirements.lock.txt` + `--no-deps` disiplini (bkz. `AGENTS.md`,
   "Linux test ortamı" notu) bununla aynı ortamda **çakışır**. Doğrudan
   import, Jarvis'in kendi kilitli sürüm garantisini bozar.
3. **Python sürüm uyuşmazlığı riski.** Hermes'in varsayılan kurulum hedefi
   Python 3.14; Jarvis'in çalışan Windows runtime'ı 3.13'tür (§2). Doğrudan
   import, ya Jarvis'in sürümünü zorla değiştirir ya da Hermes'in doğrulanan
   kurulum yolunun dışına çıkarak **doğrulanmamış** bir konfigürasyonla
   çalışır.
4. **Permission/Effect/Evidence sözleşmesi yoktur.** Hermes'in kendi tool
   çağırma, browser otomasyonu, dosya/süreç erişimi mekanizmaları
   Jarvis'in `permission_gate.py`/`effect_journal.py`/`worker_result.py`
   fence'lerinden habersizdir. Doğrudan import, bu üç immutable mekanizmayı
   (bkz. `JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md` §8) atlayan bir yan kapı
   açar — kasıt olmasa bile, yalnızca iki sistemin aynı süreçte aynı
   kaynaklara (dosya, ağ, süreç) erişmesinden dolayı.
5. **Antivirüs/sürtünme yüzeyi Jarvis'in güven sınırına girer.** `uv.exe`
   gibi bilinen false-positive sürtünmeleri (§2) Jarvis'in kendi süreciyle
   aynı prosese girerse, Jarvis'in kullanıcı güveni ve kurulum kararlılığı
   (`AGENTS.md`: "Tek paket kurulum... çalışan `.venv` değişmez") de bu
   sürtünmeyi miras alır.

Sonuç: doğrudan import, hem mimari (ikinci karar otoritesi) hem pratik
(bağımlılık/sürüm/antivirüs çakışması) nedenlerle kapalıdır. Hermes yalnız
izole bir ortamda, ayrı bir süreç sınırının **ardında** değerlendirilebilir.

---

## 4. İzole worktree/venv benchmark gereksinimi

Hermes'in herhangi bir gerçek kodu çalıştırılmadan önce şu izolasyon
şarttır:

1. **Ayrı dizin/worktree.** Hermes clone'u Jarvis repo ağacının **dışında**,
   kendi dizininde tutulur; Jarvis `git worktree` veya `.claude/worktrees`
   altına Hermes kaynağı **eklenmez**.
2. **Ayrı Python sanal ortamı.** Jarvis'in `.venv` / `requirements.lock.txt`
   kilidiyle **paylaşılmayan**, Hermes'in kendi PM'sinin kurduğu ayrı bir
   venv/araç zinciri kullanılır. Jarvis'in kilitli paketleri bu venv'e
   sızmaz, Hermes'in paketleri Jarvis'in venv'ine sızmaz.
3. **Ağ ve dosya sistemi sınırı.** Benchmark, Hermes'in gateway/cron/
   Electron desktop gibi arka planda kalıcı süreç başlatan bileşenlerini
   **devre dışı** tutar; yalnız değerlendirilecek tek alt-yüzey (örn.
   browser worker adayı) izole çalıştırılır.
4. **Kimlik bilgisi yalıtımı.** Hermes'in kendi API key/credential
   mekanizması Jarvis'in `~/.jarvis` kullanıcı anahtar deposuna **asla**
   erişmez; benchmark sırasında yalnız tek kullanımlık, gerçek kullanıcı
   verisi içermeyen test kimlik bilgileri kullanılır.
5. **Geri alınabilirlik.** İzole ortam bütünüyle silinebilir olmalı; Jarvis
   deposuna, Jarvis'in `.venv`'ine veya kullanıcı profiline hiçbir kalıcı
   iz bırakmamalıdır (kurulum sonrası "diff" boş olmalı).
6. **PC watcher/CI'dan ayrı.** Bu izole benchmark, Jarvis'in gerçek PC
   kabul watcher'ından veya CI'ından bağımsız çalışır; bu belge CI/watcher
   davranışını değiştirmez (kapsam dışı, bkz. görev tanımı).

Bu beş/altı şart karşılanmadan "Hermes'i bir kez denedim, çalıştı" türü bir
gözlem **kanıt sayılmaz**.

---

## 5. Ağ, model, dosya, browser, PC ve dış-effect sınırları

İzole benchmark sırasında dahi şu sınırlar geçerlidir — bunlar Hermes'in
kendi varsayılanları ne olursa olsun **zorunlu kısıtlamalardır**:

| Sınır alanı | Kural |
|---|---|
| Ağ | Benchmark yalnız değerlendirilen alt-yüzeyin ihtiyaç duyduğu minimum ağ erişimine izin verir (örn. sadece browser worker testinde hedef test sayfası). Hermes'in kendi gateway/cron/Telegram/Discord adaptörleri **kapalı** tutulur. |
| Model | Hermes'in kendi model çağrıları (varsa) test boyunca **gerçek ücretli API anahtarı kullanmaz**; mock/stub veya tek kullanımlık ücretsiz kota tercih edilir. Jarvis'in kullanıcıya özel Gemini/Groq anahtarları Hermes'e **asla** verilmez (`AGENTS.md`: "Anahtarlar kullanıcıya özeldir"). |
| Dosya | Hermes, test dizini dışında Jarvis kullanıcı dosyalarına (Masaüstü/Belgeler/İndirilenler) veya `~/.jarvis` içine **okuma/yazma yapmaz**. |
| Browser | Browser worker adayı değerlendiriliyorsa, yalnız **read-only** gözlem/snapshot (Jarvis'in mevcut Playwright read-only hattıyla aynı disiplin, bkz. intake #9) test edilir; form gönderme, giriş yapma, ödeme gibi external_write senaryoları bu değerlendirmede **test edilmez**. |
| PC | Hermes'in Electron desktop / native PC entegrasyonu bu değerlendirme kapsamında **hiç çalıştırılmaz**; bu oturumda bağlı bir Windows cihazı da yoktur (bilinen ortam kısıtı). |
| Dış effect | Mail gönderme, dosya silme, dış hesap değiştirme, fiziksel komut gibi hiçbir gerçek dış etki, bu değerlendirme sırasında **başlatılmaz**. Hermes'in effect benzeri çıktıları (varsa) yalnız loglanır, asla yürütülmez. |

Bu sınırların herhangi biri ihlal edilirse (örn. Hermes'in gateway'i arka
planda bir port açıp dinlemeye devam ederse) değerlendirme **otomatik olarak
FAIL** sayılır (bkz. §6).

---

## 6. Ölçülecek başarı/fail-closed ölçütleri

Değerlendirme, JarvisBench v0 (`docs/architecture/JARVIS_BENCH_V0.md`)
disipliniyle aynı mantıkla **PASS/FAIL/INCONCLUSIVE** üretir; "çalıştı
gibi görünüyor" bir sonuç değildir.

### 6.1 Kurulum/izolasyon ölçütleri (zorunlu ön koşul)

- [ ] Hermes, Jarvis deposunun dışında, ayrı bir dizinde clone edildi.
- [ ] Hermes, Jarvis'in `.venv`/kilitli paketlerinden tamamen ayrı bir
      ortamda çalıştı (paket listesi karşılaştırmasıyla kanıtlanır).
- [ ] Kurulum/test sonrası Jarvis deposunda ve Jarvis `.venv`'inde hiçbir
      dosya değişikliği yok (`git status` + `pip freeze` diff'i boş).
- [ ] Hermes süreci test sonunda tamamen sonlandırıldı; arkada kalıcı
      süreç/port/cron görevi kalmadı.

Bu dört madde FAIL olursa, aşağıdaki hiçbir ölçüt değerlendirilmez —
izolasyon ihlali **fail-closed** olarak doğrudan reddir.

### 6.2 Uyumluluk ölçütleri

| Ölçüt | PASS koşulu | FAIL koşulu |
|---|---|---|
| Python uyumu | Hedeflenen alt-yüzey, Jarvis'in çalıştığı Python 3.13 ile (veya izole 3.14 ortamında ama 3.13 davranışıyla tutarlı şekilde) hatasız import/çalışır. | Import hatası, sürüm uyuşmazlığı hatası veya yalnız 3.14'e özgü sözdizimi/API'ye bağımlılık. |
| Bağımlılık izolasyonu | Hermes'in kendi PM'si yalnız kendi venv'ine kurulum yaptı. | Hermes kurulumu Jarvis'in kilitli `requirements.lock.txt` paket sürümlerinden birini bozdu veya sistem genelinde bir paket değiştirdi. |
| Windows kabulü (yalnız gerçek PC'de) | README'nin "native Windows" iddiası gerçek bir Windows makinede doğrulandı. | Bu oturumda bağlı Windows cihazı yok → bu madde **INCONCLUSIVE** kalır, PASS iddia edilmez. |
| Davranış kanıtı | Değerlendirilen tek alt-yüzeyden (örn. browser read-only) gerçek bir evidence (ekran görüntüsü, DOM snapshot, log) üretildi ve manuel incelemeyle doğrulandı. | Evidence yok, yalnız "exit code 0" veya "hata vermedi" gibi dolaylı kanıt. |
| Effect sızıntısı | §5'teki hiçbir sınır ihlal edilmedi (ağ/dosya/browser/PC/effect günlükleri temiz). | Herhangi bir gerçek dış effect (ağ çağrısı hariç izinli test sayfası, dosya yazma, vb.) tespit edildi. |

### 6.3 Sonuç sınıflandırması

- **PASS:** §6.1'in tamamı + §6.2'deki ilgili tüm ölçütler karşılanmış,
  Windows hariç (Windows için ayrı PC turu gerekir).
- **FAIL:** §6.1'den herhangi biri ihlal edilmiş, veya §6.2'de bir
  "FAIL koşulu" gözlenmiş.
- **INCONCLUSIVE:** Gerekli ortam (örn. gerçek Windows PC) bu turda yok;
  iddia edilmez, yalnız kaydedilir ve resmî PC turuna bırakılır.

Hiçbir ölçüt "muhtemelen çalışır" gibi tahmine dayalı olarak PASS
işaretlenemez; kanıtsız ölçüt INCONCLUSIVE kalır.

---

## 7. Kabul edilse bile yalnız Worker/Adapter adayı olacağı

Bu madde `JARVIS_CAPABILITY_INTAKE_V1.md`'nin Hermes kararını ve
`JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md`'nin tüm gövdesini (§2–§10)
**değiştirmeden** teyit eder:

- Değerlendirme §1–§6'dan tamamen PASS geçse bile, Hermes Jarvis Core'un
  **yerine veya içine** import edilmez.
- Tek mümkün sonuç: `JARVIS_EXECUTION_ARCHITECTURE_V1.md` §5.1'deki
  "Worker" rolüne, tek bir `capability_id` arkasında, mevcut
  Permission/Effect/WorkerResult/Reducer zincirine tabi bir **Worker/Adapter
  adayı** olarak pilota girmek.
- Bu adapter, GoalState yazamaz, permission veremez, effect başlatamaz,
  global done/completed kararı veremez ve immutable fence/Reducer/CAS
  hattını bypass edemez (adapter boundary belgesi §4–§8, aynen geçerli).
- Bu belge, o pilotun **kendisini** başlatmaz; yalnız pilotun önündeki
  teknik/izolasyon kapısını tanımlar.

---

## 8. Reddedilme/ertelenme koşulları

Aşağıdaki durumlardan **herhangi biri** gerçekleşirse Hermes adaylığı
`ALMA` (reddedilme) veya `ERTELENMİŞ` (erteleme) statüsüne döner:

### 8.1 `ALMA` (kesin ret) koşulları

- İzole ortamda Hermes kurulumu Jarvis'in kilitli bağımlılık sürümlerini
  bozduğu veya sistem genelinde yan etki yarattığı kanıtlanırsa.
- Hermes'in değerlendirilen alt-yüzeyi, test sırasında §5'teki herhangi bir
  sınırı (gerçek dış effect, izinsiz ağ/dosya erişimi, kalıcı arka plan
  süreci) ihlal ederse.
- Lisans metninin (MIT) depo kökünde fiilen bulunmadığı veya değiştirildiği
  (telif/izin koşulunun MIT'ten farklı olduğu) ortaya çıkarsa.
- Seçilen alt-yüzeyin Jarvis'in zaten `BİZDEKİ KALSIN` statüsünde tuttuğu
  bir yeteneği (örn. Playwright read-only browser, intake #9) kayda değer
  bir fayda sağlamadan tekrar ettiği kanıtlanırsa.

### 8.2 `ERTELENMİŞ` (erteleme) koşulları

- §1.2'deki `v0.22.5` ↔ gerçek tag şeması uyuşmazlığı çözülmeden bir pilot
  başlatılmak istenirse — önce master liste kaydı netleştirilir.
- Python 3.14 (Hermes varsayılanı) ile 3.13 (Jarvis) arasındaki fark, ilgili
  alt-yüzey için ayrı bir uyumluluk kanıtıyla kapatılmadan.
- Gerekli izole worktree/venv ortamı (§4) bu oturumda veya herhangi bir
  oturumda kurulamazsa (örn. ağ/paket erişimi engellenmişse) — bu durumda
  değerlendirme INCONCLUSIVE kalır ve bir sonraki uygun ortama ertelenir.
- Windows'a özgü kabul (§6.2, "Windows kabulü" satırı) gerçek bir PC
  turunda doğrulanmadan — bu madde PASS'e dönüşene kadar pilot
  "tam kabul edildi" sayılmaz, yalnız "bulut tarafı PASS, PC tarafı
  bekliyor" olarak kaydedilir.
- `JARVIS_CAPABILITY_INTAKE_V1.md`'nin sıra listesindeki önkoşul adımları
  (Completion Policy, Legacy GoalState cutover, JarvisBench v0, ComputerWorker/
  BrowserWorker read-only, Sandbox) henüz tamamlanmamışsa — Hermes sırası
  bu önkoşulların **sonrasıdır**, önüne geçemez.

### 8.3 Yeniden değerlendirme

Reddedilme veya erteleme bir kez karara bağlandığında, yeni bir pilot
talebi yalnız şu değişikliklerden biriyle yeniden açılabilir: (a) reddin
somut nedeni giderildi ve yeni kanıtla belgelendi, (b) önkoşul sıradaki bir
adım tamamlandı, (c) gerçek Windows PC turu artık mevcut. Eski kanıt
yeniden kullanılmaz; her yeniden değerlendirme kendi tazeliğini kanıtlar.

---

## 9. Bu belgenin kapsamı ve yapmadıkları

Bu belge:

- Hermes'i clone etmez, kurmaz, import etmez veya çalıştırmaz.
- Worker/runtime/permission/GoalState kodu yazmaz.
- CI, watcher, `AGENTS.md` veya test davranışını değiştirmez.
- `JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md`'nin tanımladığı adapter authority
  sınırını yeniden tanımlamaz veya gevşetmez; yalnız ona giden intake/
  izolasyon kapısını somutlaştırır.
- Master listedeki `v0.22.5` tutarsızlığını çözmez; yalnız BLOCKED olarak
  kaydeder ve çözülmeden pilot başlamaması gerektiğini belirtir.

Gelecekte bir Hermes benchmark/pilot turu başlatılırsa, o tur bu belgedeki
her bölümü (§1–§8) karşıladığını kanıtlamadan `AL` statüsüne geçemez; kanıt
`JARVIS_CAPABILITY_INTAKE_V1.md`'nin intake kapısı ve
`JARVIS_EXECUTION_ARCHITECTURE_V1.md` §30 "Yeni capability kabul standardı"
listesiyle aynı disiplinde sunulur.
