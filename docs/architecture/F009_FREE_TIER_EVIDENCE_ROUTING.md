# F-009 — Free-tier evidence ile strict zero-cost routing

## Amaç

Mevcut `smart_router` ve `failure_policy` altyapısını değiştirmeden, otomatik cloud rota seçimini yalnız doğrulanmış ve süresi geçmemiş ücretsiz-katman kanıtına bağlamak. Ücretli fallback eklenmez.

## Mevcut yapının reuse edilen parçaları

- `modules/smart_router.py`: görev türü, provider sırası, owner state, health/cooldown, fail-closed provider exhaustion (OpenRouter ve acil rota Provider P0-3a ile tamamen kaldırıldı).
- `modules/failure_policy.py`: provider hata sınıflandırması, cooldown ve `PROVIDER_*` reason-code standardı.
- `modules/usage_meter.py`: gerçek çağrı ve sağlayıcının bildirdiği son limit başlıklarını gözlemleme. Bu limit kaydı ücretsiz-katman kanıtı değildir.

## Evidence modeli

Evidence mevcut owner router JSON durumunda `free_tier_evidence[provider][model]` altında tutulur. Alanlar:

- `provider`, `model`
- `free_tier_verified`
- `source`, `evidence_ref`
- `verified_at`, `expires_at`, `ttl_seconds`
- `eligibility`
- `quota_state`, opsiyonel `quota_remaining`
- `hard_stop_guaranteed`
- `verification_status`
- `reason`

Evidence ayrı servis, daemon veya scheduler kurmaz. TTL ihtiyaç anında değerlendirilir; stale kayıt otomatik allow değildir ve yeniden doğrulama ister.

## Strict zero-cost kapısı

Otomatik cloud candidate ancak aşağıdaki koşulların tümünde açılır:

1. kullanıcı cloud ücretsiz hesabını ayrıca onaylamıştır (`cloud_free_confirmed=True`),
2. kullanıcıya ait provider anahtarı vardır,
3. exact provider/model için provenance'lı evidence vardır,
4. evidence `verified` ve süresi geçmemiştir,
5. eligibility `eligible` durumundadır,
6. hard-stop guarantee doğrulanmıştır,
7. kota biliniyorsa tükenmemiştir; `unknown` quota state allow değildir,
8. mevcut provider health/cooldown kapısı açıktır.

`UNKNOWN = ALLOW` değildir. Evidence missing/stale/ineligible/quota exhausted/hard-stop unverified durumları `PROVIDER_FREE_TIER_*` reason-code ile skip edilir.

## Korunan davranış

- OpenAI/Anthropic otomatik havuza eklenmez.
- Acil/üçüncü bir yedek rota yoktur; zincir dışı hiçbir sağlayıcı denenmez. Eski router state'indeki OpenRouter anahtarı, modeli ve evidence satırları açılışta diskten silinir.
- 429/ağ/kimlik hatalarının mevcut `failure_policy` cooldown ve fallback akışı korunur.
- Uygun ücretsiz route kalmazsa `ProviderExhaustedError` ile fail-closed durulur ve kullanıcı mesajında `Ücretli modele geçilmedi` korunur.
- Yerel/Ollama rota cloud evidence gerektirmez.

## Kota gözlemi sınırı

`usage_meter.observe_limits()` ile kaydedilen provider limit başlıkları router durumunda gözlem olarak gösterilebilir; tek başına `free_tier_verified`, eligibility veya hard-stop guarantee üretmez. Bu ayrım, sağlayıcının bir limit başlığı döndürmesini yanlışlıkla “ücretsizdir” kanıtına çevirmeyi engeller.
