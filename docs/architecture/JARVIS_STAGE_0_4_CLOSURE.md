# Jarvis Aşama 0–4 kapanışı ve sonraki sıra

**Durum:** Kapanış kriteri ve planlama kaydı
**Tarih:** 24 Ekim 2026

Bu belge Aşama 0–4 mimarisinin "tamamlandı" kabulünü ölçülebilir kılar ve sonraki işleri kapsamlarına göre sıralar. Yeni runtime, permission otoritesi veya execution engine tanımlamaz.

## 0–4 kapanış kriteri

Aşağıdaki dört kanıt aynı güncel `main` tabanı için mevcut olmadan 0–4 "mimari olarak kapandı" diye ilan edilmez:

1. `modules.architecture_guard` BLOCKER üretmeden geçer; bilinen WARNING'ler ya açık bir defer kaydına ya da ayrı kabul edilmiş iş kartına bağlıdır.
2. Tam `python -X utf8 -m modules.validation` sonucu `Tüm test grupları başarılı.` olur.
3. Güncel `main`de self-hosted Windows doğrulaması ve ilgili gerçek Windows PC acceptance kanıtı vardır. Kapsam dışı canlı hesap/cihaz/news senaryosu, ilgisiz doküman veya yerel-hook PR'ını bloklayan bir kabul kapısı değildir.
4. En az bir temsilci durable uçtan uca senaryo şu hattı kanıtlar: `intent → effect → worker → crash/restart → reconcile → WorkerResult fence → Reducer/CAS evidence`; doğrulanmış receipt sonrası dış etki tekrar etmez.

Bu kriterler yalnız mevcut omurganın kabulüdür; tüm ürün alanlarının veya gelecek subscription tasarımının tamamlandığı iddiası değildir.

## Sonraki işlerin sırası

1. **RuntimeEvent subscription borcu:** Yalnız kalıcı subscription identity, lifecycle, resume/fan-out ve gerçek producer gerektiğinde açılır. Ayrıntı: [Durable RuntimeEvent subscription notu](../roadmap-runtime-event-subscription-notu.md). Mevcut `source_watch` bu iş açılmadan yapay biçimde GoalState'e bağlanmaz.
2. **Finance domain kararı:** Finance, Communication'ın alt yolu değildir. Salt-okuma piyasa/kur analizi ile gelecekteki para/hak-sahipliği etkileri ayrı capability/effect politikalarıyla tasarlanır. Alım-satım, hesap bağlantısı veya para hareketi bu kararın kapsamında değildir.
3. **Sağlayıcı dayanıklılık paketi:** 429, yedeksiz sağlayıcı, Ollama'nın kurulu olmaması ve çevrimdışı durum anlaşılır sonuç, sınırlı retry ve fail-closed davranışla ele alınır. Bu paket 0–4 blocker'ı değildir; yeni sağlayıcı, ücretli fallback veya gizli otomatik retry eklemez.
4. **Canonical GoalState geçişi:** Legacy compatibility görünümü daraltılır; canonical GoalState tek source of truth olacak şekilde ayrı migration ve geri dönüş planıyla ele alınır. Büyük-bang migration yapılmaz.

## Gelecek alan eşleme notu

| Gelecek alan | Doğru sahiplik / önkoşul | Şimdiki durum |
|---|---|---|
| Düşük donanım | Görsel teslimat/deneyim kabulü; ölçüm ve gerçek PC kanıtı | Planlı, runtime çekirdeğine eklenmez |
| Cümle ayrımı ve giriş kalitesi | Tek giriş/intent sınıflandırması; ses-yazı regresyonları | Alan düzeyi iş, yeni planner değildir |
| Sosyal medya | Communication/publish capability; kesin hedef, JIT izin, receipt/evidence | Gelecek ürün alanı |
| WhatsApp/Telegram | Communication/message_out capability; hesap ve alıcı sınırı | Gelecek ürün alanı |
| Finansal analiz | Ayrı Finance domain; varsayılan salt okuma | Ayrı karar kartı |
| Para/hak-sahipliği etkisi | Finance domain + `external_write`/uygun effect politikası + açık onay | Tasarlanmadı, otomatik açılmaz |

Bu tablo eski kapalı PR'ları arşivlemek için değildir. Yalnız ileride yeniden gündeme gelecek alanların doğru mimari sınırını korur.

## Operasyonel sınır

Private Free repoda GitHub ruleset sunucu tarafında enforce edilmez. Mevcut koruma: PR prosedürü, `testler-windows`, PC watcher, Main bekçisi ve repo-yerel Git hook'larıdır. `--no-verify`, başka makine veya doğrudan API push bu yerel hook'ları aşabilir; ücretli plan/organizasyon değişikliği ayrı maliyet kararıdır.
