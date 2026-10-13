# Geliştirme ortamı (Claude Code araçları)

Bu rehber, Jarvis'i başka bir bilgisayarda aynı düzenle geliştirmeye devam etmek içindir. Uygulamanın içindeki geliştirme modu için bkz. [GELISTIRME_MODU.md](GELISTIRME_MODU.md). Çalışma kuralları [AGENTS.md](../AGENTS.md) dosyasındadır.

## Git durumu (önemli)

- GitHub bağlantısı kuruldu (`origin` = `hamdkose-ctrl/Jarvis`); geliştirme düzeni değişiklikleri PR #47 ile `main`'e birleşti (`28ec38e`). Yerel `ilk-kurulum` ve `gelistirme-duzeni` dalları uzak geçmişle ortak atası olmayan eski köktür; silinmez, uzak `main`'e birleştirilmez.
- **Force push yapılmaz, geçmiş değiştirilmez, yeni `main` açılmaz, uzak `main`'e doğrudan yazılmaz.** Dalı GitHub'a göndermek ve PR açmak Hamdi'nin ayrı onayıyla yapılır.
- Satır sonları dosya başınadır: uzak depoda metin dosyaları LF, `.bat` dosyaları CRLF'dir (`.gitattributes`: `*.bat -text`). Yerelde `core.autocrlf=true` olduğu için dosyayı toptan yeniden yazma; yalnız ilgili satırları değiştir ve `git diff --stat` ile gereksiz satır sonu farkı olmadığını doğrula.
- Her iş ayrı dalda yürür (ör. `codex/<konu>-<tarih>`). `main`'e doğrudan yazılmaz.
- Bu depodaki `git yükle` (Jarvis'in kendi yayını) ve GitHub güncelleyicisi yalnız tanımlı uzantıları kabul eder; `.ps1` dosyaları o listede yoktur. `tools/claude/kur-ajanlar.ps1` bu yüzden Jarvis üzerinden değil, yalnız Git ile taşınır.
- Depoyu GitHub'sız taşımak için (USB, ağ klasörü): bu bilgisayarda `git bundle create jarvis.bundle --all`, diğer bilgisayarda `git clone jarvis.bundle Jarvis`. Bundle yalnız commit'lenmiş dosyaları içerir (anahtar, ayar, veritabanı yoktur).

## Hangi araç ne işe yarar

| Araç | Ne yapar | Nerede durur |
|---|---|---|
| **jarvis-kural-denetcisi** | Değişikliği AGENTS.md ve `MIMARI_KURALLAR_v5.7.md`'ye göre denetler; yalnız rapor yazar, dosya değiştirmez | Asıl dosya `tools/claude/agents/` (Git'te); kurulu kopya `.claude/agents/` (Git dışı) |
| **Headroom** | Claude Code isteklerini yerel bir proxy üzerinden sıkıştırır (token tasarrufu) | `uv tool` ile ayrı ortam; `.venv`'den bağımsız |
| **Task Observer** | Oturumlarda gözlem kaydı tutar, kural değişikliği *önerir* | Kullanıcı düzeyi skill + SessionStart kancası; pakete girmez |
| **claude-mem** | Oturumlar arası hafıza | Claude Code eklentisi; veritabanı pakete girmez |
| **claude-code-setup** | Otomasyon önerileri | Claude Code eklentisi |

## Denetçi ajanı

- Kullanım: "jarvis-kural-denetcisi ile değişiklikleri denetle" veya `claude -p "değişiklikleri denetle" --agent jarvis-kural-denetcisi` (proje klasöründe).
- **Yalnız açık istekle veya PR açmadan hemen önce çalışır.** Kendiliğinden çağrılmaz; her çalıştırma model kotası harcar.
- Kontroller: kullanıcılar arası anahtar yedeği, ücretli sağlayıcı havuzu, yeni Gemini çağrısı/kota, ses ayarları, AGENTS.md güncelleme şartı, genel kurallar.
- Araçları `Read, Grep, Glob, Bash`; düzenleme aracı yoktur. Bash yalnız okuma amaçlı `git` komutları için kullanılır (bu bir talimattır, teknik kilit değildir).
- Dosyayı değiştirirken yalnız `tools/claude/agents/jarvis-kural-denetcisi.md` düzenlenir, sonra kur betiği çalıştırılır.

### Kurulum

Depo kökünden, PowerShell'de:

```powershell
powershell -ExecutionPolicy Bypass -File tools\claude\kur-ajanlar.ps1
```

- Betik depo kökünü kendi konumundan bulur; kullanıcıya özel yol içermez.
- `tools/claude/agents/*.md` dosyalarını `.claude/agents/` klasörüne kopyalar.
- Aynı dosya varsa "Guncel" der; farklıysa önce `.claude/yedek/agents-<zaman>/` altına yedekler, sonra kurar. İstediğin kadar tekrar çalıştırılabilir.
- Ne yapacağını görmek için `-WhatIf` ekle (hiçbir dosya yazılmaz).
- Claude Code açıksa yeniden başlat; ajan listesi açılışta okunur.
- Ajan dosyaları **LF** satır sonuyla kurulmalıdır: CRLF'li (`---\r\n`) başlık Claude Code'da "agent not found" hatası verir. `.gitattributes` kaynağı LF çıkarır, betik de kopyalarken CRLF'yi LF'ye çevirir ve baştaki BOM'u atar; `name:` yalnız ilk iki `---` arasındaki başlıkta aranır (başlık uzunluğu sınırı yoktur; kapanış `---` bulunamazsa dosya uyarıyla atlanır). Ajan görünmüyorsa `.claude/agents/` kopyasındaki satır sonunu kontrol et ve betiği yeniden çalıştır.
- `.claude/` `.gitignore` ile Git dışındadır ve öyle kalmalıdır.

## Headroom

Kurulum (Jarvis'in `.venv`'ünden ayrı; `uv` gerekir, yoksa [uv belgesi](https://docs.astral.sh/uv/)):

```powershell
uv tool install --python 3.13 "headroom-ai[proxy]"
uv tool update-shell        # PATH'e ekler; yeni terminal aç
headroom --version
```

Başlatma (proxy, komut çalıştığı sürece açık kalır; terminali kapatma):

```powershell
cd <Jarvis klasörü>
headroom wrap vscode-claude
```

- Komut `%USERPROFILE%\.claude\settings.json` içindeki `env` bloğuna `ANTHROPIC_BASE_URL` (`http://127.0.0.1:8787/p/<proje>`) ve `ENABLE_TOOL_SEARCH` ekler; eski değerleri `.claude\.headroom-vscode-claude.json` dosyasına kaydeder. Giriş bilgin ve model seçimin değişmez.
- İlk kurulumdan sonra VS Code penceresini yeniden yükle (`Ctrl+Shift+P` → Developer: Reload Window).
- Port doluysa `--port 8788`.
- Kontrol: `http://127.0.0.1:8787/health` → `"status":"healthy"`; istekler `http://127.0.0.1:8787/dashboard` adresinde görünür.
- **Proxy kapalıyken Claude Code istek atamaz** (ayar yerinde kaldığı için istekler Headroom'u atlamaz, başarısız olur).

Geri alma:

```powershell
headroom unwrap vscode-claude
```

Olmazsa, değişiklikten önce aldığın `settings.json.bak-headroom-*` yedeğini `settings.json` üzerine kopyala. Tamamen kaldırmak için `uv tool uninstall headroom-ai`. Ücretli plan veya yeni API hesabı gerekmez.

## Task Observer (kişisel; pakete girmez)

- Kancası ve gözlem klasörü kullanıcıya ve bilgisayara özeldir. Bu depoda dosyası yoktur ve yolları sabit kullanıcı yolu içerir.
- Kaynak: `github.com/rebelytics/one-skill-to-rule-them-all` (CC BY 4.0). Kurulumda üç parça vardır: skill klasörü (`~/.claude/skills/task-observer`), çalışma klasörü (`~/.claude/task-observer-workspace/skill-observations/observation-log/archive`) ve `settings.json` içindeki `hooks.SessionStart` girdisi. Kanca betiğinde çalışma klasörü `/c/Users/...` biçiminde sabitlenir (`new-observation.sh` yalnız bu biçimi kabul eder).
- Başka bilgisayarda kurulacaksa, önce `~/.claude/skills/task-observer` ve `settings.json` içinde `task-observer` geçip geçmediğine bak; varsa tekrar kurma. Kurarken `settings.json`'ı önce yedekle ve mevcut kancaları/eklentileri koru.
- Gözlemlerden çıkan kural önerileri **onay olmadan uygulanmaz**; AGENTS.md ve kod değişiklikleri senin onayınla yapılır.
- Gözlem günlükleri bilgisayarlar arasında taşınmaz ve Git'e girmez.

## Eklentileri başka bilgisayarda kurma

Önce mevcut duruma bak, kurulu olanı tekrar kurma:

```powershell
claude plugin list
claude plugin marketplace list
```

Eksik olanlar için:

```powershell
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install claude-code-setup@claude-plugins-official
claude plugin marketplace add thedotmack/claude-mem
claude plugin install claude-mem@thedotmack
```

Kurulu eklentileri değiştirmeden, yalnız eksik olanı ekle. `settings.json` bilgisayara özel olduğu için başka PC'den kopyalanmaz; gerekirse `enabledPlugins` ve `extraKnownMarketplaces` bloklarını elle ekle.

## Pakete veya Git'e girmeyenler

Kişisel ve bilgisayara özel olduğu için kopyalanmaz, commit'lenmez:

- `%USERPROFILE%\.claude\settings.json`, `.credentials.json`, giriş ve oturum bilgileri, yedekleri
- API anahtarları ve belirteçler (Gemini, Groq, GitHub, telefon belirteci)
- claude-mem hafıza veritabanları (`~/.claude-mem` ve eklenti verisi)
- Task Observer gözlem günlükleri
- `.claude/` (proje düzeyi araç ayarları ve yedekler), `.venv`, `models/`, `%USERPROFILE%\.jarvis`, `*.log`, `*.sqlite`, `*.db`

`.gitignore` bunların çoğunu dışarıda tutar. Commit'ten önce `git status` ile kontrol et.

## Kurulum ve doğrulama adımları (yeni bilgisayar)

1. Depoyu al (bundle ya da klasör kopyası; yukarıdaki Git notuna bak) ve `kurulum.bat` ile Jarvis ortamını hazırla. `.venv` Git'te yoktur.
2. `git config user.name` / `user.email` ile kimliği bu depo için ayarla.
3. Ajanı kur: `tools\claude\kur-ajanlar.ps1` (yukarıda).
4. Eklentilerin durumunu kontrol et ve eksikleri kur.
5. İstersen Headroom'u kur ve başlat.
6. Doğrula: `run_tests.bat .venv\Scripts\python.exe`. Python/Node testlerini ve smoke testlerini çalıştırır, ardından yalnız bağımlılık içe aktarmasını dener (kurtarma, temizlik, mikrofon, servis yok). Çıkış kodu 0 beklenir.
7. Playwright Chromium'u kontrol et: `.venv\Scripts\python.exe -m playwright install --dry-run chromium` hangi yapıyı beklediğini gösterir; eksikse `kurulum.bat` kurar.

## Kota tercihleri

Genel çalışma tercihleri [AGENTS.md](../AGENTS.md) içindeki "Kota çalışma tercihleri" maddesindedir; aşağıdakiler bunu araçlara uygular.

- Geliştirme sırasında **canlı Gemini/Groq çağrısı yapılmaz**; testler taklit kullanır ve gerçek modele gitmez. Yeni Gemini çağrısı eklenecekse önce plan ve onay gerekir.
- Denetçi ajanı yalnız açık istekle veya PR öncesinde çalışır.
- Ücretli sağlayıcı, ücretli plan veya yeni API hesabı kendiliğinden eklenmez; ücretli sağlayıcılar otomatik havuza girmez.
- Kullanıcıların anahtarları ayrıdır; hiçbir test veya araç bir kullanıcının anahtarını başka kullanıcı için kullanmaz.
- Task Observer kancası yalnız metin enjekte eder; gözlem için ayrıca model çağrısı yapmaz. Headroom yerel çalışır ve token tüketimini azaltmayı hedefler.
- Ses ile ilgili değişikliklerde gerçek mikrofon/hoparlör açılmaz; bunlar kullanıcının kendi bilgisayarında ayrıca denenir.
