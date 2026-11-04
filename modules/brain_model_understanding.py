"""Bounded, non-authoritative semantic refinement through the existing free-tier router.

The model may refine only typed fields. It cannot supply arguments, targets, references,
owners, approvals, or execution authority. Core revalidates every capability proposal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

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


def _decode(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > 4000:
        raise ValueError("Model proposal is not bounded text.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Model proposal must be a JSON object.")
    expected = {"request_kind", "conversation_relation", "temporal_need", "capability_hint", "confidence"}
    if set(value) != expected:
        raise ValueError("Model proposal schema mismatch.")
    return value


def refine(*, owner: str, text: str, current: Any, arguments: Mapping[str, Any],
           protected_relation: bool = False) -> SemanticRefinement | None:
    """Ask only an already eligible free cloud route; fail closed on every error.

    The model cannot invent arguments. A changed capability is accepted only if the
    existing Core allowlist validates the unchanged deterministic arguments.
    """
    if not owner or not isinstance(text, str) or not text.strip():
        return None
    try:
        from modules import llm, provider_privacy, requests_state, smart_router
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
        prompt = json.dumps({
            "utterance": text[:2000],
            "current": {
                "request_kind": current.request_kind.value,
                "conversation_relation": current.conversation_relation.value,
                "temporal_need": current.temporal_need.value,
                "capability_hint": current.capability_hint,
            },
            "allowed": {
                "request_kind": [item.value for item in RequestKind],
                "conversation_relation": [item.value for item in ConversationRelation],
                "temporal_need": [item.value for item in TemporalNeed],
                "capability_hint": allowed_hints,
            },
            "candidate_kinds": sorted({str(getattr(ref, "kind", "")) for ref in current.references}),
        }, ensure_ascii=False)
        system = (
            "You are a semantic proposal component, not an agent. Return exactly one JSON object "
            "with keys request_kind, conversation_relation, temporal_need, capability_hint, confidence. "
            "Use only supplied enum values and capability hints. Do not output arguments, paths, names, "
            "recipients, references, approvals, permissions, or execution claims. If uncertain, keep "
            "the current decision or choose CHAT/CLARIFY. The Core will independently validate."
        )
        def send(provider: str) -> str:
            return llm._send_provider(provider, prompt, system, 180, None)

        with requests_state.budget(12):
            # Smart Router remains the only provider selector. This call narrows its
            # eligible pool to cloud providers and explicitly excludes local fallback.
            raw = smart_router.run(
                owner, prompt + "\\n" + system, send, route=route,
                exclude_providers={"ollama"},
            )
            requests_state.check()
        row = _decode(raw)
        proposed = SemanticRefinement(
            request_kind=RequestKind(row["request_kind"]),
            conversation_relation=ConversationRelation(row["conversation_relation"]),
            temporal_need=TemporalNeed(row["temporal_need"]),
            capability_hint=row["capability_hint"],
            confidence=Confidence(row["confidence"]),
        )
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
            if proposed.capability_hint is None:
                return None
            from modules.brain_core_map import core_plan
            if core_plan(proposed.capability_hint, arguments) is None:
                return None
        elif proposed.capability_hint is not None:
            return None
        # Never upgrade confidence beyond the deterministic proposal.
        rank = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
        if rank[proposed.confidence] > rank[current.confidence]:
            return None
        return proposed
    except Exception as exc:
        # User cancellation must propagate to the request boundary; all other optional-model
        # failures leave the deterministic proposal unchanged.
        try:
            from modules import requests_state
            if isinstance(exc, requests_state.Cancelled):
                raise
        except ImportError:
            pass
        return None
