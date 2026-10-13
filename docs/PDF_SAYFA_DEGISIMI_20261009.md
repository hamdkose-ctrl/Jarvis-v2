# PDF Sayfa ve Kaynak Değişimi

Gözlenen hata: kaynak/sayfa değişiminde `PDFium: Data format error`. Kullanıcının gerçek PDF’si olmadan bu hatanın kesin nedeni belirlenemedi.

Kodda ayrıca PDFium okuma ve çizim çağrılarının farklı istekler/dönüştürmeler tarafından eşzamanlı yapılabildiği görüldü. PDFium farklı belgelerde bile eşzamanlı kullanılamaz: https://pypdfium2.readthedocs.io/en/stable/python_api.html#incompatibility-with-threading

- Çalışma önizlemesi ve belge dönüştürmeleri ortak okuma yordamını kullanır. PDFium işlemleri tek kilitle sırayla yürütülür; seçili sayfa çizimi ve kaynak dosya değişimi diğer PDF işlemleriyle çakışmaz.
- Dosyalar Python’un ikili dosya akışıyla açılır; Türkçe dosya/klasör adları yerel PDFium dosya yolu API’sine gönderilmez. Matematik eklerinin mevcut PDF baytlarıyla açılma davranışı da korunur. Özgün dosya değiştirilmez.
- Bir çalışma PDF’si açılamıyorsa boş panel yerine kayıtlı metin, açıklayıcı uyarı ve yeniden bağlama düğmesi gösterilir. Bu metin görünümü özgün PDF sayfası olarak sunulmaz. Geçersiz sayfa numarası hataları gizlenmez.
- Hızlı kaynak değişiminde eski önizleme cevabı yeni kaynağın üstüne yazılmaz.

Kontroller: Türkçe dosya yolunda gerçek PDF, dosya tanıtıcılarının kapanması, paralel sayfa okumalarında seri işlem ve doğru renk/sayfa, bozuk özgünde kayıtlı metnin korunması ve hızlı kaynak değişimi. Bunlar kullanıcının belirli PDF’sinin açılacağını kanıtlamaz; hata sürerse aynı PDF ile ayrıca doğrulama gerekir.
