# Historical redirect — BEKLEYEN_ISLER

> **AKTİF İŞ LİSTESİ / ROADMAP DEĞİLDİR.**
>
> Güncel iş sırası ve yapılacaklar için tek authority: [`Jarvis_Yol_Haritasi.md`](Jarvis_Yol_Haritasi.md)
>
> Bu dosyanın tarihsel içeriği arşive taşındı: [`archive/roadmaps/BEKLEYEN_ISLER.md`](archive/roadmaps/BEKLEYEN_ISLER.md)

Bu yol yalnız eski belge bağlantılarının kırılmaması için tutulur. Buradaki eski kayıtlar yeni görev açmak için kullanılmaz.

### BRAIN-03 dilim4 — mevcut branch, kapanış açık

`gpt/brain-03-output-diagnose`: çıktı/teşhis model→Core→domain hattı ve eski iki doğal-dil kalıp sahibinin kaldırılması uygulanıyor. Yeni testler model wiring, oturum artifact kimliği, iptal ve gerçek Word kayıt adapterını kapsar; mock başarı gerçek model semantik kabulü değildir. Ücretsiz üretim rotası ön denetimi yalnız ollama adayı buldu (gemini rota dışı, groq/cloudflare ücretsiz hesap teyitsiz); canlı holdout çalışmadı ve kapı gevşetilmedi. Yerel tam validation exit 0 (5.204 Python testi: 5.203 başarılı, 1 platform skip; tüm JS/smoke ve 47 son stability testi başarılı); exact-head Windows CI ve aynı SHA PC watcher kapanış için açık kalır. Kullanıcının ayrı gönderim/PR onayı olmadan push veya PR açılmadı. Dilim5/BRAIN-04'e geçildiği iddia edilmez.

Dilim4 gerçek model kabulü Windows hesabında çalıştırılmak üzere aynı PR'ın CI bootstrap'ına bağlandı. Scriptin normal çağrısı plan gösterir; `--run` üretim rotasında 20 sentetik holdout isteğidir. Rapor artifact'ı commit ve corpus hash'i taşır. Self-hosted runner hesabında etkin Jarvis profili/uygun rota bulunmazsa exit2 ve unmeasured sonucu açık blocker'dır; CI PASS veya mocked wiring ile kapatılamaz.
