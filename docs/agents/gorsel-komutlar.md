# Görsel komutlar

## Görsel üretimi v1 — 25 Ekim 2026

`modules/image_gen.py`: kullanıcının doğal dille istediği bir görseli
(mindmap/akış şeması/infografik/zaman çizelgesi/el yazısı/teknik çizim/
genel görselleştirme — 7 tür, Hamdi'nin kararıyla hiçbiri literal bir
komut adı değil, "süreç özeti" gibi doğal ifadeyle tetiklenecek) üretmek
için Cloudflare Workers AI'nin FLUX modelini çağıran, salt üretim/iletişim
katmanı.

**Neden Cloudflare, neden Gemini değil:** Gemini'nin güncel görsel üretim
modellerinde (Nano Banana ailesi: `gemini-nano-banana-2.1`,
`gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image`) ücretsiz katman
yok, hepsi resim başına ücretli. `AGENTS.md`'deki "ücretli sağlayıcılar
otomatik havuza girmez" kuralı nedeniyle varsayılan olarak kullanılmadı.
Cloudflare Workers AI'nin FLUX modeli (`@cf/black-forest-labs/flux-1-schnell`)
kredi kartı istemeden günlük 10.000 Neuron ücretsiz kota veriyor (resim
başına ~14 Neuron, günde kabaca birkaç yüz görsel).

**Anahtar deseni:** `modules/llm.py`'deki `user_key`/`user_groq_key` ile
birebir aynı — kullanıcıya özel, `privacy.protect` ile korumalı, ayrı
dosyalarda (`<kullanıcı>.cf_account.txt`, `<kullanıcı>.cf_token.txt`)
saklanan Cloudflare hesap kimliği + API token. Kullanıcılar arası fallback
yok; anahtarı olmayan kullanıcı için `NO_KEY` hatasıyla reddedilir.

**Kapsam dışı (bilinçli):** Bu modül hangi görselin ne zaman, hangi
prompt'la isteneceğine karar vermez — doğal dil tetikleme ve 7 görsel
türü için prompt/orkestrasyon katmanı ayrı bir iş olarak planlandı, henüz
yazılmadı. Çizimi her zaman model yapar; kod hiçbir pikseli kendisi
çizmez (Hamdi'nin açık kararı).

**Doğrulama:** `tests/test_image_gen.py` (13 test, ağa çıkmaz — sahte
`_session` ile). Ayrıca elle, gerçek bir PNG baytı (1×1 piksel) ile
uçtan uca akış (URL/Authorization header/yanıt çözümleme) çalıştırılıp
doğru PNG imzasıyla (`\x89PNG`) döndüğü doğrulandı. Gerçek Cloudflare
API'sine canlı çağrı bu sandbox'ın ağ izin listesi dışında olduğu için
yapılamadı — bu, Hamdi'nin PC'sinde ayrıca denenmeli.
