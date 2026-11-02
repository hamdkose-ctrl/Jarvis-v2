# Jarvis-v2 Docs — Authority Index

## Tek aktif uygulama yolu

Jarvis-v2'nin **tek aktif uygulama yol haritası**:

- [`Jarvis_Yol_Haritasi.md`](Jarvis_Yol_Haritasi.md)

Başka hiçbir plan, migration map, ledger, acceptance belgesi, fikir listesi veya tarihsel kayıt bağımsız roadmap authority taşımaz.

## Fikir / backlog havuzu

- [`JARVIS_FIKIR_DEPOSU.md`](JARVIS_FIKIR_DEPOSU.md)

Fikir Deposu roadmap değildir. Buradaki fikirler otomatik işe dönüşmez; yalnız Hamdi açıkça **“aktar”** dediğinde aktif yol haritasına alınır.

## Mimari / spec / migration / ledger

`docs/architecture/` altındaki belgeler sözleşme, mimari karar, migration veya uygulama tasarımı taşır. Bunlar nasıl yapılacağını ya da belirli bir geçişin sınırını tarif edebilir; kendi başlarına yeni iş sırası oluşturmaz.

Özellikle:

- `JARVIS_PROGRAM_LEDGER_V1.md` = karar/handoff ledger'ı, roadmap değil.
- `JARVIS_BRAIN_MIGRATION_MAP_V1.md` = scoped migration belgesi, roadmap değil.
- `JARVIS_AUTONOMOUS_FREE_RUNTIME_V1_1*.md` = frozen architecture/implementation plan, roadmap authority değil.

## Tarihsel planlar

Eski roadmap/plan/kalan-iş belgelerinin tam içerikleri [`archive/roadmaps/`](archive/roadmaps/) altında saklanır. Tarihsel kanıt olarak okunabilirler; yeni görev veya öncelik çıkarmak için kullanılmazlar.

Eski aktif bağlantıları kırmamak için bazı eski dosya yollarında yalnız küçük **historical redirect** dosyaları tutulur. Redirect'in kendisi plan değildir.

## Çakışma kuralı

Bir tarihsel belge veya scoped spec güncel iş sırası konusunda farklı bir şey söylüyorsa uygulama sırası için `docs/Jarvis_Yol_Haritasi.md` esas alınır. Kodun gerçekten mevcut davranışı konusunda ise güncel `main` doğrulanmadan belge iddiası uygulanmış sayılmaz.
