# v5.7 Mimari Kuralları

1. GitHub `main` tek ana kod sürümüdür; Ev/İş ayrı ürün değildir.
2. Açılışta güncelleme yalnız kontrol edilir, otomatik kurulmaz.
3. **v5.9 ile güncellendi:** Self-Coder testten geçen değişikliği yerelde korur; GitHub yayını yalnız açık `git yükle` komutuyla yapılır. Başarısız testte rollback yapar.
4. Her profil kendi Gemini ve Groq anahtarını kullanır; kullanıcılar arası fallback yoktur.
5. UI anahtar durumu aktif profil üzerinden hesaplanır; global/legacy anahtar “Aktif” göstergesi oluşturmaz.
