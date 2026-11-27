# Kullanıcı Senaryoları — kapsam filtresi

Bu belge, Jarvis'in **hangi işi** çözdüğünü tanımlar. Her PR bu beş senaryodan birine
hizmet etmek ya da onları mümkün kılan bir bağımlılığı kaldırmak zorundadır.
Hizmet etmeyen ve kontenjanı olmayan iş **yapılmaz**; silinmez, kenara yazılır.

## Kategori kontenjanı

| Kategori | Pay | Anlamı | Kanıt |
| --- | --- | --- | --- |
| **Kullanıcı işi** | %70 | Beş senaryodan birine doğrudan hizmet eder | Senaryo numarası (S1–S5) |
| **Zemin işi** | %20 | Senaryoları mümkün ya da güvenli kılar (ölçüm, geri dönüş, güvenlik, kasa) | Hangi bağımlılığı kaldırdığı |
| **Keşif** | %10 | "Belki işe yarar"; sonuç ne olursa ölçümüyle yazılır | Her 10 PR'da en çok 1 |

Kural: bir PR zemin sayılıyorsa **gerçek bir bağımlılık** göstermek zorundadır.
Gösteremiyorsa keşiftir ve kontenjanından düşer. Kontenjan dolduğunda yeni "belki" işi
bir sonraki tura atılır; kullanıcının "bu önemli" dediği iş her zaman kullanıcı işi sayılır.

## Beş senaryo

### S1 — Sabah brifingi
- **Ne:** "Bugün ne var?" → takvim, önemli mail, bekleyen işler, hava/haber başlıkları.
- **Kabul:** Sabah verilen komuta **10 sn içinde** tek ekranda özet; her satır kaynağıyla.
- **Bugün:** Takvim ve mail okuma var; birleşik brifing metni ve günlük tetikleme yok.

### S2 — Yazışma (oku, özetle, taslak)
- **Ne:** "Ali'den bu hafta kaç mail var", "şu maili özetle", "şu cevabı taslak yaz".
- **Kabul:** Filtreli adet sorusu **tek turda** doğru sayı verir (mesaj bazlı, yerel saat,
  Türkçe karakter duyarsız isim eşleşmesi); taslak yazılır, **gönderim kullanıcıdadır**.
- **Bugün (Gmail):** Okuma geniş, gönderim var; **filtreli adet** ve taslak yok.
- **Bugün (iş Outlook'u):** Bağlantı yok. Karar: aynı makinede Outlook Web'i **salt okuma**
  (deneysel, kırılgan; oturum düşerse "giriş yap" der, sayı uydurmaz).

### S3 — Dosya işi
- **Ne:** "Şu belgeyi bul / özetle / düzenle / şuraya taşı".
- **Kabul:** Bulma tek turda; **yazma kopyada prova**, onaydan sonra gerçek dosyaya;
  silme çöp kutusuna (kalıcı silme yok).
- **Bugün:** Dosya okuma/yazma var; kopyada prova ve çöp kutusu kuralı yok.

### S4 — Araştırma
- **Ne:** "Şunu araştır, kaynaklarıyla anlat" (haber, fiyat, teknik konu).
- **Kabul:** En az iki bağımsız kaynak, her iddia kaynağıyla; kaynak yoksa "bulamadım".
- **Bugün:** Anahtarsız haber hattı çalışıyor (2 yayıncı/2 makale kabulü geçti);
  arama sağlayıcıları anahtar bekliyor (Bağlantılar ekranına taşınacak).

### S5 — Bilgisayarda bir işi yap
- **Ne:** "Şu programda şunu yap" (Notepad, hesap makinesi, tarayıcı alanı).
- **Kabul:** Varsayılan `uia_pattern` (odak/imleç çalmaz); `physical_input` yalnız açık
  onayla; iptal `Esc` + sol-üst köşe, **≤200 ms**; son onaydan önce Enter/click yok.
- **Bugün:** Yok (Faz 9 "başlanmadı").

## Dürüst durum özeti

| Senaryo | Olur mu | Bugünkü durum |
| --- | --- | --- |
| S1 Sabah brifingi | Evet | Parçalar var, birleşik akış yok |
| S2 Yazışma — Gmail | Evet | Okuma var, filtreli adet/taslak yok |
| S2 Yazışma — Outlook | Kısmen | Bağlantı yok; OWA okuma deneysel |
| S3 Dosya | Evet | Okuma/yazma var, prova+çöp kutusu kuralı yok |
| S4 Araştırma | Evet | Anahtarsız hat çalışıyor, sağlayıcı kolları kapalı |
| S5 Bilgisayar kontrolü | Kısmen | Yok; her uygulamada çalışmaz |

## Kapsam dışı (bilinçli)

- Gönderim: mail/mesaj gönderme Jarvis'te yok, kullanıcıda.
- Yönetici izinli pencereler, CAPTCHA, 2FA.
- Ücretli servisler, anahtar havuzu, çok kullanıcılı yapı.
- Uzak masaüstü protokolü yazmak (yalnız harici aracı başlatan kart).
