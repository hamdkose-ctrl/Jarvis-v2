# Brain semantic ownership audit — 2026-11-04

Read-only BRAIN-S1 inventory. Base: `748b372c0c20fb52edde24c60a2ceaeb653b4027`.

The canonical path is `engine_commands.handle` → `brain_entry.prepare/_semantic_pass` → `brain_candidates.build_candidates` → `brain_reference.resolve_references` → `brain_understanding.understand` → `brain_core_map` validation → existing Core intent. Exact state/fast gates remain ahead of semantic interpretation.

`UnderstandingResult` already validates enums, freezes JSON arguments, enforces owner-bound references and rejects authority-shaped keys. `brain_core_map` independently allowlists capabilities and validates arguments.

General semantic decisions still in `brain_understanding.py`: request kind/action-vs-chat (`_looks_like_capability`, `action_request`, `ends_with_action`); temporal need (`_temporal_need`); correction/topic change (`_is_correction`, `_is_topic_change`); pending-answer ownership (`_pending_answer_owners`, `_typed_clarify_answer`); active continuation/reference plurality; capability/domain selection (file, notes, weather, research, photo, app/device); domain argument extraction; bounded sequence grammar; photo continuation. These are interpretation candidates, not grounds to remove exact protocols, schema, domain syntax or safety checks.

Legacy mutation front door: `engine_tools._extra_commands` calls `file_ops.handle(command, owner)`; `file_ops.py` owns raw move/rename/create/undo grammar. `brain_core_map` has no typed move/rename/create/undo capability. No `brain-pr3c5` branch and no open PR were found; this cannot rule out an unpushed local worktree.

Concrete file_ops defect: `undo()` unlinks the owner ledger after attempting all entries, including entries skipped because a file is missing, original path is occupied, or an OSError occurs. Move/rename records contain only `[new, old]`, with no identity digest, unlike create records. Tests lack partial-ledger retention and move/rename replacement protection. Add RED tests for partial retry, missing/occupied paths, replacement identity, unchanged move/rename and owner isolation before changing behavior.

S2/S3 constraints: one bounded provider call in existing Brain entry; no duplicate model call during candidate enrichment; exact state/fast preserved; existing provider/Core policy for owner, verified free-tier, quota, privacy and egress; no silent paid fallback; timeout/cancel/provider/quota/malformed-response fail closed; minimum relevant context only; strict JSON into existing UnderstandingResult; reject unknown capability, authority keys, owner mismatch, stale or ungrounded candidate; Core revalidates all arguments and remains sole permission/effect authority.

Test gaps: `test_brain_understanding.py` currently prohibits provider calls and must be deliberately replaced with bounded-call, timeout/cancel, quota, no-paid-fallback, privacy, malformed-output, capability injection, owner mismatch and stale-reference tests. `test_file_ops.py` lacks ledger/identity regression coverage. The 465-case corpus needs 100+ unseen Turkish/multiturn cases for S5. No runtime tests are claimed by this read-only audit.

Order: S1 audit → PR3C-5 typed file mutation migration + undo hardening → S2/S3 bounded model + contract → S4 retire only audited general semantic gates → S5 100+ unseen cases and exact-SHA Windows CI/PC watcher. Brain remains open until all gates pass.
