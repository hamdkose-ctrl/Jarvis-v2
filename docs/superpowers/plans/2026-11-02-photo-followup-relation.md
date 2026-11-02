# Photo Follow-up Relation Canonicalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pending telefon fotoğrafının sonraki kullanıcı cümlesiyle ilişkisini surface regex'i yerine canonical Understanding kararıyla belirlemek.

**Architecture:** `pending_photo` state zaten `brain_entry._state_refs()` ile canonical `ActiveContext`e giriyor. Understanding bu state varken foto-follow-up semantiğini `ConversationRelation.ANSWER_TO_PENDING` olarak önerir; `engine_commands` yalnız bound entry'nin state-gate/relation sonucunu tüketir. TTL, owner fence ve `_photo_action` execution sahibi değişmez.

**Tech Stack:** Python 3.13, unittest, mevcut Brain contracts/gates/entry pipeline.

**Spec:** `docs/superpowers/specs/2026-11-02-photo-followup-relation-design.md`

## Global Constraints

- `main`e doğrudan yazma; branch `gpt/brain-photo-followup-relation`.
- Force/rebase yok.
- Önce düşen test.
- `State exists != next utterance belongs to that state` korunur.
- Exact cancel mevcut `phone_photo.cancel` bounded gate'inde kalır.
- Foto execution/vision, TTL ve owner davranışı değişmez.
- 17 orphan dispatch ve notes borcu kapsam dışı.

## Review Focus

- Pending foto varken unrelated sohbetin yanlışlıkla foto follow-up sayılması.
- Pending foto + başka pending state birlikteyken yanlış state'in consume edilmesi.
- Exact `iptal`in semantic relation'a kayıp bounded gate'i bypass etmesi.
- 600 sn geçmiş foto state'inin yeni mesajı consume etmesi.
- `analiz et` / `ne yazıyor` / `bu nedir` gibi mevcut ürün davranışlarının kaybolması.

---

### Task 1: RED — Canonical photo relation contract

**Files:**
- Create: `tests/test_brain_photo_followup_relation.py`

**Interfaces:**
- Consumes: `brain_understanding.understand(...)`, `ActiveContext`, `ContextReference`, `ConversationRelation`.
- Produces: regression contract for pending photo follow-up relation.

- [ ] **Step 1: Write failing Understanding tests**
  - pending `pending_photo` + `analiz et` → `ANSWER_TO_PENDING`.
  - pending `pending_photo` + `ne yazıyor` → `ANSWER_TO_PENDING`.
  - pending `pending_photo` + `yarın toplantım var` → `NEW_REQUEST`.
  - no pending photo + `analiz et` must not become photo answer solely from text.

- [ ] **Step 2: Run focused test and verify RED**
  Run: `python -X utf8 -m unittest tests.test_brain_photo_followup_relation`
  Expected: photo relation assertions fail because current Understanding has no pending-photo answer rule.

- [ ] **Step 3: Commit RED**
  Commit message: `test: define canonical photo follow-up relation`

### Task 2: GREEN — Move relation ownership to Understanding

**Files:**
- Modify: `modules/brain_understanding.py`

**Interfaces:**
- Produces: canonical photo-follow-up `ConversationRelation.ANSWER_TO_PENDING` decision from `pending_photo` state.

- [ ] **Step 1: Add minimal photo-follow-up recognizer in Understanding**
  It must run only when `ActiveContext.pending_references` contains owner-bound `pending_photo` from `engine_commands`. Reuse current product phrase coverage from `_PHOTO_INTENT`, but keep it inside Understanding and bounded to the pending-photo state.

- [ ] **Step 2: Preserve precedence**
  Context-control/correction and exact bounded protocols are not reclassified as photo semantic answers. Generic unrelated chat stays `NEW_REQUEST`.

- [ ] **Step 3: Run focused Understanding tests**
  Expected: PASS.

- [ ] **Step 4: Commit**
  Commit message: `feat: canonicalize photo follow-up relation`

### Task 3: RED/GREEN — Handler consumes canonical decision only

**Files:**
- Modify: `tests/test_brain_photo_followup_relation.py`
- Modify: `modules/engine_commands.py`
- Modify: `modules/engine_runtime.py`

**Interfaces:**
- Consumes: `brain_entry.current()`, `brain_entry.matched_protocol(...)`, Understanding relation.
- Produces: unchanged photo execution behavior without `_PHOTO_INTENT`.

- [ ] **Step 1: Add failing handler tests**
  - bound entry `ANSWER_TO_PENDING` + live pending photo → `_photo_action(path, command)` result and pending removed.
  - bound entry `NEW_REQUEST` + live pending photo → `_photo_action` not called; pending removed; request continues normal path.
  - `phone_photo.cancel` state-gate match → cancellation message, pending removed, no photo action.
  - expired pending photo → no photo action.

- [ ] **Step 2: Verify RED against existing handler**
  Expected: tests that forbid `_PHOTO_INTENT` ownership fail.

- [ ] **Step 3: Replace surface semantic checks**
  In `engine_commands`, keep TTL. Use canonical state protocol for cancel and bound Understanding relation for follow-up. Do not inspect raw text for photo semantic meaning.

- [ ] **Step 4: Remove `runtime._PHOTO_INTENT`**
  Delete only this semantic regex from `engine_runtime`; no unrelated runtime regex cleanup.

- [ ] **Step 5: Run focused tests**
  Expected: PASS.

- [ ] **Step 6: Commit**
  Commit message: `refactor: consume canonical photo relation`

### Task 4: Truth-sync and layered verification

**Files:**
- Modify: `docs/Jarvis_Yol_Haritasi.md`
- Modify: `docs/architecture/JARVIS_BRAIN_MIGRATION_MAP_V1.md`

**Interfaces:**
- Produces: roadmap/migration-map truth aligned with code; no premature global Faz 11 completion.

- [ ] **Step 1: Update debt wording**
  Mark photo-follow-up relation debt as implemented in this open PR, not merged/complete until proof gates pass. Keep 17 orphan dispatch and notes debts open.

- [ ] **Step 2: Run focused Brain/photo tests**
  Include `tests.test_brain_gates`, `tests.test_brain_understanding`, `tests.test_brain_production_entry_photo_fence`, and new suite.

- [ ] **Step 3: Run acceptance compare**
  Run: `python -X utf8 scripts/brain_acceptance.py compare`
  Expected: no unaccepted changed/regression/error/missing and accepted fingerprint unchanged unless a reviewed scenario legitimately changes.

- [ ] **Step 4: Run full validation**
  Run: `python -X utf8 -m modules.validation`
  Expected: all groups successful in CI environment.

- [ ] **Step 5: Open Draft PR and collect exact-head evidence**
  Require Windows CI PASS and same exact SHA work-PC watcher PASS.

- [ ] **Step 6: Final review**
  Verify diff stays limited to photo relation ownership + tests + truth-sync. No merge without Hamdi's explicit authorization.
