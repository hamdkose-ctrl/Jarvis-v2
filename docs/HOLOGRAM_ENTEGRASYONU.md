# Jarvis hologram güncellemesi — 13 Ekim 2026

Bu ZIP, gönderdiğin Jarvis sürümüne uygulanacak güncelleme dosyalarını içerir.

## Uygulama

1. Jarvis’i ve kaynak dosyalarını değiştiren açık ajan oturumlarını kapat.
2. Mevcut Jarvis klasörünün bir kopyasını yedek olarak al.
3. ZIP’i geçici bir klasöre çıkar. İçindeki webui/, modules/, tests/, docs/ klasörlerini ve AGENTS.md’yi mevcut Jarvis köküne BİRLEŞTİREREK kopyala. Aynı adlı dosyaları değiştir; mevcut klasörleri silme.
4. Jarvis kökünde `run_tests.bat .venv\Scripts\python.exe` çalıştır.
5. Testler geçince normal `baslat.bat` ile aç. Tarayıcı eski çizimi gösteriyorsa Ctrl+F5 ile yenile.

Renkler ana ekrandaki GÖRÜNÜM alanında ve Ayarlar > Sistem > Genel’de.
Üç silüet: Mavi, Turkuaz, Sarı. İki arka plan: Mavi dağlar, Lav dağları.
Seçimler bu tarayıcıda saklanır. Turuncu yüz/boğaz korunur.
Silüete tıklama veya Enter/Space mevcut Konuş eylemini kullanır; dağ tıklaması konuşma başlatmaz.
SOHBETE GEÇ ve MENÜ yolları korunur. Küçük pencerede de görünür.

## Yapılanlar ve sınırlar

Onaylanan yakın kadrajın shader’ları ve görselleri doğrudan ana ekrana alındı.
Durum mevcut /events -> onEvent -> S.orb üzerinden gelir; yeni model çağrısı, mikrofon kaydı, ses üretimi veya SSE bağlantısı yok.
Konuşma hareketi gerçek KONUŞUYOR durumuna bağlıdır; görsel ritim sentetiktir, gerçek ses genliği henüz ölçülmez.
Açılış bir kez oynar, sayfa dönüşünde kaldığı süre korunur; TEKRAR OYNAT baştan başlatır.
Animasyon kapalı/reduced-motion’da durağan görünüm; WebGL yoksa 2D durağan görünüm vardır.
Sunucu, kimlik doğrulama, CSP, ses/model motoru ve Android kaynakları değiştirilmedi.
GitHub yayını, commit veya PR yapılmadı.

## Doğrulama

- 14 mevcut Node davranış grubu geçti; yeni hologram davranış grubu da geçti.
- Tüm webui JS dosyaları sözdizimi kontrolünden geçti.
- Yeni test gerçek onEvent ve mount köprüsünü çalıştırır; kullanıcı olay ayrımı, durumlar, renk geçişi, tıklama sınırı, klavye, reduced-motion, gizli sayfa, sakin mod, tekrar oynatma, GL bağlam olayları ve kaynak temizliğini taklitlerle sınar.
- Entegre modülün gerçek shader’ları yazılımsal OpenGL/EGL’de derlendi; mavi/turkuaz/sarı ve konuşma çizimleri üretildi. Bu, Windows tarayıcı akıcılığı testi değildir.
- Altı duman testi geçti.
- Python: 890 test çalıştı; 8 başarısızlık Windows Ayarlar açma kontrollerindeydi, 2 test atlandı. Bu çalışma Linux’taydı. Eksik Google/requests/psutil test bağımlılıkları yalnız geçici ortamda tamamlandı; proje bağımlılık kilidi değiştirilmedi. Tam sürüm doğrulamasını başarılı saymıyorum: Windows’ta yukarıdaki run_tests komutu zorunlu.
- Canlı mikrofon, Whisper, Gemini Live/TTS, gerçek SSE ve 1080p/4K akıcılık PC’de bekliyor.

## PC’de kısa kontrol

- Açılış -> silüet ve dağlar; üç renk ve iki arka plan.
- Silüete tıkla -> DİNLİYOR -> konuşma sonrası DÜŞÜNÜYOR -> yanıt sırasında KONUŞUYOR -> HAZIR.
- Dağlara tıkla -> mikrofon başlamamalı.
- Sohbet/Menü’ye geç ve ana ekrana dön -> yeni bir açılış üst üste başlamamalı.
- TEKRAR OYNAT -> tek açılış yeniden başlamalı.
- Ana ekran animasyonunu kapat -> durağan görünüm; sohbet/mikrofon kullanılmalı.
- Sohbette dosya ekle ve Çalışma/Ayarlar ekranlarını aç -> mevcut işlevleri doğrula.

## Geri dönüş

Jarvis kapalıyken yedeklediğin eski dosyaları geri kopyala. Yeni hologram dosyaları eski nx.html tarafından yüklenmez; kişisel verilerin ve .venv değişmedi.
