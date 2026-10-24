# Jarvis yol haritası karar eki — 24 Ekim 2026

Bu belge `docs/yol-haritasi-birlesik-2026-10-20.md` içindeki ilgili uygulama sırasını 24 Ekim 2026 kararlarıyla günceller. Eski belge tarihsel bağlam olarak korunur; aşağıdaki maddeler çelişen sıra veya açık iş yorumlarının yerine geçer.

## Karar özeti

- Aşama 0–4 tamamlanmadan Aşama 5 ve sonrasına geçilmez.
- Ücretli GitHub planı açık iş veya öneri değildir; gündem dışıdır.
- Private Free repo için ruleset oluşturulmuş olsa da enforcement teknik olarak zorlanmadığından süreç; PR disiplini, Main bekçisi, PC watcher ve repo-local hook emniyet kemeriyle yürür. Bu yerel koruma GitHub branch protection eşdeğeri değildir.
- Eski bütün PR'lar yeni mimariyle tek tek eşlenmez. Yalnız hâlen açık hedefler ve gelecekte yeniden karşımıza çıkacak alanlar haritada tutulur.

## Sıra

### 1. Aşama 0–4 final kapanış kapısı

Aşama 0–4 ancak aşağıdaki dört ölçüt birlikte sağlandığında `CLOSED / CLEAN` sayılır:

1. Architecture Guard: `BLOCKER = 0`.
2. Tam `python -X utf8 -m modules.validation` yeşil.
3. Güncel birleşmiş `main` SHA üzerinde gerçek Windows PC acceptance PASS.
4. En az bir temsilci durable iş gerçek PC'de uçtan uca kanıtlanmış olmalı: karar/izin kapısı → worker → WorkerResult/evidence → GoalState → tamamlanma. Aynı davranışın hata/recovery sınırları otomatik testlerle korunur; her capability'nin fiziksel olarak tek tek denenmesi kapanış önkoşulu değildir.

Bu kapı sağlanmadan Aşama 5 açılmaz.

### 2. RuntimeEvent roadmap borcunu temizle

Taslak PR #256 olduğu gibi birleştirilmez. Önce güncellenir:

- kapanmış Aşama 0–4 hardening maddeleri çıkarılır veya tamamlandı diye işaretlenir;
- yalnız gerçek ertelenmiş borç olan production durable RuntimeEvent subscription/producer entegrasyonu açık bırakılır;
- RuntimeEvent freshness/dedup/Reducer-CAS altyapısının hazır olduğu, fakat gerçek production subscription yaşam döngüsünün ayrı tasarım işi olduğu korunur.

Bu iş runtime davranışı eklemek değil, yol haritası borcunu doğru hale getirmektir.

### 3. 429 / Ollama'sız çalışma dayanıklılığı

Aşama 4 blocker'ı değildir; 0–4 kapanışından hemen sonraki küçük operasyonel hardening paketidir.

Kapsam:

- 429/kota ile ağ/mikrofon/sağlayıcı hatasını kullanıcıya anlaşılır biçimde ayırmak;
- sınırlı retry ve mevcut fallback davranışını korumak;
- Ollama kurulu değilken Jarvis'in zorunlu olarak yerel modele bağımlı kalmaması;
- model yokluğunda mümkün olan modelsiz/read-only/kısmi teslim yollarını kullanmak;
- ücretli sağlayıcıya otomatik geçmemek.

Bu paket yeni domain veya ikinci yürütücü kurmaz.

### 4. Finance domain kararını mimariye işle

Finans `communication` içine alınmaz. Uzun vadeli mimaride ayrı `finance` domain olarak ele alınır.

İlk sınır:

- kur/piyasa/portföy/analiz/alarm gibi salt-okuma ve analitik işler;
- para hareketi veya yetkili işlem ayrı capability/permission tasarımı ister ve mevcut salt-okuma yetkisini genişletmez;
- Finance de aynı Core, DecisionContext, Permission Gate, Effect Policy, WorkerResult ve GoalState hattını kullanır; ikinci dispatcher kurulmaz.

Domain kararı önce belgelenir; geniş uygulama çalışması Aşama 5+ sırasını bozmaz.

### 5. Açık hedefler için kısa mimari eşleme tablosu

Kodlama işi değildir. Yalnız hâlen açık veya gelecekte yeniden ele alınacak başlıklar yeni mimaride nereye oturuyor açıkça yazılır.

En az:

- düşük donanım/performance sınırları → deployment/acceptance notu;
- cümle ayrımı/yönlendirme → router/classifier ürün sözleşmesi, güvenlik otoritesi değil;
- sosyal medya ve WhatsApp/Telegram → ertelenmiş alanlar; `communication` altında capability planı, bugün açılmış kapsam değil;
- öğrenme/kişiye uyum → ayrı ürün/Memory/Study davranışı; Aşama 0–4 execution omurgasının parçası değil;
- RuntimeEvent production subscription → deferred runtime debt;
- Finance → ayrı domain kararı.

Eski kapanmış PR'lar tek tek arşivlenmez.

## Aşama 5'e geçiş koşulu

Aşama 5 ancak bölüm 1'deki final kapanış kapısı tamamlandıktan sonra açılır. Bölüm 2–5 maddeleri arasından yalnız Aşama 0–4 kapanışını etkileyen bir regresyon bulunursa bu regresyon önce kapatılır; aksi halde bu maddeler kontrollü şekilde sırayla yürür.

## Durum etiketi

Şu an hedef durum:

`AŞAMA 0–4 = FUNCTIONALLY CLOSED / FINAL ACCEPTANCE PENDING`

Final acceptance kapısı tamamlanınca:

`AŞAMA 0–4 = CLOSED / CLEAN`
