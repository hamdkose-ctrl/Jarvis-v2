# Finans takibi (AGENTS.md alan notları)

Plan: `raporlar/finans-takibi-plan-2026-10-18.md`. Kapsam yalnız okuma: piyasa verisi, takip listesi, fiyat alarmı. Alım/satım, para hareketi, banka/borsa hesabı bağlantısı yok. Hamdi'nin kararı (2026-10-18): resmî kaynaklar + gayriresmî kaynaklar (BIST, gram altın) ayarsız, hazır açık; ~15 dk gecikme sorun değil, cevapta kaynak ve gecikme yazılır.

## Kur cevabı ve çevirisi — 18 Ekim 2026
- `modules/finance.py`: `answer(metin)` kur sorusuysa cevap, değilse `None` döner. `engine_commands.handle` eski `"dolar" in cmd_lower` alt dize kontrolünün yerinde onu çağırır (sıra değişmedi). Model çağrılmaz.
- Tetik: para birimi (Türkçe ekleriyle; ASCII yazım, `$ € £ ₺`, "yüz", "iki yüz elli", "10 bin", "iki buçuk") + soru işareti sözcüğü (kaç, ne kadar, kur, fiyat, eder, çevir, olarak, cinsinden). Geçmiş (dün, geçen hafta, kaçtı), yorum/tahmin (neden, sence, olur), alarm/takip (hatırlat, haber ver, olunca) ve tanım ("dolar nedir", "kur" yoksa) cümleleri `None` döner. "euro 2024" yıl izlerse para birimi sayılmaz; "yeni" yen değildir.
- Para birimleri: USD, EUR (euro/avro), GBP (sterlin/pound/İngiliz lirası), CHF, JPY (100 birim TCMB'de bölünür), AZN, SAR, RUB, CNY, CAD, AUD, TRY (lira/TL). Biçimler: "dolar kaç lira", "dolar ve euro ne kadar" (liste), "100 dolar kaç TL", "1000 lira kaç dolar", "euro kaç dolar" (çapraz), "50 euroyu dolara çevir".
- `chat_translation.resolve`, `finance.is_conversion` doğruysa (miktar ya da iki para birimi) metin çevirisi saymaz; "bu metni euroya çevir" yine metin çevirisidir.
- Kaynak: TCMB `today.xml` döviz satış (bülten tarihiyle), TCMB'de olmayan para birimi ya da TCMB hatasında Frankfurter v2 `/rate/{kod}/try`. İkisi de `public_sources.fetch` ile (HTTPS, boyut/süre sınırı, gizlilik modu). XML'de `ENTITY` reddedilir, DOCTYPE atılır. Önbellek 10 dk (`_CACHE`), TCMB tek istekte tüm kurlar. Cevap "Kaynak: …, tarih" ve "Banka ve döviz bürosu fiyatı farklı olabilir" der.
- Hata: gizlilik modu mesajı aynen; ağ yoksa `ollama_hint.NO_INTERNET`; internet var ama kaynaklar yoksa "Kur kaynaklarına (TCMB ve Frankfurter) şu an ulaşamadım". TCMB hatası `diagnostics.record_failure` ile günlüğe yazılır, Frankfurter'a geçiş cevapta kaynak adıyla görünür.
- Test: `tests/test_finance.py` (elle kurulmuş TCMB/Frankfurter yanıt örnekleri, `public_sources.fetch` taklit). Canlı TCMB/Frankfurter, Windows'ta sesli söyleyiş ve tam motor akışı denenmedi; geliştirme ortamı bu adreslere erişemiyor.
- Sıradaki: altın ve kripto, takip listesi, modelsiz fiyat alarmı (plan dosyası 4. bölüm).
