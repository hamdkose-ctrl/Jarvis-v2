# PR test sonucu bekleme kuralı — 23 Ekim 2026

Bu belge, GPT/Codex geliştirme ajanının PR ve gerçek Windows PC watcher sonucu karşısındaki çalışma kuralını sabitler.

## Son karar

- GPT/Codex işi tamamlayınca ayrı `gpt/*` dalına commit/push eder ve gerekiyorsa PR açar; ardından **durur**.
- GPT/Codex PR yorumlarını, CI sonucunu, watcher sonucunu veya merge durumunu kendi kendine periyodik olarak kontrol etmez.
- Gerçek Windows PC watcher yeni SHA'yı bağımsız olarak görür, testleri çalıştırır ve sonucu ilgili PR'a yazar.
- Watcher sonucu PASS veya FAIL olsa da GPT/Codex otomatik düzeltme, yeni commit, push, retry veya merge yapmaz.
- Hamdi açıkça **“sonuca bak”**, **“PR sonucuna bak”** veya eşdeğer bir komut verdiğinde GPT/Codex o anda PR/test sonucunu okur ve yorumlar.
- Sonuç FAIL ise GPT/Codex yalnız Hamdi açıkça **“düzelt”**, **“devam et”** veya eşdeğer bir komut verdiğinde kod değişikliğine başlar.
- Yeni commit/push sonrası GPT/Codex yeniden beklemeye geçer; watcher yeni SHA'yı test eder.
- Aynı SHA için watcher sonucu daha önce üretilmişse GPT/Codex bunun tekrar çalışmasını istemez ve sırf sonucu beklemek için model çağrısı yapmaz.

## Amaç

Model ve ajan kotasını PR/test bekleme döngüsünde tüketmemek; test işini iş PC'sindeki watcher'a, devam kararını Hamdi'ye bırakmak.

## Hedef akış

```text
GPT/Codex işi yapar
→ commit/push + PR
→ DUR

Windows PC watcher
→ yeni SHA'yı test eder
→ sonucu PR'a yazar
→ DUR

Hamdi: “sonuca bak”
→ GPT/Codex sonucu okur
→ PASS/FAIL'i açıklar
→ DUR

Hamdi: “düzelt” (yalnız gerekiyorsa)
→ GPT/Codex düzeltir
→ yeni commit/push
→ yeniden DUR
```

Bu kural, gerekli testlerin yapılmasını azaltmaz; yalnız GPT/Codex'in sonucu beklerken veya polling yaparken gereksiz çalışmasını engeller.
