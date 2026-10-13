# Çalışma Alanı ve Özgün PDF Görünümü

- Masaüstünde Soru / Kaynak ve Anlatım panelleri çalışma sayfasında kalan yüksekliği kullanır. PDF oranı korunarak görüntü alanına sığar; sayfalama ve Sayfaya Sığdır düğmesi kaynağın altındadır.
- Çalışma Önerileri açılır bölümde tutulur. Dar ekranlarda paneller alt alta gelir ve sayfa kaydırılabilir. Görsel ve video kaynak penceresi açılmaya devam eder.
- Eski kayıtta özgün PDF eksikse açık uyarı ve Özgün PDF’yi Bağla düğmesi görünür. Kullanıcı aynı PDF’yi seçer; kaynak kimliği ve ilerlemesi korunur. PDF mevcutsa eski metadata bayrağı eksik olsa da özgün sayfa gösterilir.
- Bilinen kaynak hash’i varsa yüklenen dosyanın SHA-256 değeri eşleşmelidir. Eski hash’siz kayıtlarda çıkarılan metin, boşluklar dışında kayıtlı metinle eşleşmelidir. Bu ikinci kontrol görsellerin aynı olduğunu kanıtlamaz; kullanıcı özgün dosyayı seçmelidir. Yanlış dosya ve işlem sırasında kaldırılan/değişen kaynak reddedilir.
- Özgün dosya yoksa çıkarılmış metinden sayfa düzeni yeniden üretilmez. Gerçek PDF bağlanana kadar metin görünümü kalır.

Kontroller: gerçek iki sayfalık PDF üzerinde özgün baytların korunması, sayfa oranı/rengi, ilerlemenin korunması, yanlış dosya ve eski kaynak reddi; JavaScript üzerinde sayfalama konumu, yüksekliğe uyarlama ve geç yüklemede profil koruması. Otomatik kontroller gerçek Windows ekranında görsel doğrulamanın yerine geçmez.
