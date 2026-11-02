# Jarvis ana planı ve mevcut uygulama

13 Ekim 2026. Hedef: Kullanıcının verdiği işi araştırma, üretim, iletişim, bilgisayar işlemleri ve takip boyunca yöneten genel amaçlı Jarvis. Ekonomi/haber bir kullanım örneğidir, temel mimariyi belirlemez. Kota temel hedef değildir; kalite, doğrulama, kalıcılık ve kullanıcı kontrolü esastır.

## Sabit kararlar

- Mevcut Jarvis motoru, kullanıcı profilleri, model yönlendirmesi, API ve SSE korunur.
- Son kabul edilen silüet/arka plan görünümü korunur. Ana ekran, menü, sohbet, dosyalar ve çalışma düzeni için yeni tasarım uygulanmaz.
- Olağan okuma, araştırma ve geri alınabilir yerel işler her adımda onay istemez. Dış gönderim/yayın, para, kalıcı silme, hassas bilgi ve hesap güvenliği için açık işlem yetkisi gerekir. Verilmiş yetki aynı kapsamda tekrar sorulmaz; kapsam ve servis desteği doğrulanır.
- Kullanıcılar arasında anahtar, hafıza, görev veya hesap bağlantısı paylaşılmaz. Yeni ücretli sağlayıcı otomatik seçilmez.
- Tamamlandı denilen işin gerçek çıktı/kanıtı olmalı. Desteklenmeyen işlem yapılmış gibi gösterilmez.

## Mevcut koddan çıkarılan yapı

| Katman | Mevcut kod | Durum |
|---|---|---|
| Ana komut motoru | engine_runtime, engine_commands, command_manager | Var; görev komutları burada bağlı |
| Model yönlendirmesi | llm, smart_router | Gemini/Groq/Ollama ve açıkça ayarlanan bağlantılar |
| Görev adımları | task_agents | Araştırma, rapor, tarayıcı, geliştirme ve doğrulama; bağımlılık grafiği |
| İstek kimliği ve iptal | requests_state | Aynı istek kimliği tekrar çalıştırılmaz; süre/iptal kontrolleri var |
| Tarayıcı işlemleri | browser_agent | Gerçek Playwright; sonuç kontrolü ve tek plan için onay |
| PC kontrolü | desktop_agent, desktop_uia, system_control | Kullanıcı/uygulama izinleri ve sonuç doğrulama |
| Kişisel hafıza | personalization, learning, session_state | Bilgiler, kurallar, hedefler ve oturum durumu |
| Gmail/Takvim | google_api | OAuth, kullanıcıya ayrı token; Gmail kapsamı salt okuma |
| WhatsApp | messaging | Windows uygulama otomasyonu; resmi çok servisli mesaj altyapısı değil |
| Medya | media, studymedia | Açma/oynatma ve çalışma kaynakları; genel video üretim/yayın sistemi değil |

## Bu pakette uygulanan temel

Görev devam, görev sürdür, görev iptal, görev durumu <kimlik>, görev geçmişi ve görev yetenekleri komutları mevcut motor üzerinden çalışır. Bir görev kapanınca kaydı kalır; Jarvis kapandıktan sonra yeni oturumda devam komutu verilebilir.

- Tamamlanan adımlar tekrar uygulanmaz.
- Yarım kalan araştırma/rapor/doğrulama güvenli biçimde sürdürülür. Tarayıcı veya kod adımının dış etkisi belirsizse otomatik tekrarlanmaz.
- Sonuçlar ve adım geçişleri diskte tutulur; kayıt flush/fsync ve atomik değiştirmeyle yazılır.
- Raporun SHA-256 özeti tutulur. Tamamlanan dosya değişmiş veya kaybolmuşsa devam durur. Eski kayıtlarda özet yoksa yalnız varlık denetimi yapılabilir; daha güçlü kanıt varmış gibi sunulmaz.
- İptal sırasında geç dönen sonuç görevi yeniden tamamlandı yapamaz.
- Çalışan görev başına kullanıcı kimliği/model bağlamı korunur ve iş sonunda eski bağlam geri gelir.
- Önceki tamamlanmış ilgili görevlerden sınırlı yerel bağlam alınır; kayıtlar talimat veya doğruluk garantisi değildir. Başka kullanıcının geçmişi taranmaz.
- Eksik/bozuk kayıt veya saklama hatasında işlem başarı sayılmaz.

## İki mimari seçeneğin kararı

1. Mevcut görev motorunu ortak yürütme sınırı olarak güçlendirmek — bu pakette uygulandı. Mevcut modeli, güvenliği ve araçları korur.
2. LangGraph veya başka bir yürütücüye geçirmek — koşullu akışlar, daha geniş paralellik ve dağıtık çalışma ihtiyaçlarında tekrar değerlendirilecek. Geçişten önce aynı iptal, sahiplik, yan etki ve kurtarma testleri geçmeli.

Bu projelerin hepsini aynı anda kurmak aynı sorumluluğu birden çok motora dağıtır. Yeni bağımlılık yalnız somut ihtiyacı karşılıyorsa eklenir.

## Kaynak projelerin ana plana katkısı

README tanıtımları incelendi; bütün kaynakları denetlenmiş veya Jarvis'e kurulmuş sayılmaz.

| Kaynak | Değerlendirilecek katkı |
|---|---|
| LangGraph | Kalıcı/koşullu yürütme, kesinti ve onay düğümleri |
| Hindsight | Uzun süreli hafıza, sakla/hatırla/çıkarım; mevcut kullanıcı hafızasıyla karşılaştırma |
| Paperclip | Görev/rol/yetki/geçmiş yönetimi ve sonuç incelemesi |
| Agency Agents | Uzman tanımları, format ve kurulum takibi; yürütme motoru değil |
| OpenAI Agents SDK | Araçlar, uzman devri, oturumlar ve izleme |
| smolagents | Kodla çalışan uzman ve izole çalışma ortamı |
| CrewAI | Rol takımları ve olay odaklı akışlar |
| AutoGen | Çok ajanlı örnekler; bakım modu nedeniyle Microsoft Agent Framework de değerlendirilecek |
| VoiceStudio | Ses/video dublaj, yerel API/MCP; AGPL lisansı ve donanım koşulları ayrıca incelenecek |
| REA | Uygulama/binary analizi; yerel kanıt ve sınırlılık raporu |
| Antigravity | Geliştirme platformu; diğer açık kaynak kütüphanelerle aynı kategoride değil |
| AgentSpace | Görev dağıtımı ve çalışma takibi örnekleri; ürün motoru kapalı kaynak |

Bağlantılar: https://github.com/langchain-ai/langgraph · https://github.com/vectorize-io/hindsight · https://github.com/paperclipai/paperclip · https://github.com/msitarzewski/agency-agents-app · https://github.com/openai/openai-agents-python · https://github.com/huggingface/smolagents · https://github.com/crewAIInc/crewAI · https://github.com/microsoft/autogen · https://github.com/debpalash/VoiceStudio · https://github.com/morluto/rea · https://antigravity.google/

## Uygulama sırası ve kabul koşulları

1. Ortak görev yürütme/kurtarma — bu pakette güçlendirildi. Kesinti, yeniden başlatma, iptal, değişmiş dosya ve kullanıcı sınırı testleri geçer.
2. Ortak araç sözleşmesi — sekiz worker'da sonuç kanıtı, girdi alanları, çalışma kimliği, risk ve yeniden yürütme sınıfı uygulandı (`task_results`, `task_tools`). Tarayıcı/kod/dış yayın belirsizliği otomatik tekrar edilmez. Genel PC araçlarının tamamını bu sözleşmeye taşıma açık iştir.
3. Hesap bağlantıları — Gmail, Telegram bot, resmi WhatsApp Business, YouTube ve Instagram profesyonel hesap uyarlayıcılarının bu paketteki alt kapsamı JARVIS_BIRLESIK_KULLANIM.md tablosundadır. Hesap girişi/izin ve canlı kabul açık iştir. Ek okuma, webhook/teslim, yorumlar ve Reels tam yönetimi tamamlanmadı.
4. Üretim zinciri — mevcut belge yolları korundu; yerel görsel/isteğe bağlı ses → video, gerçek akış/süre/boyut kontrolü ve medya → YouTube bağımlılığı eklendi. Genel görsel/video/ses stüdyosu açık iştir.
5. Takip/zamanlama — tek sefer/tekrar okuma-rapor-medya kuyruğu, engine arka plan çalışanı, lease/heartbeat, görev kimliğinden yeniden başlatma ve sahibine bildirim eklendi. PC kapalıyken çalışmaz; dış yayın/tarayıcı/kod otomatik kuyruğa alınmaz.
6. Uzman ekipler — mevcut araştırmacı, üretici, geliştirici, doğrulayıcı görev rolleri sıralı grafikte çalışır. Genel uzman paralelliği ve çakışma yönetimi ileride değerlendirilir.
7. Kalıcı hafıza — kullanıcıya özel görev geçmişi, kaynaklar/tarih/kanıtlar ve sınırlı ilgili görev bağlamı mevcut. Daha kapsamlı bilgi düzeltme/silme ve Hindsight değerlendirmesi açık iştir; yeni hafıza framework'ü kurulmadı.
8. Baştan sona kabul — yerel/fixture akışları ve gerçek FFmpeg üretimi test edildi; gerçek Windows/OAuth/servis/model kalitesi ve canlı sonuç takibi kullanıcı PC'sinde yapılmalı.

## Açık ve dürüst sınırlar

## Birleşik son uygulama — 13 Ekim 2026

Bu bölüm önceki aşama sınırlarını günceller. Ortak `publish`/outbox/yetki yolları, Gmail gönderim, Telegram bot okuma/gönderim, resmi WhatsApp Business metin gönderim, YouTube kanal istatistiği/video yükleme, Instagram profesyonel hesap istatistiği/görsel yayın, yerel FFmpeg video üretimi ve tek sefer/tekrar okuma-üretim kuyruğu eklendi. Mevcut Python motoru ve kabul edilen arayüz korunur. Kurulum/yetki/kullanım ayrıntısı JARVIS_BIRLESIK_KULLANIM.md içindedir.

API uyarlayıcılarının varlığı hesapların bağlı olduğu anlamına gelmez. Canlı hesap/Windows kabulü, WhatsApp webhook geçmişi/teslimi, Instagram Reels/yorum, YouTube yorum takibi, tam bot güncelleme tüketimi, üretim stüdyosu ve genel uzman paralelliği açık işlerdir. Kuyruk dış gönderim/tarayıcı/kod adımlarını otomatik yürütmez; PC ve Jarvis açık olmalıdır.

Gerçek FFmpeg video üretimi doğrulandı; dış hesap gönderimleri ve model çağrıları bu testlerde taklit edildi. Gerçek hesap girişi/izinleri, Windows donanımı ve canlı denemeler gerekir. Şifre/anahtar sohbetten istenmez. Bulut modelini veya ücretli hizmeti bu doğrulamalar sırasında çağırmadım. Queue engine açıkken çalışır; PC kapalıyken çalışmaz. İptal kooperatiftir: sürmekte olan dış API işlemini geriye çeviremez; sonraki adımları durdurur.


## Son genişleme — 13 Ekim 2026

Mesaj kutusu ve teslim durumu, kendi içeriklerine yorum okuma/yanıtlama, aynı Instagram Reels konteynerini takip etme, güvenli rollerin paralel çalışması ve yerel sahneli video üretimi uygulandı. WhatsApp yalnız etkinleştirildikten sonra gelen webhook olaylarını saklar; geçmiş sohbeti API üzerinden çekmez. Ayrıntılar: [Mesaj, yorum ve stüdyo](MESAJ_YORUM_STUDYO.md).

Canlı hesap/OAuth ve dış HTTPS webhook kurulumu, gerçek Windows/mikrofon kabul testi, kullanıcının Piper modeli veya Windows SAPI ile ses kalitesi hâlâ doğrulanmalıdır. Video stüdyosu sahne, görsel, altyazı ve ses montajıdır; fotogerçekçi üretken video modeli içermez. Eski açık iş maddeleri bu yeni kapsamla birlikte okunmalıdır.
