# F-009 — Free-tier evidence ile strict zero-cost routing

## Amaç

Mevcut `smart_router` ve `failure_policy` altyapısını değiştirmeden, otomatik cloud rota seçimini yalnız doğrulanmış ve süresi geçmemiş ücretsiz-katman kanıtına bağlamak. Ücretli fallback eklenmez.

P0 provider-authority cutover sınırı:

`llm public call → Smart Router seçim/transition → llm strict provider-local execution → success veya classified failure → Smart Router sonraki uygun ücretsiz rota`

`modules/smart_router.py` otomatik provider sırası, preference ordering, exact free-tier evidence allow/deny, provider transition, cooldown skip ve exhausted kararının tek authority'sidir. `modules/llm.py` yalnız seçilen provider transport'unu, aynı provider içindeki bounded retry/model fallback'i, timeout/response parsing ve usage ölçümünü yürütür. Router callback'i concrete provider ile strict/provider-local çalışır; `llm.py` Gemini→Groq, Groq→Gemini, Ollama→Gemini veya Gemini→Ollama geçişi yapmaz.

## Mevcut yapının reuse edilen parçaları

- `modules/smart_router.py`: görev türü, provider sırası, owner state, health/cooldown, fail-closed provider exhaustion ve OpenRouter ücretsiz acil rota.
- `modules/failure_policy.py`: provider hata sınıflandırması, cooldown ve `PROVIDER_*` reason-code standardı.
- `modules/usage_meter.py`: gerçek çağrı ve sağlayıcının bildirdiği son limit başlıklarını gözlemleme. Bu limit kaydı ücretsiz-katman kanıtı değildir.

Yeni router, provider sistemi, scheduler, agent veya ikinci evidence/policy motoru kurulmaz.

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

**Bu P0 cutover gerçek free-tier evidence üreticisi eklemez.** API key bulunması, provider preference, `cloud_free_confirmed` checkbox'ı, usage/quota header'ı veya billing-disabled bilgisi tek başına evidence üretmez. Production account/evidence producer ayrı sonraki iştir; producer yokken cloud route'ların fail-closed kalması beklenen davranıştır.

## Strict zero-cost kapısı

Otomatik veya preference ile öne alınmış cloud candidate ancak aşağıdaki koşulların tümünde açılır:

1. kullanıcı cloud ücretsiz hesabını ayrıca onaylamıştır (`cloud_free_confirmed=True`),
2. kullanıcıya ait provider anahtarı vardır,
3. exact provider/model için provenance'lı evidence vardır,
4. evidence `verified` ve süresi geçmemiştir,
5. eligibility `eligible` durumundadır,
6. hard-stop guarantee doğrulanmıştır,
7. kota biliniyorsa tükenmemiştir; `unknown` quota state allow değildir,
8. mevcut provider health/cooldown kapısı açıktır.

`UNKNOWN = ALLOW` değildir. Evidence missing/stale/ineligible/quota exhausted/hard-stop unverified durumları `PROVIDER_FREE_TIER_*` reason-code ile skip edilir.

Provider-local model fallback de exact-model evidence sınırını geçmek zorundadır. Örneğin Gemini model A başarısızsa model B yalnız B için de geçerli evidence varsa denenebilir. Aynı kural Groq model fallback'i için geçerlidir.

## Provider preference authority değildir

`Gemini kullan`, `Groq kullan`, `Ollama kullan` veya `OpenRouter kullan` seçimi yalnız Router aday sırasına verilen preference'tır.

Preference:

- free-tier evidence değildir,
- paid consent değildir,
- permission değildir,
- ücretli fallback yetkisi değildir,
- strict evidence gate'i bypass edemez.

Tercih edilen provider uygun değilse Router diğer doğrulanmış ücretsiz/local route'ları deneyebilir; hiçbiri uygun değilse `ProviderExhaustedError` ile dürüstçe durur. Tercih edilen route evidence eksikliği nedeniyle atlandıysa bu neden quota exhausted gibi yanlış bir sebebe çevrilmez.

## Korunan davranış

- `provider=auto` mevcut task-order davranışını kullanır.
- `provider=gemini|groq|ollama|openrouter` free-provider preference olarak Smart Router'a girer.
- `openrouter/free` veya `:free` dışındaki OpenRouter model otomatik/tercihli ücretsiz rota olamaz.
- OpenAI/Anthropic otomatik havuza eklenmez; mevcut explicit paid activation sözleşmesinde kalır.
- OpenRouter acil yedeği de kendi exact model evidence'ı olmadan çalışmaz.
- Gemini/Groq aynı-provider retry ve exact-evidence'lı model fallback davranışları korunur.
- Ollama büyük kurulu model → effective base model fallback'i provider-local kalır.
- Uygun ücretsiz route kalmazsa `ProviderExhaustedError` ile fail-closed durulur ve kullanıcı mesajında `Ücretli modele geçilmedi` korunur.
- Yerel/Ollama rota cloud evidence gerektirmez.
- `privacy.mode() == "yerel"` durumunda Gemini/Groq/OpenRouter denenmez.

## Auxiliary Gemini sınırı

Embedding, STT, model-health/measure ve Gemini Live gibi gerçek cloud generation/call yolları da owner + exact Gemini model için aynı Smart Router evidence kararını kullanır. `gemini_aux_allowed()` ikinci policy motoru değildir; Router'ın read-only `provider_allowed(...)` kararına delegasyon yapar.

- embedding: `gemini-embedding-001` exact evidence ister,
- STT: çalışacak Gemini model(ler)i Router evidence filtresinden geçer,
- model health/measure: yalnız exact evidence'ı olan modeller gerçek çağrı yapabilir,
- Live: configured Live model adı exact evidence gate'ine verilir.

Bu sınır Live semantic migration değildir; yalnız provider/budget authority kapısıdır.

## Key save generation değildir

Gemini veya Groq API key kaydetmek:

- generation çağrısı başlatmaz,
- ücretsiz kullanım doğrulaması sayılmaz,
- paid consent oluşturmaz,
- provider fallback yetkisi vermez.

UI yalnız key/preference kaydeder ve doğru durumu gösterir. Gerçek generation isteyen ölçüm/tanı çağrıları da verified-free evidence veya mevcut explicit paid-provider sözleşmesi olmadan cloud generation başlatamaz.

## Kota gözlemi sınırı

`usage_meter.observe_limits()` ile kaydedilen provider limit başlıkları router durumunda gözlem olarak gösterilebilir; tek başına `free_tier_verified`, eligibility veya hard-stop guarantee üretmez. Bu ayrım, sağlayıcının bir limit başlığı döndürmesini yanlışlıkla “ücretsizdir” kanıtına çevirmeyi engeller.
