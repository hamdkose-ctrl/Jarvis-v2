# Router token budget reservations (developer controlled)

`modules/router_quota.py` reserves local **RPM/RPD request counts** and,
when explicitly configured, **TPM/TPD conservative token budgets** in one
SQLite `BEGIN IMMEDIATE` transaction. An enabled policy names an **exact**
provider/model, a HTTPS evidence source and a recent verified/expiry interval.
The `POLICIES` registry carries only rows the developer reviewed against an
official published limits page with a bounded verification date: currently the
Groq Free plan base RPM/RPD (30/1000) for the three routed text models, expiring
23 Nov 2026 19:00 UTC. Providers whose official pages publish no static free-tier
request ceilings (Gemini, Cloudflare) remain without a policy. Nothing is ever
guessed and this does not grant free-tier eligibility.

When `tpm/tpd` are configured, the caller must supply a trusted
`ModelRequest.token_budget` that is at least `max_output_tokens` and
safely bounds **all input plus maximum output tokens** after provider
formatting. This is not an arbitrary character/token estimate. If such a bound
is not available, the Router skips this candidate **without a network send**;
it may still use another eligible candidate, never an automatic paid fallback.
Declaring a bound does **not** prove the adapter observed it: provider-specific
input packing and token measurement still require verification before real
account policies are switched on.

Both rolling windows count each physical adapter attempt and reserve its full
token budget before the send. Failed attempts are not refunded. An upgraded
database may contain earlier request-only records with unknown token cost.
Those records are conservatively marked `-1`; when token limits are enabled,
requests for that owner/provider/model stop until unknown usage is out of the
24-hour window. Older request-only policies continue working unchanged.

All state is per owner/provider/exact model and cross-process atomic. No
prompts, tokens, credentials or responses are stored, only time and units.

Not yet done: actual verified per-project/provider limits, quota policy UI,
accurate provider token upper-bound contracts, neuron usage, third-party
traffic/billing hard-stops, custom provider adapters/UI and full end-to-end
multi-provider live acceptance. These need deliberate developer integration
and tests; Jarvis never auto-installs provider capabilities.
