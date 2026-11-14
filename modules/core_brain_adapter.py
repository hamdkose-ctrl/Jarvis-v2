"""Core adapter for Brain proposals: validation, session lifecycle and dispatch.

Brain entry observes and proposes. This adapter applies existing Core/domain
protocols; it never reclassifies free text or introduces another state store.
"""
from __future__ import annotations
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.brain_entry import EntryResult

def _photo_lifecycle(runtime: Any, entry: EntryResult) -> None:
    """Düşme kuralının tek sahibi: fotoğrafa bağlı olmayan, kararı verilmiş turn pending'ı kapatır.

    Kural yüzeyde (`engine_commands`) yaşıyordu ve legacy handler'a ulaşan turlerde çalışıyordu;
    Fast/State lane'ları handler'ı dolaşınca hiç uygulanmaz oldu. Karar yine yalnız canonical
    relation/protocol gözleminden gelir — burada ham cümle hiçbir fotoğraf işlemi seçmez.
    İptal turn'ü fotoğrafın kendi sahibidir: mesajını bounded tüketici yazar, düşürülmez."""
    from modules.brain_entry import (
        PENDING_PHOTO_TTL, PHOTO_CANCEL_PROTOCOL, _record_failure, photo_followup_owned, relation_decided, time
    )
    try:
        if getattr(runtime._session(), "_in_multi", False):
            return
    except Exception:
        _record_failure("modules/brain_entry.py:photo_lifecycle_session")
        return
    photos = getattr(runtime, "_pending_photo", None)
    if not isinstance(photos, dict):
        return
    row = photos.get(entry.owner)
    if not isinstance(row, dict):
        return
    started = row.get("t")
    # Süre sınırı lifecycle gözlemidir; `_pending_photo_row` ile aynı saati okur.
    if not isinstance(started, (int, float)) or time.time() - started > PENDING_PHOTO_TTL:
        photos.pop(entry.owner, None)
        return
    if photo_followup_owned(entry):
        return
    if entry.state_gate.matched and entry.state_gate.protocol == PHOTO_CANCEL_PROTOCOL:
        return
    if relation_decided(entry):
        photos.pop(entry.owner, None)


def core_plan(entry: EntryResult) -> tuple[str, dict[str, object]] | None:
    """Core-validated intent for a mapped capability hint; None keeps the existing handler path."""
    from modules.brain_entry import (
        RequestKind, _canonical_photo_path, _pending_owns_turn, _translate_source_is_brains, brain_core_map, photo_followup_owned
    )
    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):
        return None
    semantic = entry.understanding
    if semantic is None or semantic.request_kind is not RequestKind.CAPABILITY:
        return None
    arguments = semantic.arguments
    if semantic.capability_hint == "development.manage":
        # Approval source is the immutable Core entry, never a model field.
        arguments = {**arguments, "original_text": entry.text}
    plan = brain_core_map.core_plan(semantic.capability_hint, arguments)
    if plan is not None and plan[0] == "document_export":
        artifacts = [ref for ref in entry.active_context.active_artifacts
                     if ref.owner == entry.owner and ref.kind == "artifact"
                     and ref.source == "session_state" and ref.id == "last_doc"]
        if len(artifacts) != 1:
            return None
        digest = artifacts[0].provenance.get("document_digest")
        if not isinstance(digest, str) or len(digest) != 64:
            return None
        plan = (plan[0], {"document_owner": entry.owner, "document_digest": digest})
    if plan is not None and plan[0] == "workbench_followup":
        references = [ref for ref in entry.active_context.active_artifacts
                      if ref.owner == entry.owner and ref.id == "last_workbench"
                      and ref.source == "workbench" and ref.kind == "artifact"]
        if len(references) != 1:
            return None
        digest = references[0].provenance.get("digest")
        if not isinstance(digest, str) or len(digest) != 64:
            return None
        plan = ("workbench_followup", {**plan[1], "expected_digest": digest})
    photo_plan = plan is not None and plan[0] == "photo_action"
    if photo_plan:
        selected, ambiguous = _canonical_photo_path(entry)
        if ambiguous or selected is None or plan[1].get("photo") != selected:
            return None
    # Slot presence is not relation authority: only a turn the canonical chain assigned to an
    # open interaction (exact state/answer/continuation) blocks the plan. The single exception is
    # a validated photo plan that consumes exactly the open pending photo it was built from.
    if _pending_owns_turn(entry):
        consumes_pending = (photo_plan and photo_followup_owned(entry)
                            and not semantic.ambiguities)
        if not consumes_pending:
            return None
    if plan is not None and plan[0] in {"notes_read", "notes_write"}:
        ident = plan[1].get("id")
        # A note effect/read may target only an id Brain resolved for THIS request, never an arbitrary string.
        if ident is not None and ident not in {ref.id for ref in semantic.references if ref.kind == "note"}:
            return None
        if plan[0] == "notes_write":
            # This digest is Core-owned and never provided by the model. Recheck
            # the persisted record at the exact effect boundary before writing.
            matches = [ref for ref in semantic.references
                       if ref.kind == "note" and ref.owner == entry.owner
                       and ref.id == ident]
            if len(matches) != 1:
                return None
            from modules import main_planner
            observed = {"id": matches[0].id, **{
                key: matches[0].provenance.get(key)
                for key in ("text", "title", "ts", "photo")
            }}
            digest = main_planner.note_snapshot_digest(observed)
            if digest is None:
                return None
            plan = ("notes_write", {**plan[1], "expected_note_digest": digest})
    if plan is not None and plan[0] == "file_action":
        allowed = {str(ref.provenance.get("path")) for ref in semantic.references
                   if ref.kind == "file" and isinstance(ref.provenance.get("path"), str)}
        path = plan[1].get("path")
        paths = plan[1].get("paths")
        if path is not None and path not in allowed:
            return None
        if paths is not None and (not isinstance(paths, (list, tuple)) or any(value not in allowed for value in paths)):
            return None
    if plan is not None and plan[0] == "file_mutate" and plan[1].get("operation") in {"rename", "move"}:
        allowed = {ref.provenance.get("path") for ref in semantic.references
                   if ref.owner == entry.owner and ref.kind == "file"}
        if plan[1].get("path") not in allowed:
            return None
    if plan is not None and plan[0] == "development_manage":
        allowed = {ref.provenance.get("path") for ref in semantic.references
                   if ref.owner == entry.owner and ref.kind == "file"}
        if any(path not in allowed for path in plan[1].get("reference_paths", ())):
            return None
    if plan is not None and plan[0] == "translate" and not _translate_source_is_brains(entry, plan[1]):
        return None
    return plan


def _drop_stale_clarify(runtime: Any, entry: EntryResult) -> None:
    """Core-owned: a request that bypasses the legacy handler supersedes an unanswered clarify question.

    When the handler runs, ``app_actions.continue_voice`` consumes or clears it itself."""
    from modules.brain_entry import (
        _is_clarify_pending, _record_failure
    )
    if any(_is_clarify_pending(ref) for ref in entry.active_context.pending_references):
        try:
            state = runtime._session()
            pending = getattr(state, "pending_action", None)
            if isinstance(pending, dict) and pending.get("stage") == "clarify":
                state.pending_action = None
        except Exception:
            _record_failure("modules/brain_entry.py:drop_stale_clarify")


def _batch_handoff(runtime: Any, entry: EntryResult, handler: Any, command: str):
    """Run each adopted action through the existing Core intent path, never raw text."""
    from modules.brain_entry import (
        _LAST_FEEDBACK, _correlated_job_id, _record_failure, feedback, handoff, replace
    )
    from modules.command_manager import awaiting_input
    if awaiting_input(runtime._session()):
        row = feedback(entry, result_status="needs_input", reason_code="CORE_AWAITING_INPUT",
                       core_ambiguities=("core pending: existing interaction",))
        _LAST_FEEDBACK.set(row)
        return ("Açık bir mesaj/onay/düzenleme akışı varken çok adımlı komutu başlatmadım. "
                "Önce bekleyen yanıtı tamamla veya iptal et.", row, None)
    semantic = entry.understanding
    actions = tuple(getattr(semantic, "actions", ())) if semantic is not None else ()
    outcomes: dict[str, str] = {}
    lines: list[str] = []
    from modules import requests_state
    for action in actions:
        action_id = str(action["action_id"])
        if any(outcomes.get(dep) != "succeeded" for dep in action["depends_on"]):
            outcomes[action_id] = "skipped_dependency"
            lines.append(f"{action_id}: önkoşul başarılı olmadığı için atlandı.")
            continue
        try:
            requests_state.check()
            # Re-enter the existing single-action Core handoff with typed fields only:
            # this preserves Core's own result status instead of classifying reply text.
            action_entry = replace(
                entry, batch_child=True,
                understanding=replace(
                    semantic, capability_hint=action["capability_id"],
                    arguments=action["arguments"], actions=(),
                ),
            )
            output, action_feedback, _ = handoff(runtime, action_entry, handler, command)
            lines.append(f"{action_id}: {output}")
            if action_feedback.result_status == "handled":
                # Routing acknowledgement is not domain success. Only explicit domain evidence
                # can unlock a dependent action; uninstrumented results remain unknown.
                ok = getattr(output, "ok", None)
                outcomes[action_id] = "succeeded" if ok is True else "failed" if ok is False else "unknown"
                continue
            outcomes[action_id] = action_feedback.result_status
            # Existing Core owns any pending/onay state; no sibling may overwrite it.
            if action_feedback.result_status == "needs_input":
                for later in actions:
                    later_id = str(later["action_id"])
                    if later_id not in outcomes:
                        outcomes[later_id] = "deferred_core_pending"
                break
        except requests_state.Cancelled:
            outcomes[action_id] = "cancelled"
            for later in actions:
                later_id = str(later["action_id"])
                if later_id not in outcomes:
                    outcomes[later_id] = "cancelled"
            raise
        except Exception:
            _record_failure("modules/brain_entry.py:batch_action")
            outcomes[action_id] = "failed"
            lines.append(f"{action_id}: yürütme başarısız oldu.")
    status = ("needs_input" if "needs_input" in outcomes.values() else
              "handled" if outcomes and all(value == "succeeded" for value in outcomes.values()) else "partial")
    if status == "partial":
        lines.append("İşlemlerin tamamı başarılı olarak doğrulanamadı; sonuç kısmi.")
    row = feedback(entry, result_status=status,
                   reason_code=("CORE_AWAITING_INPUT" if status == "needs_input" else
                                "CORE_BATCH_HANDOFF_RETURNED" if status == "handled" else "CORE_BATCH_PARTIAL"),
                   core_ambiguities=("core pending: batch action",) if status == "needs_input" else ())
    _LAST_FEEDBACK.set(row)
    return "\n".join(lines), row, _correlated_job_id(entry)


def handoff(runtime: Any, entry: EntryResult, handler: Any, command: str):
    """Hand the proposal to existing Core/domain code and correlate BrainFeedback."""
    from modules.brain_entry import (
        ConversationRelation, PHOTO_CAPABILITY, RequestKind, _LAST_FEEDBACK, _batch_handoff, _core_rejected_proposal, _correlated_job_id, _drop_stale_clarify, _explicit_owner_after_model_chat, _file_access_refusal, _is_explicit_owner_protocol, _lane_plan, _open_core_pending, _photo_lifecycle, _relation_supersedes_clarify, _runtime_owner, _use_existing_handler, bind, brain_core_map, brain_precedence, clarification, core_plan, feedback
    )
    if _runtime_owner(runtime) != entry.owner:
        raise ValueError("Core handoff owner eşleşmiyor.")
    semantic = entry.understanding
    # The last verified volume/brightness target belongs only to an adjacent
    # level-setting conversation. A different canonical turn (including chat,
    # web navigation, exact controls, model outage or clarification) closes
    # that context before it can leak into a later bare-number request.
    if not (entry.stage == "understanding" and semantic is not None
            and semantic.capability_hint == "pc.level.set"
            and "MODEL_DECIDED" in semantic.reason_codes):
        from modules import session_state
        session_reader = getattr(runtime, "_session", None)
        if callable(session_reader):
            session_state.clear_property(session_reader())
    if semantic is None or semantic.capability_hint != "notes.write":
        from modules import session_state
        session_reader = getattr(runtime, "_session", None)
        if callable(session_reader):
            # Reads/adds must publish their own successful result. Other turns
            # close the previous referent instead of letting it drift topics.
            session_state.clear_note(session_reader())
    if (entry.stage == "understanding" and semantic is not None
            and {"MODEL_UNAVAILABLE", "MODEL_PROPOSAL_REJECTED"}.intersection(semantic.reason_codes)):
        # State and Fast lanes have their own exact Core protocols. They never
        # depend on the general semantic model's availability.
        # Only explicit UI-path and exact user-registered shortcut protocols
        # survive a model outage. A synthetic non-reminder plan closes all
        # raw front gates (planner/camera/cascade/fuzzy macro) in precedence.
        exact = brain_precedence.claim(runtime, command, ("unsupported", {}))
        if exact is not None:
            row = feedback(entry, result_status="handled", reason_code="EXACT_PROTOCOL_HANDLED")
            _LAST_FEEDBACK.set(row)
            return exact[1], row, None
        # Independent exact PC/workflow/git/updater owner protocols must remain
        # operational without the semantic model. Do not admit any raw natural
        # language fallback; only a whole explicit protocol can enter the
        # existing bounded handler and its permission checks.
        if _is_explicit_owner_protocol(runtime, command):
            if not callable(handler):
                raise ValueError("Exact protocol handler callable olmalı.")
            with bind(entry):
                output = handler(command)
            if output is not None:
                row = feedback(entry, result_status="handled", reason_code="EXACT_PROTOCOL_HANDLED")
                _LAST_FEEDBACK.set(row)
                return output, row, None
        rejected = "MODEL_PROPOSAL_REJECTED" in semantic.reason_codes
        row = feedback(entry, result_status="failed", reason_code=(
            "BRAIN_MODEL_PROPOSAL_REJECTED" if rejected else "BRAIN_MODEL_UNAVAILABLE"))
        _LAST_FEEDBACK.set(row)
        if rejected:
            return ("İstenen hedefi veya işlem bilgilerini güvenli biçimde doğrulayamadım; "
                    "hiçbir işlem başlatmadım.", row, None)
        return ("Doğal dil isteğini doğrulayacak model şu anda kullanılamıyor; "
                "güvenlik için işlem başlatmadım.", row, None)
    question = clarification(entry)
    if question is not None:
        if entry.understanding is not None:
            brain_core_map.clarification_effect(runtime, entry.understanding.ambiguities, entry.understanding.arguments)
        return question, feedback(entry, result_status="needs_input", reason_code="BRAIN_CLARIFICATION_REQUIRED"), None
    if entry.understanding is not None and getattr(entry.understanding, "actions", ()):
        if not callable(handler):
            raise ValueError("Core handler callable olmalı.")
        return _batch_handoff(runtime, entry, handler, command)
    refusal = _file_access_refusal(entry)
    if refusal is not None:
        row = feedback(entry, result_status="failed", reason_code="FILE_TARGET_NOT_ACCESSIBLE")
        _LAST_FEEDBACK.set(row)
        return refusal, row, None
    plan = core_plan(entry)
    if (plan is None and entry.understanding is not None
            and entry.understanding.capability_hint == "documents.export"):
        message = "Kaydedilecek bir çıktı bulamadım. Hangi çıktıyı kaydetmemi istiyorsun?"
        row = feedback(entry, result_status="needs_input", reason_code="DOCUMENT_OUTPUT_UNAVAILABLE")
        _LAST_FEEDBACK.set(row)
        return message, row, None
    lane_plan = None if plan is not None else _lane_plan(runtime, entry)
    if entry.batch_child and plan is None:
        row = feedback(entry, result_status="failed", reason_code="CORE_PROPOSAL_REJECTED")
        _LAST_FEEDBACK.set(row)
        return "Bu işlemi güvenli biçimde doğrulayamadım; işlem başlatılmadı.", row, None
    if (plan is None and entry.understanding is not None
            and entry.understanding.capability_hint == PHOTO_CAPABILITY):
        # No validated Core photo plan means no photo effect, and no legacy raw-text fallback.
        message = "Bu fotoğraf isteğini güvenli biçimde doğrulayamadım; işlem başlatılmadı."
        row = feedback(entry, result_status="failed", reason_code="PHOTO_TARGET_NOT_VALIDATED")
        _LAST_FEEDBACK.set(row)
        return message, row, None
    if (plan is None and lane_plan is None
            and (_core_rejected_proposal(entry)
                 or (semantic is not None and "MODEL_DECIDED" in semantic.reason_codes
                     and semantic.request_kind is RequestKind.CAPABILITY))):
        # Core'un reddettiği tam tipli öneri ham cepheden ikinci kez yürütülemez: ne etki ne
        # sahte başarı. Eksik öneri (yalnız cümle metni) bu çite girmez, eski sahibinde kalır.
        message = "Bu isteği güvenli biçimde doğrulayamadım; işlem başlatılmadı."
        row = feedback(entry, result_status="failed", reason_code="CORE_PROPOSAL_REJECTED")
        _LAST_FEEDBACK.set(row)
        return message, row, None
    if not callable(handler):
        raise ValueError("Core handler callable olmalı.")
    _LAST_FEEDBACK.set(None)
    before = _open_core_pending(runtime)
    goal_resolution = None
    try:
        with bind(entry):
            # A model-accepted independent request supersedes an unanswered
            # reminder creation/conflict prompt. Without this fence, a later
            # unrelated "evet" can create an old event the user has left behind.
            # A true ANSWER_TO_PENDING still belongs to the existing State owner.
            if (entry.stage == "understanding" and semantic is not None
                    and "MODEL_DECIDED" in semantic.reason_codes
                    and semantic.conversation_relation in {
                        ConversationRelation.NEW_REQUEST, ConversationRelation.TOPIC_CHANGE
                    }
                    and semantic.capability_hint != "reminder.propose"):
                runtime._session().pending_event_title = None
            if plan is not None or not _use_existing_handler(entry) or _relation_supersedes_clarify(entry):
                _drop_stale_clarify(runtime, entry)
            _photo_lifecycle(runtime, entry)
            if entry.understanding is not None and entry.understanding.request_kind is RequestKind.GOAL_CONTROL:
                # BRAIN-05: hedef işleminin tek yürütme kapısı Goal Resolver'dır ve bu dal
                # claim/dispatch/handler zincirinden ÖNCE gelir. `brain_precedence.claim` yalnız bir
                # plan ile çalıştığı için legacy `_planner_command`'a hedef cümlesi hiç ulaşmaz;
                # handler'ın ham metin yorumu da aynı cümleye ikinci kez bakamaz (BRAIN-MIG-098).
                # Efekt yine yalnız mevcut `goal_executor` ilkellerindedir — ikinci bir depo yok.
                from modules import goal_resolver
                goal_resolution = goal_resolver.resolve(runtime, entry)
                output = goal_resolution.message
            else:
                claimed = brain_precedence.claim(runtime, command, plan) if plan is not None else None
                if claimed is not None:
                    output = claimed[1]
                elif plan is not None:
                    from modules.engine_intents import dispatch
                    output = dispatch(runtime, plan[0], dict(plan[1]), command, command.casefold())
                elif lane_plan is not None:
                    # Protokol cevapları tek sahibine gider: cümlenin kendisi hiçbir yerde yeniden sınıflandırılmaz.
                    from modules.engine_intents import dispatch
                    output = dispatch(runtime, lane_plan[0], dict(lane_plan[1]), command, command.casefold())
                elif _explicit_owner_after_model_chat(runtime, entry, command):
                    output = handler(command)
                elif _use_existing_handler(entry):
                    output = handler(command)
                elif entry.understanding is not None and entry.understanding.request_kind is RequestKind.CONTEXT_CONTROL:
                    output = "Tamam. Yeni isteğini mevcut business state'i değiştirmeden ayrı bağlamda ele alacağım."
                else:
                    from modules.engine_intents import dispatch
                    output = dispatch(runtime, "chat", {}, command, command.casefold())
    except BaseException as exc:
        from modules import failure_policy, requests_state
        cancelled = isinstance(exc, requests_state.Cancelled)
        structured = None if cancelled else failure_policy.structured_outcome(exc)
        _LAST_FEEDBACK.set(feedback(
            entry,
            result_status="cancelled" if cancelled else "failed",
            reason_code="CORE_CANCELLED" if cancelled else (
                structured["reason_code"] if structured else "CORE_HANDLER_FAILED"),
            recovery_class=structured["recovery_class"] if structured else None,
        ))
        raise
    opened = tuple(sorted(_open_core_pending(runtime) - before))
    if opened:
        result = feedback(entry, result_status="needs_input", reason_code="CORE_AWAITING_INPUT",
                          core_ambiguities=tuple(f"core pending: {field}" for field in opened))
    elif goal_resolution is not None:
        # Hedef turunun sonucu resolver'ın Core doğrulamasından dönen gözlemidir; generic
        # CORE_HANDOFF_RETURNED onun yerine geçmez (etki mi, ret mi, soru mu ayrımı kaybolur).
        result = feedback(entry, result_status=goal_resolution.result_status,
                          reason_code=goal_resolution.reason_code)
    elif getattr(output, "ok", None) is False:
        # A Core/domain ActionOutcome with ok=False is a failure, also for
        # single actions; the batch path already observes this same signal.
        result = feedback(entry, result_status="failed", reason_code="CORE_ACTION_FAILED")
    else:
        result = feedback(entry, result_status="handled", reason_code="CORE_HANDOFF_RETURNED")
    _LAST_FEEDBACK.set(result)
    # `create_goal` yeni kimliğini resolver'da taşımaz (henüz önerilmemiş bir kayıttı); onu mevcut
    # korelasyon taraması kendi yazdığı kayıttan bulur.
    job_id = (goal_resolution.job_id if goal_resolution is not None else None) or _correlated_job_id(entry)
    return output, result, job_id



def clarification_effect(runtime: Any, ambiguities: tuple[str, ...], arguments: Mapping[str, Any]) -> None:
    """Core-owned state change that makes the asked question answerable next turn."""
    from modules.brain_core_map import LEVEL_UNSPECIFIED, APP_TARGET_MISSING, _app_target_kind, _app_target_question
    if LEVEL_UNSPECIFIED in ambiguities:
        level = arguments.get("level")
        if isinstance(level, int) and not isinstance(level, bool):
            runtime._session().pending_level = max(0, min(100, level))
        return
    if APP_TARGET_MISSING in ambiguities:
        kind = _app_target_kind(arguments)
        question = _app_target_question(arguments)
        if kind is None or question is None:
            return
        # Yalnız bounded proposal yazılır: hedefsiz fiilin cevabi mevcut app aç/kapat sahibine döner.
        from modules import app_actions
        app_actions.ask_clarification(runtime._session(), str(arguments.get("original_text") or ""),
                                      question, runtime.profile, {"kind": kind})
