# Jarvis — Aşama 0–4 kapanışı ve sonraki sıra

Güncelleme: 24 Ekim 2026 (Europe/Istanbul).

Bu belge `docs/yol-haritasi-birlesik-2026-10-20.md` içindeki genel hedefi değiştirmez. Bundan sonraki yakın çalışma sırasını netleştirir ve Aşama 0–4 kapanışı ile sonraki işleri birbirinden ayırır. Eski kapanmış PR'lar tek tek yeniden eşlenmez; yalnız açık hedefler ve ileride yeniden karşımıza çıkacak mimari/operasyon kararları taşınır.

## 1. Önce: Aşama 0–4 final kapanış kapısı

Aşama 0–4, yalnız “guard yeşil” veya tek tek PR testleri geçti diye kapalı sayılmaz. `CLOSED / CLEAN` etiketi için aynı güncel tabanda şu dört kanıt birlikte aranır:

1. `modules.architecture_guard` raporunda **BLOCKER = 0**.
2. Tam `python -X utf8 -m modules.validation` sonucu **Tüm test grupları başarılı.**
3. Güncel birleşmiş `main` SHA üzerinde gerçek Windows/PC kabulü **PASS**.
4. En az bir temsilci durable iş, gerçek PC'de uçtan uca şu zinciri kanıtlar: **Decision/Permission Gate → Worker → WorkerResult/Evidence → GoalState/Reducer/CAS → Completion**. Aynı mimarinin crash/recovery ve stale/duplicate korumaları otomatik testlerde yeşil kalmalıdır.

Her capability'yi tek tek fiziksel olarak denemek bu kapanışın şartı değildir. Ama yalnız birim/integration testleri de yeterli değildir; en az bir gerçek durable E2E kabul şarttır.

Bu kapı geçmeden Aşama 5+ için yeni mimari genişleme commit'i açılmaz. Açık hata düzeltmeleri ve kapanış sertleştirmeleri ayrı küçük PR'lar olarak yapılabilir.

## 2. Sonra: #256 RuntimeEvent roadmap borcunu temizle

PR #256 (`RuntimeEvent durable subscription` notu) olduğu gibi birleştirilmez. Önce güncellenir:

- Aşama 0–4 sırasında kapanmış hardening maddeleri listeden çıkarılır veya `done` işaretlenir.
- Yalnız gerçek ertelenmiş borç açık kalır: production/durable subscription → source/watcher → `RuntimeEvent` → freshness/dedup → canonical GoalState evidence.
- `RuntimeEvent` altyapısının hazır olması ile production producer/subscription entegrasyonunun hazır olması birbirine karıştırılmaz.
- Bu iş yeni bir dispatcher, ikinci state writer veya mevcut Core hattını atlayan paralel watcher üretmez.

Amaç arşiv tutmak değil, gelecekte “bu neden eksik?” sorusuna tek ve güncel cevap bırakmaktır.

## 3. Aşama 0–4 sonrasında küçük dayanıklılık paketi: 429 / Ollama'sız çalışma

Bu paket Aşama 4 blocker'ı değildir; kapanıştan hemen sonra, yeni domain genişlemesinden önce ele alınır.

Kapsam:

- 429/kota, ağ, auth ve yerel model yokluğu kullanıcıya farklı ve anlaşılır nedenlerle gösterilir.
- Aynı başarısız isteğe kör kısa retry yapılmaz; mevcut cooldown/failure policy tek kaynak olarak kullanılır.
- Ollama **zorunlu bağımlılık değildir**. Ollama kurulu değilse Jarvis desteklenen bulut/modelsiz yollarla çalışmaya devam eder; hedefin gerçekten model gerektiren kısmı yapılamıyorsa bunu açıkça söyler.
- Ücretli sağlayıcıya otomatik geçiş yapılmaz.
- Modelsiz kaynak/araç yolu mümkünse hedef tamamen bırakılmaz; doğrulanmış kısmi teslim yapılabilir.
- İş PC'si gibi Ollama olmayan gerçek ortam kabul senaryosu ayrıca tutulur.

Bu paket yeni model router veya ikinci fallback sistemi kurmaz; mevcut router/failure-policy hattını sertleştirir.

## 4. Finance domain kararı: ayrı domain

Finans uzun vadede `communication` içine gömülmez. Yeni mimaride **Finance ayrı domain** olarak ele alınacaktır.

Finance domain kapsamı en az şu alt dalları barındırır:

- kur ve piyasa verisi,
- portföy/izleme,
- alarm ve eşik takibi,
- finansal hesap/analiz,
- kaynak/tarih/evidence doğrulaması,
- ileride desteklenirse yetkili finansal işlem yolu.

Bu karar mevcut permission/effect politikasını gevşetmez. Salt-okuma finans verisi ile para/credential veya dış işlem aynı yetki sınıfı değildir. Para veya hesap üzerinde gerçek etki ayrı, daha sıkı authority/permission/effect sözleşmesine tabi kalır.

Finance domain'in kod göçü, Aşama 0–4 kapanışından ve yakın omurga aşamalarından bağımsız bir “hemen kodla” işi değildir. Burada yalnız mimari yeri sabitlenir; implementation kendi dikey dilim planıyla yapılır.

## 5. Belgele, hemen kodlama: açık hedef eşleme tablosu

Eski bütün PR'lar yeni mimariye tek tek eşlenmez. Yalnız bugün açık olan veya ileride tekrar gündeme gelecek başlıklar için küçük bir eşleme tablosu tutulur.

| Başlık | Yeni mimaride yeri | Şimdiki karar |
|---|---|---|
| Düşük donanım / performans | deployment + acceptance/performance sözleşmesi | Mimari Core'a doldurulmaz; ayrı kabul kriteri olarak belgelenir |
| Cümle ayrımı / doğal dil sınıflandırma | router/classifier ürün sözleşmesi | Core authority değildir; davranış testleriyle korunur |
| Sosyal medya | ileride domain/capability genişlemesi | Şimdilik ertelenmiş |
| WhatsApp/Telegram | communication altında servis/capability | Şimdilik ertelenmiş; alıcı/izin sınırları korunur |
| Öğrenme/kişiye uyum | memory/personalization + study/organizer ile ilişkili | Ayrı genişleme; omurga kapanışına karıştırılmaz |
| RuntimeEvent production subscription | durable runtime event hattı | #256 ile görünür borç; ayrı tasarım işi |

Amaç “unutuldu mu, bilerek mi ertelendi?” sorusunu ortadan kaldırmaktır; tarihsel arşiv üretmek değildir.

## 6. Bundan sonraki sıra

Yakın sıra şu şekilde kilitlenir:

1. **Aşama 0–4 final kapanış kanıtını tamamla.**
2. **#256 RuntimeEvent roadmap notunu güncelle/temizle.**
3. **429 / Ollama'sız çalışma dayanıklılık paketini yap.**
4. **Finance = ayrı domain kararını ana mimari/domain haritasına işlerken yalnız sözleşmeyi sabitle; kod göçünü ayrı planla.**
5. **Açık/ertelenmiş hedef eşleme tablosunu güncel tut.**
6. **Bunlardan sonra Aşama 5 ve devamındaki omurga/alan işleri mevcut Execution Architecture sırasına göre yürür.**

## 7. Özellikle kapsam dışı

- Ücretli GitHub planına geçiş bu yol haritasında açık iş değildir.
- Eski bütün PR numaralarını yeni mimariye tek tek bağlamak hedef değildir.
- Her push öncesi tam validation çalıştırmak yerel hook görevi değildir; resmî test kapısı Windows CI, gerçek PC kapısı watcher olarak kalır.
- Repo-local Git hook/ruleset yardımcıları GitHub server-side enforcement eşdeğeri sayılmaz.
