# Jarvis Capability Intake v1 — İkinci dalga (705 madde)

Bu belge, `Jarvis_Master_Hasat_Listesi`ndeki 705 adayın tamamını
`JARVIS_CAPABILITY_INTAKE_V1.md`'deki karar etiketleriyle kayda geçirir ve
Hermes kaynak referansını commit SHA'ya sabitler. Yeni capability kurmaz,
kod değiştirmez; yalnız karar defterini günceller (yol haritası Faz 3).

İlk dalga (20 aday) geçerliliğini korur. İki dalga aynı konuda ayrışırsa
ilk dalga kararı geçerlidir; ikinci dalga onu yalnız madde düzeyine indirir.

Madde madde tablo:
[`capability_intake/JARVIS_CAPABILITY_INTAKE_WAVE2_INVENTORY.csv`](capability_intake/JARVIS_CAPABILITY_INTAKE_WAVE2_INVENTORY.csv)

## Kaynak ve kapsam

- Envanter: `Jarvis_Hasat_Listesi_Dogrulanmis.xlsx` (705 madde, 23 başlık).
  Her maddenin `Jarvis durumu` (VAR / KISMİ / YOK) ve `Kanıt` sütunu kod
  taramasıyla `main@028e2fc` üzerinde doğrulanmıştır.
- Faz eşlemesi: `Jarvis_Yol_Haritasi.md` (25 Ekim 2026) Faz 0–12.
- Bu taramadan sonra birleşen #348–#352 (Faz 0-B, 0-A hazırlığı, 1-A, 1-B,
  1-C) bazı Faz 0/1 maddelerinin durumunu değiştirmiş olabilir. Bu belge
  durum sütununu yeniden taramaz; o maddeler kendi faz PR'larında kapanır.

## Karar kuralı

Etiketler ilk dalgayla aynıdır (`AL`, `UYARLA`, `BİZDEKİ KALSIN`, `ALMA`,
`ERTELENMİŞ`). Her madde aşağıdaki sırayla ilk uyan kurala göre etiketlenir:

1. **`ALMA`** — Madde yol haritasının "Listede olmayanlar" bölümüne girer
   (ücretli/kart isteyen servis, ürün kararıyla çıkarılan alan, istenmeyen
   alan) veya ilk dalga #14 (mevcut `plugins.py`) kapsamındadır.
2. **`BİZDEKİ KALSIN`** — Liste kararı `KORU` olan Core kuralı veya
   Jarvis'te `VAR` olan yetenek. Dış aday yalnız benchmark olarak kalır.
3. **`UYARLA`** — Yol haritasında Faz 0–4'e düşen madde. Intake kapısından
   (kaynak pin, lisans, Windows/Python uyumu, Permission/Effect/Evidence,
   acceptance) geçtikten sonra yalnız adapter sınırından alınır.
4. **`ERTELENMİŞ`** — Faz 5–12'ye düşen madde. Önkoşul fazı açılmadan
   tasarıma da alınmaz.

İkinci dalgada hiçbir madde `AL` değildir. `AL`, madde bazında sabit kaynak,
lisans ve Windows runtime kanıtı ister; aşağıdaki Hermes pini bu kanıtın
yalnız kaynak/lisans kısmını sağlar.

## Sonuç

| Karar | Madde |
|---|---|
| `ALMA` | 65 |
| `BİZDEKİ KALSIN` | 164 |
| `UYARLA` | 99 |
| `ERTELENMİŞ` | 377 |
| **Toplam** | **705** |

### Başlığa göre

| Başlık | Maddeler | `ALMA` | `BİZDEKİ KALSIN` | `UYARLA` | `ERTELENMİŞ` |
|---|---|---|---|---|---|
| Çoklu Ajan / Delegation / Koordinasyon | 1–30 | 3 | 3 | 0 | 24 |
| Kanban / Görev Koordinasyonu | 31–50 | 0 | 4 | 0 | 16 |
| PC / Windows / Computer Use | 51–88 | 2 | 11 | 0 | 25 |
| Browser / Web Otomasyonu | 89–116 | 1 | 7 | 20 | 0 |
| Skills / Öğrenilebilir Yetenekler | 117–152 | 0 | 0 | 0 | 36 |
| Plugins / Tool Registry / MCP / Connections / A2A | 153–199 | 5 | 2 | 0 | 40 |
| Araştırma / Web / Haber / Hoca | 200–236 | 4 | 13 | 20 | 0 |
| Dosya / Klasör / Office / Bilgi Kaynakları | 237–267 | 4 | 11 | 3 | 13 |
| Kodlama / Git / Yazılım Ajanları | 268–295 | 0 | 4 | 0 | 24 |
| Sandbox / İzolasyon / Güvenli Yürütme | 296–322 | 2 | 1 | 0 | 24 |
| Memory / Session / Kişiselleştirme / Self-Evolution | 323–351 | 3 | 7 | 0 | 19 |
| Context Yönetimi | 352–372 | 0 | 0 | 0 | 21 |
| Cron / Background / Event / Hooks | 373–410 | 0 | 13 | 25 | 0 |
| Mesajlaşma / Gateway / İletişim | 411–442 | 12 | 8 | 0 | 12 |
| Gmail / Takvim / Workspace / İş | 443–468 | 0 | 7 | 3 | 16 |
| Finans / Piyasa | 469–489 | 1 | 8 | 11 | 1 |
| Sosyal Medya / Medya / Yaratıcı | 490–530 | 15 | 7 | 0 | 19 |
| Ses / UI / Desktop / Dashboard | 531–559 | 0 | 9 | 0 | 20 |
| Model / Provider / 429 / Local AI | 560–590 | 4 | 13 | 14 | 0 |
| Observability / Eval / Kalite | 591–626 | 0 | 6 | 0 | 30 |
| Backup / Update / Migration / Operasyon | 627–651 | 0 | 4 | 0 | 21 |
| Yeni Jarvis Alanları / Genişleme | 652–678 | 9 | 4 | 0 | 14 |
| Jarvis Çekirdeği ile Entegrasyon Kuralları | 679–705 | 0 | 22 | 3 | 2 |
| **Toplam** | 705 | **65** | **164** | **99** | **377** |

### Faza göre

| Yol haritası fazı | `ALMA` | `BİZDEKİ KALSIN` | `UYARLA` | `ERTELENMİŞ` | Toplam |
|---|---|---|---|---|---|
| Faz 0: Aşama 0–4 kapanışı | 0 | 5 | 3 | 0 | 8 |
| Faz 1: 429 / Ollama'sız paket | 4 | 0 | 14 | 0 | 18 |
| Faz 2: RuntimeEvent / cron / hook | 0 | 0 | 25 | 0 | 25 |
| Faz 3–4: Finance sözleşmesi ve veri | 1 | 0 | 8 | 0 | 9 |
| Faz 4: Salt-okuma pilotlar | 9 | 0 | 49 | 0 | 58 |
| Faz 5: Gözlemlenebilirlik | 0 | 0 | 0 | 30 | 30 |
| Faz 6: Sandbox / skill / kod ajanı | 2 | 0 | 0 | 84 | 86 |
| Faz 7: Delegation / Kanban | 3 | 0 | 0 | 40 | 43 |
| Faz 8: MCP / plugin | 5 | 0 | 0 | 40 | 45 |
| Faz 9: ComputerWorker | 2 | 0 | 0 | 27 | 29 |
| Faz 10: Dışarıya etki eden işler | 26 | 0 | 0 | 31 | 57 |
| Faz 11: Hafıza / context | 3 | 0 | 0 | 40 | 43 |
| Faz 12: Düşük öncelikli alanlar | 10 | 0 | 0 | 85 | 95 |
| Mevcut — bakım | 0 | 159 | 0 | 0 | 159 |

## `ALMA` listesi (65)

| Gerekçe | Maddeler |
|---|---|
| Ücretli / kart isteyen: Brave, Perplexity, Parallel, xAI/X arama | 205, 208, 210, 211 |
| Ücretli / kart isteyen: Modal, Daytona | 299, 300 |
| Ücretli / kart isteyen: Honcho, Mem0, Supermemory bulut | 329, 330, 331 |
| Ücretli / kart isteyen: Alpha Vantage | 477 |
| Ücretli / kart isteyen: X API (arama, paylaşım, DM vb.) | 490–503 |
| Ücretli / kart isteyen: ses klonlama, prompt önbellekleme, araç ağ geçidi | 518, 589, 590 |
| Ücretli / kart isteyen: yönetilen bağlayıcılar, bulut worker | 191, 669 |
| Ürün kararı: anahtar havuzu / anahtar döndürme | 575, 576 |
| Ürün kararı: Jarvis MCP veya API sunucusu | 188, 656, 657 |
| Ürün kararı: IDE istemcisi | 658, 659, 660, 661 |
| Ürün kararı: uzak PC ve çoklu oturum | 82, 84 |
| İstenmeyen: Notion, Obsidian, Box, Airtable | 253, 254, 255, 256 |
| İstenmeyen: algılanmayan tarayıcı (Camofox) | 111 |
| İstenmeyen: uzman grup sohbeti ve `@bahsetme` | 20, 21, 22, 665 |
| İstenmeyen: Telegram ve WhatsApp dışı platformlar | 415–417, 419–425, 434, 435 |
| İstenmeyen: worker / eklenti pazarı | 670 |
| İlk dalga #14: mevcut `plugins.py` büyütülmez | 163, 164, 167 |

Şartlı tutulan maddeler (`ERTELENMİŞ`, CSV `Not` sütununda): 103 (yalnız
ücretsiz/yerel şifre yöneticisi), 178, 179, 513 (yalnız yerel görsel/video
üretimi), 668, 676 (yalnız kendi makinedeki worker).

## Hermes sürüm referansı (SHA'ya sabit)

İlk dalga ve `JARVIS_HERMES_COMPATIBILITY_EVALUATION_V1.md` §1.2, master
listedeki `v0.22.5` referansını doğrulanamadı diye `BLOCKED` bırakmıştı.
2026-10-26'da `git ls-remote` ile tag artık upstream'de görülüyor ve
çözüldü:

| Alan | Değer |
|---|---|
| Repo | `https://github.com/NousResearch/hermes-agent` |
| Tag | `v0.22.5` (annotated; tagger "Hermes Release Automation", 2026-10-23 05:28:40 UTC) |
| Tag nesnesi | `56b6a31fededdf7364e1a0a79548d144e7fd81a3` |
| **Commit (pin)** | **`bf0203a794a07aac3ff764972ab9087baa4e4f4e`** |
| Commit tarihi / başlık | 2026-10-22T19:24:27-07:00 — "fix(launchers): a Python repin republishes hermes.exe, not a .cmd" |
| Release kaydı | Tag mesajı: `rc.3-v0.22.5` adayından terfi, `releaseId` 421389285 |
| Lisans | `LICENSE` — MIT, "Copyright (c) 2025 Nous Research"; dosya SHA-256 `821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6` |
| `requires-python` | `>=3.11,<3.15` (`pyproject.toml`) |
| `.python-version` | `3.14` |
| `.nvmrc` | `26` |

Yeniden doğrulama:

```text
git ls-remote https://github.com/NousResearch/hermes-agent 'refs/tags/v0.22.5^{}'
→ bf0203a794a07aac3ff764972ab9087baa4e4f4e  refs/tags/v0.22.5^{}
```

Notlar:

- Tag imzalı değildir (PGP/SSH imzası yok). Pin tag adına değil, commit
  SHA'sına yapılır; tag taşınırsa pin değişmez.
- `requires-python` aralığı Jarvis'in Python 3.13'ünü kapsar, ama Hermes'in
  kendi kurulumu 3.14'ü hedefler. 3.13 üzerinde hangi modüllerin çalıştığı
  hâlâ benchmark kanıtı ister; uyumluluk belgesi §2'deki "belirsiz" kararı
  değişmez.
- Upstream `rc.N-v0.22.5` ve `v0.22.5+canary.*` tag'leri de var. Bunlar
  benchmark referansı olamaz; yalnız yukarıdaki commit kullanılır. `main`
  HEAD de kullanılmaz (uyumluluk belgesi §1.3).
- Pin, Hermes'i `AL` yapmaz. İlk dalga kararı (#10 `ERTELENMİŞ`, Hermes
  yalnız Worker/Adapter adayı) ve `JARVIS_HERMES_ADAPTER_BOUNDARY_V1.md`
  sınırı aynen geçerlidir.

## Bakım

- CSV, `Jarvis_Hasat_Listesi_Dogrulanmis.xlsx`'ten bu kurallarla üretilir;
  madde kararı değişirse CSV satırı ve bu belgedeki sayılar aynı PR'da
  güncellenir.
- Bir faz açıldığında o fazın `ERTELENMİŞ` maddeleri ayrı bir dalga
  belgesiyle `UYARLA` veya `ALMA`'ya çevrilir; bu belge geriye dönük
  yeniden yazılmaz.
