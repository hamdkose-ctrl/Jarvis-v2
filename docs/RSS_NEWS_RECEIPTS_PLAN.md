# RSS/API mühürlü haber makbuzu planı

Bu dal, eski HTML-merkezli haber kurtarma yamalarından bağımsızdır.

Hedef mimari:
1. Yalnız kayıtlı Türkçe sağlayıcıların RSS/API uçları keşif kaynağıdır.
2. Her girdiden mühürlü makbuz üretilir: sağlayıcı, kanonik URL, başlık, yayın tarihi, içerik özeti, kaynak özeti, alınma zamanı ve doğrulama/seal durumu.
3. Research yalnız makbuzdaki kanonik URL'yi açar. Sayfada tarih bulunamazsa, aynı URL'ye ait mühürlü RSS/API yayın tarihi kullanılır.
4. İki farklı yayıncıdan iki geçerli mühürlü makbuz olmadan genel haber hedefi kapanmaz.
5. Model yalnız doğrulanmış makbuzları özetler; kaynak seçmez, URL üretmez ve tarih uyduramaz.
6. Haber işi basit testlerle tamamlanmaz; ayrı gerçek Windows `--news` final kabulü PASS olmalıdır.

Bu PR'da HTML kazıma davranışını yamalamak yerine makbuz katmanı ve sözleşmeleri kurulacaktır. Eski #225 haber yamaları bu dala taşınmayacaktır.
