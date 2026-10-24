# Jarvis yol haritası — 24 Ekim 2026 kapanış sırası

Bu belge, `docs/yol-haritasi-birlesik-2026-10-20.md` içindeki uygulama sırasını 24 Ekim 2026 itibarıyla günceller. Eski tarihsel maddeler Git geçmişinde kalır; aşağıdaki sıra yeni büyük işe geçmeden önce izlenecek güncel kapıdır.

## 1. Aşama 0–4 kapanış kapısı

Aşama 0–4 ancak aşağıdaki dört ölçüt aynı sürümde sağlandığında `CLOSED / CLEAN` sayılır:

1. Architecture Guard: `BLOCKER = 0`.
2. Tam `python -X utf8 -m modules.validation` yeşil.
3. Güncel birleşmiş `main` SHA üzerinde gerçek Windows PC kabulü PASS.
4. En az bir temsilci durable uçtan uca akış gerçek PC'de veya kabul ortamında doğrulanmış: Decision/Permission Gate → Worker → WorkerResult/evidence → GoalState/Reducer/CAS → completion. Aynı sınıfın crash/recovery davranışı testlerde korunur; her capability'nin tek tek fiziksel kabulü kapanış önkoşulu değildir.

Bu kapı tamamlanmadan Aşama 5 ve sonraki yeni omurga/domain genişlemeleri başlatılmaz.

## 2. RuntimeEvent ertelenmiş borç notunu temizle (#256)

Aşama 0–4 kapanışından sonra ilk dokümantasyon işi PR #256'nın güncellenmesidir.

- Kapanmış hardening maddeleri roadmap borcu olarak tutulmaz.
- Yalnız gerçek ertelenmiş iş görünür kalır: production durable RuntimeEvent subscription/producer entegrasyonu.
- Mevcut `source_watch` yapısı yapay biçimde GoalState'e bağlanmaz.
- Bu iş tamamlanmadan yapılmış sayılmaz; fakat Aşama 0–4 kapanış blocker'ı değildir.

## 3. 429 / Ollama'sız çalışma dayanıklılığı

Yeni domain açmadan önce küçük ve ayrı bir operasyonel hardening paketi yapılır.

Kapsam:

- 429/kota ile ağ/mikrofon/sağlayıcı hatasını kullanıcı mesajında ayırmak.
- Sınırlı retry/cooldown; kör tekrar yok.
- Bir sağlayıcı yoksa mevcut ücretsiz/uygun yedek yolları kullanmak.
- Ollama kurulu değilken Jarvis'in desteklenen bulut/modelsiz yollarının bozulmaması.
- Ücretli sağlayıcı veya ücretli GitHub planı bu paketin parçası değildir.
- Mevcut partial/modelsiz teslim yolları korunur; doğrulanmamış iş tamamlandı sayılmaz.

Bu paket Aşama 4 mimari blocker'ı değil, Aşama 0–4 kapanışından sonraki dayanıklılık işidir.

## 4. Finance ayrı domain kararı

Finance, Communication içine sıkıştırılmaz. Yeni mimaride ayrı `finance` domain olarak tasarlanır.

İlk sınır:

- Kur/piyasa/veri okuma ve hesaplama.
- Portföy/izleme/alarm için salt-okuma veya kullanıcı kontrollü kayıt yolları.
- Para transferi, emir, credential veya dış hesap yazımı mevcut Permission/Effect kurallarından bağımsız yeni yetki kazanmaz.
- Sayısal hesap mümkün olduğunda kod/hesap motoruyla; yorum ve açıklama modelle yapılır.
- Kaynak tarihi ve veri kaynağı kanıtı zorunlu tutulur.

Finance domain tasarımı, Aşama 0–4 kapanışını geriye dönük değiştirmez; ortak Core, DecisionContext, Permission Gate, Effect Policy, WorkerResult ve GoalState hattını kullanır.

## 5. Eski hedefler için yalnız aktif eşleme notu

Eski bütün PR'lar tek tek yeni mimariye taşınmaz. Yalnız halen açık veya gelecekte tekrar ele alınacak hedeflerin yeni karşılığı tutulur.

Belgelenmesi gereken başlıklar:

- düşük donanım/performance sınırları → deployment/acceptance notu,
- cümle ayrımı/doğal dil yönlendirmesi → router/classifier ürün sözleşmesi,
- sosyal medya ve WhatsApp/Telegram → ertelenmiş domain/capability kapsamı,
- öğrenme/kişiye uyum → ayrı kullanıcı/hafıza davranış kapsamı,
- RuntimeEvent production subscription → ertelenmiş durable runtime borcu,
- Finance → ayrı domain.

Kapanmış tarihsel PR ayrıntıları yeniden kataloglanmaz. Amaç arşiv üretmek değil, "unutuldu mu / ertelendi mi / nereye bağlanacak" belirsizliğini kaldırmaktır.

## 6. Bundan sonraki sıra

1. Aşama 0–4 kapanış kapısını tamamla.
2. #256'yı güncelle ve yalnız gerçek RuntimeEvent subscription borcunu bırak.
3. 429 / Ollama'sız çalışma hardening paketini tamamla.
4. Finance domain sözleşmesini yaz ve ortak omurgaya bağlanma sınırlarını kilitle.
5. Aktif/ertelenmiş eski hedeflerin kısa eşleme tablosunu güncelle.
6. Ancak bundan sonra Aşama 5+ işlerine geç.

## 7. Bilinçli kapsam dışı karar

Ücretli GitHub planına geçiş gündemde değildir ve açık iş olarak taşınmaz. Private Free repo sınırı; mevcut PR disiplini, Windows CI, gerçek PC watcher, Main bekçisi ve repo-local yerel Git emniyet kemeri ile yönetilir. Yerel hook'lar GitHub branch protection'ın eşdeğeri değildir; `--no-verify`, başka makine ve doğrudan API/server push ile atlanabilir.

## 8. Kapanış etiketi

Aşama 0–4 için kullanılacak tek kapanış etiketi:

`AŞAMA 0–4 = CLOSED / CLEAN`

Bu etiket yalnız bölüm 1'deki dört koşul birlikte sağlandığında kullanılacaktır.
