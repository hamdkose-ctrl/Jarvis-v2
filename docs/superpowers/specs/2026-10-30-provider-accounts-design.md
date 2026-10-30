# Provider accounts — approved target and development checkpoint

User decisions: Gemini/Groq free primary pool; OpenRouter free fallback; installed, suitable Ollama may be selected automatically. GPT/Claude automatic use requires separate opt-in and user-selected models. Paid providers may be selected from the start when opted in. User enters a shared monthly paid budget; an unset budget is not unlimited. Gemini has separate free/paid projects, keys and model choices. User approved a separate read-only Google OAuth connection for actual billing inspection. A checkbox is not provider verification. #452's attestation approach was withdrawn; do not merge that head.

Existing architecture: retain llm/smart_router/user_models; no replacement router, framework or news/Hoca changes. Google OAuth token must remain separate from Gmail/Calendar. Never expose credential-bearing lookup URLs or raw exceptions. Key-project identity must come from Google lookupKey, not a user-entered unrelated project. Billing disabled is not evidence of model availability or free quota.

Restored and locally verified in this checkpoint:
- Separate free/paid key paths and model lists. Existing defaults still read free slot. Saving does not generate or activate paid use.
- Read-only lookupKey -> CRM v3 project -> billingInfo check, owner-bound OAuth. UI checks the requested slot.
- Models API discovery filters generateContent; independent selectors for both slots. Metadata listing is not pricing evidence.
- Updating a catalog changes only its select; other drafts survive and results are discarded if owner changes.
- 19 backend regressions, UI draft/owner regression and full modules.validation passed after recovery. Previous scratch-only work was lost across sessions; this branch is a durable development checkpoint, not a release.

## Remaining implementation, in order

1. Bind actual billing results to owner, tier and exact key fingerprint. Protect local receipt data, invalidate on key change/failure, refresh before generation when stale. Status queries must not silently open login or claim unchecked billing verified.
2. Connect the receipt to both automatic selection and direct/auxiliary Gemini call paths. Recheck the exact key used by the client. Never fall through to the paid key. Keep missing access/quota/429/network/billing reasons distinct. Test stale/key-change/restart and owner isolation.
3. Keep Gemini paid route disabled until opt-in, allowed models, real cost accounting and shared budget reservation are connected. No paid retry after ambiguous timeout; unknown price/cost cannot be treated as zero.
4. OpenRouter: verify configured free routing/model metadata from official API; never fabricate evidence. Groq: no account-plan API has yet been found; resolve an honest verification method before labeling it verified. Do not revive rejected user attestation as automatic proof.
5. Full local validation, exact-head Windows CI, real PC/account acceptance. Unit/model discovery PASS is not live OAuth, quota, billing or inference acceptance.

No new PR and no merge authorization for this checkpoint. Keep #452 blocked. Only GitHub connector for repository operations; no main push, force or rebase. Tests before behavior changes. Final review and current-main delta check before presenting a release candidate.
