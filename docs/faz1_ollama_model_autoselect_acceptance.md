# Faz 1 — Ollama installed-model autoselect acceptance

Bu küçük kapanış düzeltmesi, gerçek provider acceptance sırasında görülen stale yerel model seçimi kusurunu izler.

Ana invariant:

> Stale local-model tercihi artık kurulu Ollama modelini engellemez; runtime yalnız gerçekten kurulu modele bağlanır.

- Kullanıcı tercihi diskte korunur; yalnız kuruluysa runtime authority olur.
- Kullanıcı tercihi stale ise kurulu model listesinden deterministik ilk model kullanılır.
- Kullanıcı override yoksa kurulu settings `ollama_model` korunur.
- Hiç model yoksa fail-closed `LocalModelError` korunur.
- Model indirme/pull yapılmaz.
- F-009 free-tier evidence ve paid fallback politikası değiştirilmez.
- LM Studio / llama.cpp mevcut model çözümleme davranışı korunur.

Gerçek PC acceptance beklentisi: stale `llama3.2` tercihi + kurulu `qwen2.5-coder:7b` ile Jarvis kullanıcıdan elle model düzeltmesi istemeden `qwen2.5-coder:7b` üzerinden cevap vermelidir.
