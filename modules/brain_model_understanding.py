"""Bounded, non-authoritative semantic refinement through the existing free-tier router.

The model may refine only typed fields. It cannot supply arguments, targets, references,
owners, approvals, or execution authority. Core revalidates every capability proposal.
"""
from __future__ import annotations

import json
import ntpath
import time
from dataclasses import dataclass
from typing import Any, Mapping

from modules.diagnostics import record_failure as _record_failure

from modules.brain_contracts import Confidence, ConversationRelation, RequestKind, TemporalNeed

_PAID = frozenset({"openai", "anthropic"})
_LOCAL = frozenset({"ollama"})


@dataclass(frozen=True)
class SemanticRefinement:
    request_kind: RequestKind
    conversation_relation: ConversationRelation
    temporal_need: TemporalNeed
    capability_hint: str | None
    confidence: Confidence
    arguments: Mapping[str, Any] | None = None
    references: tuple[Any, ...] = ()


def _decode(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > 4000:
        raise ValueError("Model proposal is not bounded text.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Model proposal must be a JSON object.")
    expected = {"request_kind", "conversation_relation", "temporal_need", "capability_hint", "confidence", "file_operation", "file_slots"}
    if set(value) != expected:
        raise ValueError("Model proposal schema mismatch.")
    return value


def refine(*, owner: str, text: str, current: Any, arguments: Mapping[str, Any],
           protected_relation: bool = False,
           file_operation_hint: str | None = None) -> SemanticRefinement | None:
    """Ask only an already eligible free cloud route; fail closed on every error.

    The model cannot invent arguments. A changed capability is accepted only if the
    existing Core allowlist validates the unchanged deterministic arguments.
    """
    if not owner or not isinstance(text, str) or not text.strip():
        return None
    try:
        from modules import llm, provider_privacy, requests_state, smart_router
        if llm.current_user() != owner:
            return None
        selected = llm.provider()
        # Explicit paid/local selections are not silently overridden or used by Brain.
        if selected in _PAID or selected in _LOCAL or llm.privacy.mode() == "yerel":
            return None
        route = provider_privacy.ROUTE_PRIVATE_GENERAL
        eligible = smart_router.selection(owner, "analysis", route=route).get("candidates", [])
        if not any(name in {"groq", "cloudflare"} for name in eligible):
            return None

        from modules.brain_core_map import CORE_INTENTS
        allowed_hints = sorted(CORE_INTENTS)
        file_refs = [ref for ref in current.references if getattr(ref, "kind", None) == "file"]
        current_ambiguities = tuple(getattr(current, "ambiguities", ()))
        resolving_file_ambiguity = bool(
            getattr(current, "needs_input", False)
            and current_ambiguities == ("multiple target references",)
            and current.capability_hint == "files.read"
            and file_operation_hint in {"summarize", "analyze", "locate"}
            and current.conversation_relation is ConversationRelation.NEW_REQUEST
            and current.pending_owner is None
            and not protected_relation
            and len(file_refs) >= 2
        )
        resolving_chat_ambiguity = bool(
            getattr(current, "needs_input", False)
            and current_ambiguities == ("multiple target references",)
            and current.capability_hint is None
            and current.conversation_relation is ConversationRelation.NEW_REQUEST
            and current.pending_owner is None
            and not protected_relation
        )
        file_slots = []
        slot_refs = []
        slot_labels: dict[str, tuple[str, str]] = {}
        for reference in file_refs:
            path_value = reference.provenance.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                continue
            name_value = reference.provenance.get("name")
            if not isinstance(name_value, str) or not name_value.strip():
                name_value = ntpath.basename(path_value)
            parent_parts = [part for part in ntpath.dirname(path_value).replace("/", "\\").split("\\") if part]
            folder_value = " / ".join(parent_parts[-2:])
            slot = f"file_{len(slot_refs)}"
            file_slots.append({
                "slot": slot,
                "name": name_value[:180],
                "folder": folder_value[:100],
            })
            slot_refs.append((slot, reference))
            slot_labels[slot] = (name_value.casefold().strip(), folder_value.casefold().strip())
        prompt = json.dumps({
            "utterance": text[:2000],
            "current": {
                "request_kind": current.request_kind.value,
                "conversation_relation": current.conversation_relation.value,
                "temporal_need": current.temporal_need.value,
                "capability_hint": current.capability_hint,
                "needs_input": bool(getattr(current, "needs_input", False)),
                "ambiguities": list(current_ambiguities),
                "file_operation_hint": file_operation_hint,
            },
            "allowed": {
                "request_kind": [
                    RequestKind.CHAT.value, RequestKind.CAPABILITY.value,
                    RequestKind.CLARIFY.value, RequestKind.CONTEXT_CONTROL.value,
                ],
                "conversation_relation": [item.value for item in ConversationRelation],
                "temporal_need": [item.value for item in TemporalNeed],
                "capability_hint": allowed_hints,
                "file_operation": ["open", "summarize", "analyze", "locate", "list", "compare"],
            },
            "file_candidates": file_slots,
        }, ensure_ascii=False)
        system = (
            "You are a semantic proposal component, not an agent. Return exactly one JSON object "
            "with keys request_kind, conversation_relation, temporal_need, capability_hint, confidence, "
            "file_operation, file_slots. file_slots may contain only supplied slot labels. You may propose "
            "files.read only with one valid file slot for summarize/analyze/locate, 2-10 slots for "
            "compare, or no slots for list. Do not output arguments, paths, filenames, recipients, "
            "references, approvals, permissions, or execution claims. For other capabilities keep the "
            "current capability and never invent arguments. If current.needs_input is true, preserve "
            "CLARIFY unless the only ambiguity is multiple target references and one supplied file "
            "candidate is clearly identified by the utterance using its name/folder. In that case, use "
            "exactly file_operation_hint and one slot. If candidates cannot be distinguished, return "
            "CLARIFY with no slots; never guess. For an ambiguous file target do not downgrade to CHAT. "
            "Core revalidates."
        )
        deadline = time.monotonic() + 12.0

        def send(provider: str) -> str:
            requests_state.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests_state.Cancelled("Brain model refinement budget expired.")
            return llm._send_provider(provider, prompt, system, remaining, None)

        with requests_state.budget(12):
            # Smart Router remains the only provider selector. This call narrows its
            # eligible pool to cloud providers and explicitly excludes local fallback.
            raw = smart_router.run(
                owner, prompt + "\\n" + system, send, route=route,
                exclude_providers={"ollama"},
            )
            requests_state.check()
        row = _decode(raw)
        proposed_kind = RequestKind(row["request_kind"])
        proposed_hint = row["capability_hint"]
        operation = row["file_operation"]
        slots = row["file_slots"]
        if not isinstance(slots, list) or any(not isinstance(slot, str) for slot in slots):
            return None
        proposed_arguments = None
        resolved_references: tuple[Any, ...] = ()
        if proposed_hint == "files.read":
            if operation not in {"open", "summarize", "analyze", "locate", "list", "compare"}:
                return None
            current_operation = current.arguments.get("operation")
            if current_operation is None and resolving_file_ambiguity:
                current_operation = file_operation_hint
            if current.capability_hint == "files.read" and current_operation != operation:
                return None
            by_slot = dict(slot_refs)
            if len(set(slots)) != len(slots) or any(slot not in by_slot for slot in slots):
                return None
            if operation == "list":
                if slots or current.capability_hint != "files.read":
                    return None
                proposed_arguments = {"original_text": text, "operation": "list"}
            elif operation == "compare":
                if not 2 <= len(slots) <= 10:
                    return None
                proposed_arguments = {
                    "original_text": text,
                    "operation": "compare",
                    "paths": [by_slot[slot].provenance.get("path") for slot in slots],
                }
            else:
                if len(slots) != 1:
                    return None
                proposed_arguments = {
                    "original_text": text,
                    "operation": operation,
                    "path": by_slot[slots[0]].provenance.get("path"),
                }
            if not all(isinstance(value, str) and value.strip() for value in (
                    proposed_arguments.get("path"),) if "path" in proposed_arguments):
                return None
            if "paths" in proposed_arguments and any(not isinstance(value, str) or not value.strip()
                                                       for value in proposed_arguments["paths"]):
                return None
            if current.capability_hint == "files.read":
                current_path = current.arguments.get("path")
                current_paths = current.arguments.get("paths")
                if current_path is not None and proposed_arguments.get("path") != current_path:
                    return None
                if current_paths is not None and proposed_arguments.get("paths") != list(current_paths):
                    return None
            if resolving_file_ambiguity:
                if operation != file_operation_hint or len(slots) != 1:
                    return None
                selected_slot = slots[0]
                selected_label = slot_labels.get(selected_slot)
                if selected_label is None or not selected_label[0]:
                    return None
                if sum(1 for label in slot_labels.values() if label == selected_label) != 1:
                    return None
                selected_reference = dict(slot_refs).get(selected_slot)
                if selected_reference is None or selected_reference.owner != owner:
                    return None
                resolved_references = (selected_reference,)
        elif operation is not None or slots:
            return None
        proposed = SemanticRefinement(
            request_kind=proposed_kind,
            conversation_relation=ConversationRelation(row["conversation_relation"]),
            temporal_need=TemporalNeed(row["temporal_need"]),
            capability_hint=proposed_hint,
            confidence=Confidence(row["confidence"]),
            arguments=proposed_arguments,
            references=resolved_references,
        )
        if proposed.request_kind in {RequestKind.CLARIFY, RequestKind.CONTEXT_CONTROL}:
            return None
        if proposed.request_kind not in {RequestKind.CHAT, RequestKind.CAPABILITY}:
            return None
        if bool(getattr(current, "needs_input", False)) and not (
            resolving_file_ambiguity or resolving_chat_ambiguity
        ):
            return None
        if resolving_file_ambiguity and not resolved_references:
            return None
        if resolving_chat_ambiguity and not (
            proposed.request_kind is RequestKind.CHAT
            and proposed.capability_hint is None
            and proposed.arguments is None
        ):
            return None
        if proposed.capability_hint is not None and proposed.capability_hint not in CORE_INTENTS:
            return None
        # A model may not rewrite an owner-bound pending answer, correction, topic change,
        # or active continuation established by the canonical deterministic evidence.
        if protected_relation and proposed.conversation_relation is not current.conversation_relation:
            return None
        if proposed.conversation_relation not in {current.conversation_relation, ConversationRelation.NEW_REQUEST}:
            return None
        # The model cannot upgrade a chat into an executable capability unless Core accepts
        # the unchanged, deterministic argument payload for that exact capability.
        if proposed.request_kind is RequestKind.CAPABILITY:
            if (proposed.confidence is Confidence.LOW and not resolving_file_ambiguity) or proposed.capability_hint is None:
                return None
            if current.capability_hint is not None and proposed.capability_hint != current.capability_hint:
                return None
            if current.capability_hint is None and not (
                proposed.capability_hint == "files.read"
                and current.request_kind in {RequestKind.CHAT, RequestKind.CAPABILITY}
                and any(getattr(reference, "kind", None) == "file" for reference in current.references)
            ):
                return None
            from modules.brain_core_map import core_plan
            candidate_arguments = proposed.arguments if proposed.arguments is not None else arguments
            if core_plan(proposed.capability_hint, candidate_arguments) is None:
                return None
        elif proposed.capability_hint is not None or proposed.arguments is not None:
            return None
        # Never upgrade confidence beyond the deterministic proposal.
        rank = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
        if rank[proposed.confidence] > rank[current.confidence]:
            if not resolving_file_ambiguity:
                return None
            # Resolving the exact target ambiguity can raise LOW only to conservative MEDIUM.
            proposed = SemanticRefinement(
                request_kind=proposed.request_kind,
                conversation_relation=proposed.conversation_relation,
                temporal_need=proposed.temporal_need,
                capability_hint=proposed.capability_hint,
                confidence=Confidence.MEDIUM,
                arguments=proposed.arguments,
                references=proposed.references,
            )
        return proposed
    except Exception as exc:
        _record_failure("modules/brain_model_understanding.py:refine")
        # User cancellation must propagate to the request boundary; all other optional-model
        # failures leave the deterministic proposal unchanged.
        from modules import requests_state
        if isinstance(exc, requests_state.Cancelled):
            raise
        return None
