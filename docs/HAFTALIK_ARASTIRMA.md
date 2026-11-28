# Haftalık araştırma turu

Bir konuyu her hafta kendiliğinden araştırıp rapora yazdırmak için:

```
haftalık araştırma turu kur: yapay zeka mevzuatı
```

Jarvis şunu yapar:

1. Konuyu araştırma isteğine çevirir (son **7 gün** penceresi).
2. İki görevli bir iş kuyruğa yazar: `research` (kaynaklı arama) ve `writer` (Markdown rapor).
3. İşi **her pazartesi 09:00** (`0 9 * * 1`) çalışacak şekilde cron'a bağlar.

Yanıt olarak cron ifadesini, pencereyi ve iptal kimliğini verir.

## Nasıl kontrol edersin

- `kuyruk` yazarak bekleyen işleri görürsün; haftalık tur orada cron etiketiyle durur.
- `kuyruk çalıştır <kimlik>` ile beklemeden bir kez çalıştırırsın.
- `kuyruk iptal <kimlik>` ile turu kaldırırsın.

## Sınırlar (dürüst)

- Kuyruk **Jarvis açıkken** çalışır. Bilgisayar kapalıyken hiçbir şey çalışmaz; bulut zamanlayıcı yoktur.
- Rapor, araştırma görevinin gerçekten okuduğu kaynaklara dayanır. Kaynak bulunamazsa uydurmaz, eksik olduğunu söyler.
- Tur yalnız okuma ve rapor yazar; dışarıya gönderim yapmaz.

## İlgili yer

- `modules/weekly_research.py` — turu kuran kod.
- `modules/task_queue.py` — cron'lu iş kuyruğu.
- Test: `tests/test_weekly_research.py`.
