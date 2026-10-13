# GitHub Güncelleme Güvenliği — v5.5

- JARVIS açılışta GitHub'dan dosya çekip kurmaz. Yalnız yeni sürüm olup olmadığını kontrol eder.
- “Güncelleme var mı?” yalnız kontrol yapar; çalışma dosyalarını değiştirmez.
- Kurulum yalnız kullanıcının açık “kendini güncelle / güncellemeyi kur” komutuyla başlar.
- Self-Coder yerel değişiklik koruması updater içinde devam eder.
- v5.9 itibarıyla Self-Coder başarılı değişiklikleri testten sonra yerelde korur; GitHub main yayını yalnız açık `git yükle` komutuyla yapılır. Force-push kullanılmaz.
- Böylece yerelde test edilen v5.x dosyalarının açılışta eski GitHub sürümüyle sessizce ezilmesi engellenir.
- v5.12: “Senkron” etiketi yalnız kayıtlı commit'e dayanmaz; kullanıcı doğrulama/yayın istediğinde uzak `main` ile gerçek kaynak ağacı karşılaştırılır.
- v5.12: GitHub yayını çalışan `.venv` sürümlerini `requirements.lock.txt` içine alır; diğer PC lock dosyasını kullanır.
