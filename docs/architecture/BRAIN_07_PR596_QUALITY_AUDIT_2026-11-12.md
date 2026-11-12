# BRAIN-07 / PR #596 — adversarial acceptance audit (12 Nov 2026)

Scope: current typed `brain_entry.prepare → handoff → goal_resolver → canonical_goal_flow` read-only admission, the already-existing `task_queue.start` Scheduler, `canonical_scheduler_dispatch`, Core WorkerResult/CAS, and owner-pinned written result. Tracker #584 remains open. BRAIN-03 semantic authority and shared files are not owned by this change.

## Evidence rules

- **CODE PRESENT** means source and an explicit guard or test were inspected; it does **not** claim a passing run.
- **EXACT-HEAD PASS** can only follow actual GitHub Windows CI plus real Windows-PC watcher for the same commit; neither may be inferred from an older SHA.
- Worker `done` is not global Goal `done`; Core terminal CAS is not UI delivery; UI sink success is not a user-read receipt; `reserved` is not `delivered`.
- A synthetic/mock provider exercises program control but cannot establish live model semantic quality, real Windows microphone/audio playback or OS-wide exactly-once behavior.

## Adversarial matrix

| # | Fault or boundary | Observed source/test evidence | Limit and accountable follow-up |
|---|---|---|---|
| 1 | Duplicate typed request after publication | `canonical_goal_flow._existing_request` checks owner/request/text under existing per-job lock *before* `model_wait.ask`; explicit duplicate + invalid-second-plan tests | New same-ID attempts do not plan or invoke legacy; tested outcome needs exact-head CI |
| 2 | Concurrent initial duplicate | `_planning_once` uses a per-ID process-local mutex and distinct per-ID OS lock; new two-thread valid/valid, valid/invalid and invalid/valid tests, OS-lock process test | Unsupported first plan needs one-shot legacy receipt; never claim model-only serialization is enough; Windows lock contention may fail closed rather than wait forever |
| 3 | Late/duplicate worker callback | `canonical_scheduler_lane.revalidate_offer`, `canonical_scheduler_dispatch.execute_offer`, accepted WorkerResult CAS and existing `test_duplicate_wake_cannot_start_same_canonical_attempt` | External provider side effects cannot be undone; read-only manifest restriction remains essential |
| 4 | Lease expiry/deadline | `runtime_worker_result.CanonicalWorkerDeadline` and `require_scheduler_active`; `test_real_scheduler_worker_deadline_fences_late_core_cas_no_replay` | Expiry fences evidence/next action, not physical termination of a stuck provider; BRAIN-08 recovery/lifecycle |
| 5 | Scheduler stop | `task_queue.start` checks stop/deadline; existing `test_scheduler_stop_during_running_research_rejects_late_core_cas` | No claim that remote I/O is killed or process restart is exactly once; BRAIN-08 |
| 6 | Model/provider timeout | `model_wait.ask` bounded 60 s; errors propagate rather than `None` legacy fallback; new timeout-first/second-admission test | Provider thread can outlive caller; no global provider kill guarantee; BRAIN-08 |
| 7 | User cancellation | `requests_state.check` before first legacy claim and before canonical publication, existing canonical worker cancelled-result tests, new cancel-during-model regression | Cancellation/commit are not one atomic transaction; tiny race after check until publication remains; BRAIN-08 end-to-end cancellation fencing |
| 8 | Plan changed before execution | `goal_plan_gate.revalidate`, `canonical_scheduler_lane.revalidate_offer`, `canonical_plan_evidence.certify_projected_plan` and `test_node_from_old_plan_cannot_be_reoffered` | A new plan requires fresh proof; wider effectful plan migration outside #596 |
| 9 | Process crash | `canonical_restart_audit.inspect` classifies queued, started-unknown, accepted-unprojected and failed states; new legacy fallback receipt is durable | OS lock release does not prove an external effect did not happen; BRAIN-08 |
| 10 | Only one of two writes durable | First GoalState-with-plan then ExecutionRecord under control lock; missing pair blocks Scheduler and duplicate admission. Existing partial-publication and new concurrent crash test | Core terminal CAS then final ExecutionRecord can also crash; this terminal two-file recovery remains unproven and blocks a stronger durability claim; BRAIN-08 |
| 11 | Owner/profile identity changes | `canonical_profile` pins registered profile, `execution_record.load` checks owner, `read_completed_result` checks owner/Core terminal/proof | Cross-owner read denied; physical account changes outside supported owner namespace remain distinct |
| 12 | UI sink failure | `_complete_once` persists `reserved` and result text before fanout; exception leaves unknown delivery and never replays blindly | `delivered` means sink return, **not** user-read; BRAIN-10 UI acknowledgment |
| 13 | Goal done but user sees nothing | Exact `hedef sonucu <16-hex-ID>` command verifies Core terminal + each projected WorkerResult hash and returns durable response without fanout | Works when paired journal/result exists; Core-done-without-record gap still requires reviewed recovery; BRAIN-08 |
| 14 | Legacy fallback on duplicate request | Unsupported FIRST plan now claims a per-ID, digest-bound `.planning` receipt atomically **before** `goal_executor.run`; duplicate gets no-op, not a second UUID. New invalid-first/valid-second, receipt-corruption/write-failure and cross-process receipt tests | Receipt means *admitted*, not legacy success. Other, non-typed legacy entry paths are BRAIN-03 scope; they cannot be declared globally idempotent here |
| 15 | Foreground conversation during background work | Existing one Scheduler, per-owner bounded work, test `test_foreground_accepts_second_independent_goal_while_worker_is_running` and synthetic voice interleave in scheduler lane | Real speaker/microphone Full acceptance and single voice front-end belong to BRAIN-10; do not claim acoustic success |

## First admission race matrix (focused #596)

| First planner outcome | Competing same-ID attempt | Expected safe result | New/existing regression |
|---|---|---|---|
| Valid read-only | Valid read-only | One canonical job, one planner call, no legacy | `test_concurrent_valid_plans_admit_only_one_model_decision` |
| Valid read-only | Invalid/effectful | Second must not consume an invalid plan or invoke legacy | `test_concurrent_missing_request_cannot_escape_to_legacy_with_unsupported_second_plan` |
| Invalid/effectful | Valid read-only | One legacy admission receipt and first-only fallback; no canonical second job | `test_invalid_first_plan_has_durable_one_shot_legacy_fallback` |
| Model timeout | Valid read-only | No first effect/legacy, subsequent attempt may plan | `test_timeout_first_attempt_never_claims_legacy_or_stale_completion` |
| GoalState stored, journal fails | Any | No second plan/legacy; flagged incomplete pair | `test_concurrent_half_published_goal_does_not_fall_back_to_legacy` |
| Same ID, different text | Any | Identity collision error before alternate model/effect | `test_concurrent_same_request_id_different_text_is_rejected` |
| Cancellation during model | Delayed valid return | No job publication from cancelled request | `test_cancelled_model_cannot_publish_after_its_provider_returns` |
| Two processes with same ID | Same key | Cross-process OS planning exclusion; durable legacy receipt readable across restart | `test_cross_process_same_id_planning_guard_excludes_second_process`, `test_legacy_receipt_survives_a_separate_process_restart` |

## Ownership / release decision

- **#596 owner**: typed read-only canonical admission, already-existing Scheduler/Core proof, written owner result and the **first-admission** fallback-fence in `canonical_goal_flow` + narrow `goal_resolver` branch.
- **BRAIN-03**: broad natural-language understanding, old semantic/regex authority, old planner and non-typed legacy entry retirement. Do not modify `brain_entry.py`, `brain_understanding.py`, `brain_model_understanding.py`, `brain_core_map.py`, or `engine_loop.py` in this follow-up; #596 already touches `engine_loop.py` from its earlier scope and future edits must be coordinated.
- **BRAIN-08**: effectful action approvals, uncertain effect reconciliation, hard provider I/O lifetime, durable two-file terminal recovery, cancellation/lease lifecycle and safe operator recovery. The tiny first-admission marker is not a worker queue, GoalState or Scheduler.
- **BRAIN-10**: real voice-first foreground/background behavior, user-visible result inbox/acknowledgment and larger UI/response architecture. Large BRAIN-01–10 real-user campaign only after BRAIN-10; does not waive narrow #596 PC checks.
- **Release gate**: exact new HEAD full Windows CI and physical PC watcher must BOTH PASS. A real-model Full semantic run is separate from CI/mock tests. No automatic polling/merge after push; follow `docs/agents/pr-test-bekleme.md`.
