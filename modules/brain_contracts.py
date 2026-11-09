"""Non-authoritative Brain contracts for Jarvis.

These immutable contracts carry observations and proposals only. They do not
represent permission, approval, execution, GoalState mutation, or completion.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Mapping


class RequestKind(str, Enum):
    CHAT = "CHAT"
    CAPABILITY = "CAPABILITY"
    CLARIFY = "CLARIFY"
    CONTEXT_CONTROL = "CONTEXT_CONTROL"


class ConversationRelation(str, Enum):
    NEW_REQUEST = "NEW_REQUEST"
    ANSWER_TO_PENDING = "ANSWER_TO_PENDING"
    CONTINUE_ACTIVE = "CONTINUE_ACTIVE"
    CORRECTION = "CORRECTION"
    TOPIC_CHANGE = "TOPIC_CHANGE"


class PendingOwner(str, Enum):
    """The single canonical pending slot an answer belongs to.

    Values are the existing state-protocol vocabulary so the owner the semantic layer
    selects is directly comparable with the legacy consumer fence. An answer can only
    belong to one owner; ambiguity is expressed as ``None`` plus a reason code."""

    WEATHER_LOCATION = "session.pending_weather_location"
    MESSAGE_TO = "session.pending_msg.to"
    MESSAGE_TEXT = "session.pending_msg.text"
    APP_CLARIFY = "session.pending_action.clarify"


class TemporalNeed(str, Enum):
    STATIC = "STATIC"
    CURRENT = "CURRENT"
    RECENT = "RECENT"
    HISTORICAL = "HISTORICAL"
    UNSURE = "UNSURE"


class ContextAction(str, Enum):
    KEEP = "KEEP"
    REPLACE_REFERENCE = "REPLACE_REFERENCE"
    DROP_ACTIVE_ARTIFACT = "DROP_ACTIVE_ARTIFACT"
    DROP_ACTIVE_TASK_REFERENCE = "DROP_ACTIVE_TASK_REFERENCE"
    DROP_TOPIC = "DROP_TOPIC"
    RESET_SESSION_CONTEXT = "RESET_SESSION_CONTEXT"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


_AUTHORITY_ARGUMENT_KEYS = frozenset({
    "allowed",
    "permission",
    "permission_granted",
    "approved",
    "authorized",
    "completed",
    "done",
    "effect_allowed",
    "execute",
})


def _require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _optional_text(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_text(name, value)


def _as_enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} geçersiz.") from None


def _reject_authority_argument_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key in _AUTHORITY_ARGUMENT_KEYS:
                raise ValueError(f"UnderstandingResult.arguments authority alanı taşıyamaz: {key}.")
            _reject_authority_argument_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_authority_argument_keys(item)


def _freeze_json(value: Any) -> Any:
    if callable(value):
        raise ValueError("Contract çalıştırılabilir callback/function taşıyamaz.")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Contract JSON uyumlu olmalı.")
        return value
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Contract JSON object anahtarları string olmalı.")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("Contract JSON uyumlu olmalı.")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if is_dataclass(value):
        return {item.name: _thaw_json(getattr(value, item.name)) for item in fields(value)}
    return value


class _JsonContract:
    def to_dict(self) -> dict[str, Any]:
        return {item.name: _thaw_json(getattr(self, item.name)) for item in fields(self)}


def _reference_tuple(name: str, value: Any, owner: str | None = None) -> tuple["ContextReference", ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} liste/tuple olmalı.")
    refs = tuple(value)
    for ref in refs:
        if not isinstance(ref, ContextReference):
            raise ValueError(f"{name} yalnız ContextReference taşımalı.")
        if owner is not None and ref.owner != owner:
            raise ValueError(f"{name} başka owner referansı taşıyamaz.")
    return refs


def _text_tuple(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} liste/tuple olmalı.")
    rows = tuple(value)
    for row in rows:
        _require_text(name, row)
    return rows


@dataclass(frozen=True)
class ContextReference(_JsonContract):
    id: str
    kind: str
    source: str
    owner: str
    provenance: Mapping[str, Any] = field(default_factory=dict)
    recency: TemporalNeed = TemporalNeed.UNSURE
    confidence: Confidence = Confidence.MEDIUM
    relevance: Confidence = Confidence.MEDIUM

    def __post_init__(self) -> None:
        _require_text("ContextReference.id", self.id)
        _require_text("ContextReference.kind", self.kind)
        _require_text("ContextReference.source", self.source)
        _require_text("ContextReference.owner", self.owner)
        object.__setattr__(self, "provenance", _freeze_json(self.provenance))
        object.__setattr__(self, "recency", _as_enum(TemporalNeed, self.recency, "recency"))
        object.__setattr__(self, "confidence", _as_enum(Confidence, self.confidence, "confidence"))
        object.__setattr__(self, "relevance", _as_enum(Confidence, self.relevance, "relevance"))


@dataclass(frozen=True)
class ActiveContext(_JsonContract):
    owner: str
    request_id: str
    topic: str | None = None
    active_goal_references: tuple[ContextReference, ...] = ()
    active_task_references: tuple[ContextReference, ...] = ()
    recent_references: tuple[ContextReference, ...] = ()
    active_artifacts: tuple[ContextReference, ...] = ()
    pending_references: tuple[ContextReference, ...] = ()
    memory_references: tuple[ContextReference, ...] = ()

    def __post_init__(self) -> None:
        _require_text("ActiveContext.owner", self.owner)
        _require_text("ActiveContext.request_id", self.request_id)
        _optional_text("ActiveContext.topic", self.topic)
        for name in (
            "active_goal_references", "active_task_references", "recent_references",
            "active_artifacts", "pending_references", "memory_references",
        ):
            object.__setattr__(self, name, _reference_tuple(name, getattr(self, name), self.owner))


@dataclass(frozen=True)
class EchoPreview(_JsonContract):
    text: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_text("EchoPreview.text", self.text)
        _optional_text("EchoPreview.reason_code", self.reason_code)


@dataclass(frozen=True)
class UnderstandingResult(_JsonContract):
    owner: str
    request_id: str
    request_kind: RequestKind
    capability_hint: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    # Model batch actions stay immutable evidence until each is independently Core-planned.
    actions: tuple[Mapping[str, Any], ...] = ()
    references: tuple[ContextReference, ...] = ()
    conversation_relation: ConversationRelation = ConversationRelation.NEW_REQUEST
    pending_owner: PendingOwner | None = None
    temporal_need: TemporalNeed = TemporalNeed.UNSURE
    context_actions: tuple[ContextAction, ...] = ()
    confidence: Confidence = Confidence.MEDIUM
    ambiguities: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    needs_input: bool = False
    preview: EchoPreview | None = None

    def __post_init__(self) -> None:
        _require_text("UnderstandingResult.owner", self.owner)
        _require_text("UnderstandingResult.request_id", self.request_id)
        object.__setattr__(self, "request_kind", _as_enum(RequestKind, self.request_kind, "request_kind"))
        object.__setattr__(self, "conversation_relation", _as_enum(ConversationRelation, self.conversation_relation, "conversation_relation"))
        if self.pending_owner is not None:
            object.__setattr__(self, "pending_owner", _as_enum(PendingOwner, self.pending_owner, "pending_owner"))
            if self.conversation_relation is not ConversationRelation.ANSWER_TO_PENDING:
                raise ValueError("pending_owner yalnız ANSWER_TO_PENDING ilişkisinde taşınabilir.")
        object.__setattr__(self, "temporal_need", _as_enum(TemporalNeed, self.temporal_need, "temporal_need"))
        object.__setattr__(self, "confidence", _as_enum(Confidence, self.confidence, "confidence"))
        _optional_text("UnderstandingResult.capability_hint", self.capability_hint)
        _reject_authority_argument_keys(self.arguments)
        object.__setattr__(self, "arguments", _freeze_json(self.arguments))
        if not isinstance(self.actions, (tuple, list)):
            raise ValueError("actions liste/tuple olmalı.")
        normalized_actions = []
        seen_action_ids = set()
        for index, action in enumerate(self.actions):
            if not isinstance(action, Mapping) or set(action) != {"action_id", "capability_id", "arguments", "reference_slots", "depends_on"}:
                raise ValueError("action şeması uyuşmuyor.")
            action_id = action.get("action_id")
            capability_id = action.get("capability_id")
            depends_on = action.get("depends_on")
            if (not isinstance(action_id, str) or action_id != f"a{index + 1}" or action_id in seen_action_ids
                    or not isinstance(capability_id, str) or not isinstance(depends_on, (tuple, list))
                    or any(not isinstance(item, str) or item not in seen_action_ids for item in depends_on)):
                raise ValueError("action bağımlılığı uyuşmuyor.")
            _reject_authority_argument_keys(action.get("arguments"))
            normalized_actions.append(_freeze_json(action))
            seen_action_ids.add(action_id)
        object.__setattr__(self, "actions", tuple(normalized_actions))
        object.__setattr__(self, "references", _reference_tuple("references", self.references, self.owner))
        if not isinstance(self.context_actions, (tuple, list)):
            raise ValueError("context_actions liste/tuple olmalı.")
        object.__setattr__(
            self,
            "context_actions",
            tuple(_as_enum(ContextAction, action, "context_action") for action in self.context_actions),
        )
        object.__setattr__(self, "ambiguities", _text_tuple("ambiguities", self.ambiguities))
        object.__setattr__(self, "assumptions", _text_tuple("assumptions", self.assumptions))
        object.__setattr__(self, "reason_codes", _text_tuple("reason_codes", self.reason_codes))
        if not isinstance(self.needs_input, bool):
            raise ValueError("needs_input bool olmalı.")
        if self.request_kind is RequestKind.CLARIFY and not self.needs_input:
            raise ValueError("CLARIFY sonucu kullanıcı girdisi istemeli.")
        if self.needs_input and not self.ambiguities and not self.references:
            raise ValueError("needs_input ambiguity veya candidate reference taşımalı.")
        if self.preview is not None and not isinstance(self.preview, EchoPreview):
            raise ValueError("preview EchoPreview olmalı.")


@dataclass(frozen=True)
class BrainFeedback(_JsonContract):
    owner: str
    request_id: str
    result_status: str
    candidates: tuple[ContextReference, ...] = ()
    evidence: tuple[ContextReference, ...] = ()
    reason_code: str | None = None
    recovery_class: str | None = None
    effect_state: str | None = None
    needs_input: bool = False
    ambiguities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("BrainFeedback.owner", self.owner)
        _require_text("BrainFeedback.request_id", self.request_id)
        _require_text("BrainFeedback.result_status", self.result_status)
        object.__setattr__(self, "candidates", _reference_tuple("candidates", self.candidates, self.owner))
        object.__setattr__(self, "evidence", _reference_tuple("evidence", self.evidence, self.owner))
        _optional_text("BrainFeedback.reason_code", self.reason_code)
        _optional_text("BrainFeedback.recovery_class", self.recovery_class)
        _optional_text("BrainFeedback.effect_state", self.effect_state)
        if not isinstance(self.needs_input, bool):
            raise ValueError("needs_input bool olmalı.")
        object.__setattr__(self, "ambiguities", _text_tuple("ambiguities", self.ambiguities))
