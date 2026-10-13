# Kullanıcı / API Anahtarı Kuralı

- JARVIS çok kullanıcılıdır.
- Her kullanıcı kendi profil, hafıza, sohbet ve Gemini API anahtarına sahiptir.
- Bir kullanıcının Gemini anahtarı başka kullanıcı için fallback/ortak anahtar olarak kullanılmaz.
- Kullanıcının anahtarı yoksa Gemini o kullanıcı için kullanılamaz; sistem başka kullanıcının kotasını tüketmez.
- Android bağımsız uygulamasının kurulum QR kodu yalnız seçilen kullanıcının kendi Gemini anahtarını taşır. Ekrandan 90 saniye sonra gizlenmesi anahtarın süresini doldurmaz.
- Android/iPhone PC bağlantısı QR kodu API anahtarı içermez: 90 saniyelik tek kullanımlık eşleşme kodu taşır. Başarılı eşleşmede tarayıcıya yalnız o profile ait telefon erişim anahtarı verilir.
- Mevcut global anahtar eski kurulum/bakım uyumluluğu için tutulabilir; normal profil sohbetinde fallback değildir.
