"""Birincil anlamlandırma zarfı: kararı model üretir, yetkiyi yalnız Core verir.

Her serbest turda tek bir bounded çağrı ``brain-understanding.v2`` zarfını döndürür. Zarf
operation, eylem listesi, hedef kimlik yuvaları, hedef kartı, netleştirme, güven, ilişki ve
gereklilik alanlarını taşır. Model hiçbir gerçek yol, hesap, jeton, kimlik bilgisi veya onay
kimliği yazamaz ve yalnız kendisine sunulan yuva adlarını seçer. Kullanıcının kendi cümlesinden
doğması gereken alanlar (`_USER_OWNED_ARGUMENT_SLOTS`) modelin doldurabilir, ama her dolu alan
cümleden birebir alıntılanmış bir dayanakla (`argument_sources`) gelmek zorundadır. Core her
alanı kendi doğrulayıcısından geçirir; izin ve etki yetkisi yine yalnız Core'a aittir.
"""
from __future__ import annotations

import json
import ntpath
import re
import time
from dataclasses import dataclass
from contextvars import ContextVar
from typing import Any, Mapping

from modules.diagnostics import record_failure as _record_failure

from modules.brain_contracts import (
    Confidence, ConversationRelation, GOAL_CARD_KEYS, GOAL_CARD_KINDS, GOAL_CARD_TITLE_MAX,
    GoalOperation, RequestKind, TemporalNeed,
    _freeze_json, _reject_authority_argument_keys,
)

_PAID = frozenset({"openai", "anthropic"})
_LOCAL = frozenset({"ollama"})

SCHEMA_VERSION = "brain-understanding.v2"
MAX_ACTIONS = 5
MAX_TARGET_GOALS = 8
_GOAL_TEXT_MAX = GOAL_CARD_TITLE_MAX
_RESPONSE_MAX_TOKENS = 2048
# Brain'in ortak süre politikası (sn): üretim ve ölçüm aynı sınırı kullanır, daha kısa bir dış
# bütçe varsa requests_state.budget onu korur (iç içe bütçe en sıkı olanı seçer).
_MODEL_BUDGET_SECONDS = 30.0

OPERATIONS = frozenset({
    "chat", "direct_action", "action_batch", "create_goal", "continue_goal", "revise_goal",
    "add_task", "pause_goal", "resume_goal", "cancel_goal", "prioritize_goal", "clarify",
})
# Kapalı hedef işlemi sözlüğü tek yerden (brain_contracts.GoalOperation) gelir: zarf bu adları
# doğrular, taşıyıcı aynı enum'ı taşır, yürütücü (goal_resolver) aynı enum'ı Core lifecycle'ına
# eşler. Üçü ayrıştığında ölü bir dal doğar.
GOAL_OPERATIONS = frozenset(operation.value for operation in GoalOperation)
REQUEST_KIND_BY_OPERATION = {
    "chat": RequestKind.CHAT,
    "direct_action": RequestKind.CAPABILITY,
    "clarify": RequestKind.CLARIFY,
    "action_batch": RequestKind.CAPABILITY,
    **{operation.value: RequestKind.GOAL_CONTROL for operation in GoalOperation},
}

_proposal_diagnostic = ContextVar('brain_proposal_diagnostic', default=None)


def proposal_diagnostic(*, clear: bool = False) -> dict[str, Any]:
    """Per-call protocol/rejection codes only; no text, arguments or owner data."""
    if clear:
        _proposal_diagnostic.set(None)
    return dict(_proposal_diagnostic.get() or {})


def _reject(code: str):
    _proposal_diagnostic.set({**proposal_diagnostic(), 'status':'rejected', 'reason_code':code})
    return None

ENVELOPE_KEYS = frozenset({
    "schema_version", "operation", "conversation_relation", "temporal_need",
    "target_goal_ids", "goal", "actions", "clarification", "confidence",
})
ACTION_KEYS = frozenset({"action_id", "capability_id", "arguments", "reference_slots",
                         "depends_on", "argument_sources"})
CLARIFICATION_KEYS = frozenset({"required", "question", "reason_code"})
# Hedef kartının kapalı biçimi sözleşmede yaşar (brain_contracts); zarf onu burada kullanır.
_GOAL_KEYS = GOAL_CARD_KEYS
_GOAL_CARD_KINDS = GOAL_CARD_KINDS

# Model hedef kimliği üretemez: Core'un kendi authority alanı yasağına ek olarak zarf
# argümanlarında bu adlar geçtiği anda önerinin tamamı reddedilir. `photo` da bir yol alanıdır:
# photo turunda modelin uydurduğu yol, canonical artifact eşitliği çitinde tüm isteği
# PHOTO_TARGET_NOT_VALIDATED'a düşürürdü; bu yüzden öneri burada tümüyle reddedilir.
_MODEL_DENIED_ARGUMENT_KEYS = frozenset({
    "path", "paths", "photo", "token", "credential", "approval", "approval_id",
    "account", "account_id",
})

# BRAIN-03 dilim 2 (§4): `recipient`/`body` artık yasak anahtar değil, modelin doldurabildiği
# tipli yuvalardır. Yetki yasağının yerini DAYANAK denetimi aldı: model bir kullanıcı-sahibi
# alanı dolduruyorsa o alanı kullanıcının kendi cümlesinden birebir alıntılamak zorundadır.
# Bu tablo bir kelime listesi değildir — hangi ALANLARIN kullanıcının cümlesinden doğması
# gerektiğinin kapalı sözleşmesidir; değerlerin doğru olup olmadığına yine Core biçim hükmeder.
_USER_OWNED_ARGUMENT_SLOTS = {
    "message.send": frozenset({"recipient", "body"}),
    "contacts.manage": frozenset({"name", "phone"}),
    "user.manage": frozenset({"name", "old", "text"}),
    "macro.teach": frozenset({"trigger"}),
    "macro.manage": frozenset({"trigger"}),
    "learning.manage": frozenset({"text", "old", "index"}),
}

# Kullanıcı-sahibi alanlardan hangileri SAYIDIR. Bu bir doğal dil listesi değildir; hangi
# yuvanın rakam dizisi olarak karşılaştırılacağının kapalı sözleşmesidir (telefon). Metin
# alanları kelime dizisiyle, sayısal alanlar rakam dizisinin TAMAMIyla doğrulanır.
_GROUNDING_NUMERIC_FIELDS = frozenset({"phone", "index"})

# Kalıcı kullanıcı tercihi kullanıcının KENDİ cümlesinden doğar; modelin o cümlede olmayan bir
# yazma/silme yeteneği önermesi bu zarfta yetenek düzeyinde reddedilir. Core yalnız BİÇİM
# hükmeder (anlam listesi tutsa ikinci semantic authority olurdu), bu yüzden "çok sıcak" gibi
# şeklen geçerli bir değeri ayırt edemez — ölçüldü: `core_plan("weather.city.set",
# {"location": "çok sıcak"})` `("city_set", {"location": "Çok Sıcak"})` verir.
# BRAIN-03 dilim 2: `message.send` ve `contacts.manage` bu kümeden ÇIKTI — onlar modelin
# önerebilir kararlarıdır; uydurma alan tehlikesi artık dayanak denetimiyle kapatılır. Küme
# kapalı kalır: yeni bir ad eklemek açık bir karardır (`architecture_guard` ARCH-008 ayrıca
# yüzeyde yeniden belirmesini blocker sayar).
_MODEL_DENIED_CAPABILITIES = frozenset({"weather.city.set", "weather.city.reset"})

_FILE_OPERATIONS = ("open", "summarize", "analyze", "locate", "list", "compare")
_REASON_CODE = re.compile(r"^[A-Z0-9_]{1,64}$")
_CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


@dataclass(frozen=True)
class ProposedAction:
    action_id: str
    capability_id: str
    arguments: Mapping[str, Any]
    reference_slots: tuple[str, ...]
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class UnderstandingProposal:
    operation: str
    conversation_relation: ConversationRelation
    temporal_need: TemporalNeed
    confidence: Confidence
    actions: tuple[ProposedAction, ...] = ()
    target_goal_ids: tuple[str, ...] = ()
    goal: Mapping[str, Any] | None = None
    clarification_required: bool = False
    clarification_reason_code: str | None = None
    clarification_question: str | None = None
    references: tuple[Any, ...] = ()


def _decode(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > 6000:
        _reject('ENVELOPE_TEXT_LIMIT')
        raise ValueError("Model zarfı sınırlandırılmış metin değil.")
    try:
        value = json.loads(raw)
    except ValueError:
        _reject('ENVELOPE_JSON_INVALID')
        raise
    if not isinstance(value, dict):
        _reject('ENVELOPE_NOT_OBJECT')
        raise ValueError("Model zarfı JSON nesnesi olmalı.")
    if set(value) != set(ENVELOPE_KEYS):
        _reject('ENVELOPE_FIELDS_INVALID')
        raise ValueError("Model zarfı şeması uyuşmuyor.")
    if value["schema_version"] != SCHEMA_VERSION:
        _reject('ENVELOPE_VERSION_INVALID')
        raise ValueError("Model zarfı sürümü uyuşmuyor.")
    return value


def _response_schema(capabilities: list[str]) -> dict[str, Any]:
    """Expose the wire contract, without supplying an intent or an expected answer."""
    strings = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object", "additionalProperties": False,
        "required": sorted(ENVELOPE_KEYS),
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "operation": {"enum": sorted(OPERATIONS)},
            "conversation_relation": {"enum": [v.value for v in ConversationRelation]},
            "temporal_need": {"enum": [v.value for v in TemporalNeed]},
            "confidence": {"enum": [v.value for v in Confidence]},
            "target_goal_ids": strings,
            "goal": {"anyOf": [{"type": "null"}, {
                "type": "object", "additionalProperties": False,
                "required": sorted(_GOAL_KEYS), "properties": {
                    "kind": {"enum": sorted(_GOAL_CARD_KINDS)},
                    "title": {"type": "string", "maxLength": _GOAL_TEXT_MAX}}}]},
            "actions": {"type": "array", "maxItems": MAX_ACTIONS, "items": {
                "type": "object", "additionalProperties": False,
                "required": sorted(ACTION_KEYS), "properties": {
                    "action_id": {"type": "string"},
                    "capability_id": {"enum": capabilities},
                    "arguments": {"type": "object"},
                    "reference_slots": strings, "depends_on": strings,
                    "argument_sources": {"type": ["object", "null"]}}}},
            "clarification": {"type": "object", "additionalProperties": False,
                "required": sorted(CLARIFICATION_KEYS), "properties": {
                    "required": {"type": "boolean"},
                    "question": {"type": ["string", "null"]},
                    "reason_code": {"anyOf": [{"type":"null"},
                        {"type":"string", "pattern":_REASON_CODE.pattern}]}}},
        },
    }


def _deep_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                keys.add(key)
            keys |= _deep_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys |= _deep_keys(item)
    return keys


def _text_list(name: str, value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list) or any(not isinstance(row, str) or not row for row in value):
        return None
    rows = tuple(value)
    if len(set(rows)) != len(rows):
        return None
    return rows


def _goal_payload(row: Any) -> Mapping[str, Any] | None:
    if not isinstance(row, Mapping) or set(row) - set(_GOAL_KEYS):
        return None
    if row.get("kind") not in _GOAL_CARD_KINDS:
        return None
    title = row.get("title")
    if not isinstance(title, str) or "\x00" in title or not 0 < len(title.strip()) <= _GOAL_TEXT_MAX:
        return None
    return {"kind": row["kind"], "title": title.strip()}


def _argument_shape(capability_id: str) -> dict[str, Any]:
    """Modelin bu yetenek için doldurabileceği alanların biçimi; değer kümesini Core doğrular."""
    from modules.brain_core_map import CORE_INTENTS
    if capability_id not in CORE_INTENTS:
        return {}
    if capability_id in {"documents.export", "system.diagnose"}:
        return {"arguments": {}, "target": "current.current_output"
                if capability_id == "documents.export" else "read-only system checks"}
    if capability_id == "windows.settings.open":
        from modules.system_control import WINDOWS_SETTINGS_PAGES
        return {"page": sorted(WINDOWS_SETTINGS_PAGES)}
    if capability_id == "jarvis.selfctl":
        from modules.selfctl import PAGES
        return {"action": {
            "kind": ["navigate", "restart", "open_data", "setting_read", "setting", "ui"],
            "navigate.page": sorted(PAGES),
            "open_data.target": ["data", "log"],
            "setting_read.key": ["wake_sensitivity", "response_speed", "idle_seconds"],
            "setting": {
                "wake_sensitivity": [1, 2, 3, 4, 5, "increase", "decrease"],
                "response_speed": ["fast", "balanced", "patient"],
                "wake_beep": [True, False], "learn_from_chat": [True, False],
                "live_mode": [True, False], "widget": [True, False],
                "window_mode": ["full", "window"], "idle_seconds": "integer 15..600",
            },
            "ui": {"hologram_tone": ["blue", "turquoise", "yellow"],
                   "hologram_background": ["lava", "mountains"],
                   "replay": [True], "home_animation": [True, False]},
        }}
    if capability_id == "finance.read":
        from modules import finance
        return {
            "kind": ["rate", "asset", "stock"],
            "rate": {
                "source": sorted(finance.CURRENCY_CODES),
                "target": sorted(finance.CURRENCY_CODES),
                "codes": sorted(finance.CURRENCY_CODES),
                "amount": "optional positive decimal string",
            },
            "asset": {
                "asset": sorted(finance.FINANCE_ASSETS),
                "target": sorted(finance.CURRENCY_CODES),
                "gold_kind": sorted(finance.GOLD_KINDS),
                "amount": "optional positive decimal string",
            },
            "stock": {
                "stock": sorted(finance.STOCK_CODES),
                "amount": "optional positive decimal string",
            },
        }
    if capability_id == "user.manage":
        return {"operation": ["rename", "delete", "create", "list", "identify", "switch",
                                "goals_list", "goals_clear", "goal_add", "fact_add"],
                "name": "quoted user name when needed", "old": "quoted existing user name when needed",
                "text": "quoted goal or fact when needed", "argument_sources": ["name", "old", "text"]}
    if capability_id == "macro.teach":
        return {"trigger": "quoted shortcut phrase", "actions": ["verbatim executable steps from the utterance"],
                "argument_sources": ["trigger"]}
    if capability_id == "macro.manage":
        return {"operation": ["list", "delete"], "trigger": "quoted shortcut phrase for delete",
                "argument_sources": ["trigger"]}
    if capability_id == "learning.manage":
        return {"operation": sorted(__import__("modules.brain_core_map", fromlist=["_LEARNING_OPERATIONS"])._LEARNING_OPERATIONS),
                "text": "quoted user-provided text for addition or editing",
                "old": "complete quoted old fact for edit/forget",
                "index": "user-spoken 1-based index for a single pending fact or rule deletion",
                "argument_sources": ["text", "old", "index"]}
    owned = _USER_OWNED_ARGUMENT_SLOTS.get(capability_id)
    if owned:
        return {"freeform": True, "argument_sources": sorted(owned)}
    validator = CORE_INTENTS[capability_id][1]
    if validator.__name__ in {"_audio_args", "_media_args", "_window_list_args", "_window_op_args"}:
        return {"nested": {"action": "kapalı eylem kümesi"}}
    return {"freeform": True}


# Yetenek amaçlarının tek sahibi: model hangi işlemin hangi nesneye uygulandığını kelimelerden
# değil bu sözleşmeden ayırsın. Bu bir kelime/regex havuzu değil, capability id -> amaç/önkoşul
# tanımıdır; biçim ve yetki hükmü yine yalnız Core'un doğrulayıcısındadır.
_CAPABILITY_PURPOSES = {
    "windows.settings.open": (
        "opens a supported Windows Settings page with a closed ms-settings identifier",
        "Core verifies page before Windows receives it; not a Jarvis page or arbitrary URL"),
    "jarvis.selfctl": (
        "opens a Jarvis page, reads or changes an allowed setting, adjusts UI or restarts",
        "choose a valid typed kind, key and value from argument_schema; Core checks before effect"),

    "learning.manage": ("manages approved facts, numbered pending facts, and rules",
        "Core rejects an ALL scope from model proposals; exact State Gate alone authorizes bulk changes"),
    "git.publish": ("publishes local changes as a GitHub PR only on an exact admin command",
        "the original full command must satisfy the git_publish protocol"),
    "system.update": ("checks or installs an update only on an exact updater command",
        "the updater checks the original full command before any effect"),
    "user.manage": ("changes, selects, lists or records data in the current user's own profile", "Core validates a closed operation and bounded supplied fields"),
    "macro.teach": ("stores a user-requested named shortcut with its proposed steps", "Core validates a bounded trigger and non-empty steps; it does not infer an operation from raw text"),
    "macro.manage": ("lists or deletes a saved shortcut for the current user", "Core validates the closed operation and a bounded trigger for deletion"),
    "documents.export": (
        "keeps the result this conversation already produced as a document the user can open later",
        "requires current.current_output.available true; Core alone binds the document, its path and format",
    ),
    "notes.write": (
        "changes or deletes one note that already exists",
        "targets an existing note; it never stores the conversation's current result",
    ),
    "files.mutate": (
        "renames or moves a file that already exists on disk, or undoes a previous file action",
        "targets an existing file; it never creates a document from the conversation's current result",
    ),
    "files.read": (
        "opens, summarizes, analyzes, locates, lists or compares files",
        "targets only the supplied file_candidates slots; Core resolves the real path",
    ),
    "system.diagnose": (
        "runs Jarvis's own health checks and reports which parts are failing",
        "performs no repair, no setting change and no write, so a request that forbids repairing "
        "still asks for this check",
    ),
}


def _supplied_schema(capability_id: str) -> dict[str, Any]:
    """Biçim sözleşmesine yeteneğin amaç/önkoşul tanimini da ekler; değer kümesini Core doğrular."""
    shape = _argument_shape(capability_id)
    purpose = _CAPABILITY_PURPOSES.get(capability_id)
    if purpose is None or not shape:
        return shape
    return {**shape, "purpose": purpose[0], "precondition": purpose[1]}


# Core'un bu turda bağlayabildiği tek tanınmış oturum çıktısı; başka bir slot çıktı değildir.
_KNOWN_OUTPUT_SLOTS = ("last_doc",)


def _current_output(session_artifacts: Any) -> dict[str, Any]:
    """Oturum çıktısının var/yok hükmü: yalnız tanınmış last_doc kaydı, tek ve owner-bound.

    Yalnız slot/etiket görünür; belge içeriği veya parmak izi modele gitmez. Hüküm yalnız
    üretilmiş oturum çıktısını anlatır: dosya adaylarının var/yokluğu ayrı bildirilir, bilinmeyen
    bir slot çıktı sayılmaz ve tek başına hedef uydurulmaz."""
    rows = [row for row in session_artifacts if isinstance(row, Mapping)]
    outputs = [row for row in rows if row.get("slot") in _KNOWN_OUTPUT_SLOTS]
    labels = [str(row.get("label")) for row in outputs
              if isinstance(row.get("label"), str) and row.get("label")]
    available = len(rows) == 1 and len(outputs) == 1
    return {
        "available": available,
        "slot": _KNOWN_OUTPUT_SLOTS[0] if available else None,
        "label": labels[0] if available and labels else None,
        "meaning": ("this is the result this conversation produced and Core can save; a request to "
                    "keep, save or export refers to it, and an explicit candidate the user chose from "
                    "file_candidates or reference_slots is judged by that capability's own target "
                    "contract rather than turning into a question; clarify only when the target "
                    "genuinely cannot be decided"
                    if available else
                    "this conversation has no produced result for Core to save, export or attach "
                    "yet; this says nothing about file_candidates, which still describe the files "
                    "the user named"),
    }


_FOLDER_SIGNAL_ALIASES = {
    "downloads": ("downloads", "download", "indirilenler", "indirilen"),
    "documents": ("documents", "document", "belgeler", "belge"),
    "desktop": ("desktop", "masaüstü", "masaustu"),
    "pictures": ("pictures", "picture", "resimler", "resim"),
    "videos": ("videos", "video", "videolar"),
    "music": ("music", "müzikler", "muzikler"),
}


def _normal_signal(value: str) -> str:
    return " ".join(value.replace("İ", "i").replace("I", "ı").casefold().strip().split())


def _text_mentions_label(text: str, label: str) -> bool:
    signal = _normal_signal(label)
    if not signal:
        return False
    return re.search(rf"(?<!\w){re.escape(signal)}[\w]*", text) is not None


def _file_name_signals(reference: Any) -> tuple[str, ...]:
    path_value = reference.provenance.get("path")
    name_value = reference.provenance.get("name")
    basename = ntpath.basename(name_value if isinstance(name_value, str) and name_value.strip()
                                else path_value if isinstance(path_value, str) else "")
    stem = ntpath.splitext(basename)[0]
    return tuple(dict.fromkeys(signal for signal in (basename, stem) if signal))


def _file_folder_signals(reference: Any) -> tuple[str, ...]:
    path_value = reference.provenance.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        return ()
    parent_parts = [
        part for part in re.split(r"[\\/]+", ntpath.dirname(path_value)) if part
    ][-2:]
    signals: list[str] = []
    for part in parent_parts:
        signals.append(part)
        signals.extend(_FOLDER_SIGNAL_ALIASES.get(_normal_signal(part), ()))
    return tuple(dict.fromkeys(signals))


def _selected_file_candidate_is_grounded(
    text: str, selected: Any, candidates: list[Any],
) -> bool:
    """Require the spoken filename or folder to identify this candidate independently of the model."""
    normalized = _normal_signal(text)
    name_matches = [
        candidate for candidate in candidates
        if any(_text_mentions_label(normalized, signal) for signal in _file_name_signals(candidate))
    ]
    folder_matches = [
        candidate for candidate in candidates
        if any(_text_mentions_label(normalized, signal) for signal in _file_folder_signals(candidate))
    ]
    if len(name_matches) == 1:
        return name_matches[0] is selected and (not folder_matches or selected in folder_matches)
    if len(folder_matches) == 1:
        return folder_matches[0] is selected
    return False


def _file_slots(current: Any) -> tuple[list[dict[str, str]], list[tuple[str, Any]], dict[str, tuple[str, str]]]:
    slot_rows: list[dict[str, str]] = []
    slot_refs: list[tuple[str, Any]] = []
    slot_labels: dict[str, tuple[str, str]] = {}
    for reference in current.references:
        if getattr(reference, "kind", None) != "file":
            continue
        path_value = reference.provenance.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        name_value = reference.provenance.get("name")
        if not isinstance(name_value, str) or not name_value.strip():
            name_value = ntpath.basename(path_value)
        parent_parts = [part for part in ntpath.dirname(path_value).replace("/", "\\").split("\\") if part]
        folder_value = " / ".join(parent_parts[-2:])
        slot = f"file_{len(slot_refs)}"
        slot_rows.append({"slot": slot, "name": name_value[:180], "folder": folder_value[:100]})
        slot_refs.append((slot, reference))
        slot_labels[slot] = (name_value.casefold().strip(), folder_value.casefold().strip())
    return slot_rows, slot_refs, slot_labels


def _offered_goal_ids(candidates: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(reference.id) for reference in candidates
        if getattr(reference, "kind", None) in _GOAL_CARD_KINDS
    ))


def _offered_goal_cards(candidates: Any) -> list[dict[str, Any]]:
    """Modele sunulan hedef kartları: kullanıcıya ait kimlik + sınırlı bağlam, başka bir şey değil.

    Kartın her alanı referansın kendi provenance'ından gelir (Core'un gözlemi); durum geçişi,
    izin veya yürütme bilgisi taşımaz. Sınır zarftaki hedef kimliği sınırıyla aynı sayıdır.
    Model bir kartı `target_goal_ids` içinde kullanmadan önce görür. Hedef işlemi olmayan bir
    önerinin bu küme dışına çıkması bütün öneriyi düşürür (`GOAL_TARGET_NOT_OFFERED`); hedef
    işleminde denetimin durağı yürütücüdür — orada uydurma kimlik efekt değil soru üretir."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reference in candidates:
        if getattr(reference, "kind", None) not in _GOAL_CARD_KINDS:
            continue
        ident = str(reference.id)
        if ident in seen:
            continue
        seen.add(ident)
        card: dict[str, Any] = {"id": ident, "kind": reference.kind}
        provenance = getattr(reference, "provenance", None)
        if isinstance(provenance, Mapping):
            for field in ("state", "title", "progress"):
                value = provenance.get(field)
                if isinstance(value, str) and value.strip():
                    card[field] = value.strip()[:_GOAL_TEXT_MAX]
            priority = provenance.get("priority")
            if isinstance(priority, int) and not isinstance(priority, bool):
                card["priority"] = priority
        cards.append(card)
    return cards[:MAX_TARGET_GOALS]


def _resolving_file_ambiguity(current: Any, *, file_operation_hint: str | None,
                              protected_relation: bool, file_refs: list[Any]) -> bool:
    return bool(
        getattr(current, "needs_input", False)
        and tuple(getattr(current, "ambiguities", ())) == ("multiple target references",)
        and current.capability_hint == "files.read"
        and file_operation_hint in {"summarize", "analyze", "locate"}
        and current.conversation_relation is ConversationRelation.NEW_REQUEST
        and current.pending_owner is None
        and not protected_relation
        and len(file_refs) >= 2
    )


def _file_read_arguments(*, text: str, supplied: Mapping[str, Any], slots: tuple[str, ...],
                         by_slot: Mapping[str, Any], slot_labels: Mapping[str, tuple[str, str]],
                         current: Any, resolving_file_ambiguity: bool,
                         file_operation_hint: str | None, file_refs: list[Any],
                         owner: str) -> tuple[dict[str, Any], tuple[Any, ...]] | None:
    """Dosya okuma önerisi yalnız sunulan yuvalardan ve deterministik kanıttan kurulur."""
    if set(supplied) - {"operation"}:
        return None
    operation = supplied.get("operation")
    if operation not in _FILE_OPERATIONS:
        return None
    current_operation = current.arguments.get("operation")
    if current_operation is None and resolving_file_ambiguity:
        current_operation = file_operation_hint
    if current.capability_hint == "files.read" and current_operation != operation:
        return None
    if operation == "list":
        if slots or current.capability_hint != "files.read":
            return None
        return {"original_text": text, "operation": "list"}, ()
    if operation == "compare":
        if not 2 <= len(slots) <= 10:
            return None
        arguments = {"original_text": text, "operation": "compare",
                     "paths": [by_slot[slot].provenance.get("path") for slot in slots]}
    else:
        if len(slots) != 1:
            return None
        arguments = {"original_text": text, "operation": operation,
                     "path": by_slot[slots[0]].provenance.get("path")}
    if "path" in arguments and not (isinstance(arguments["path"], str) and arguments["path"].strip()):
        return None
    if "paths" in arguments and any(not isinstance(value, str) or not value.strip()
                                    for value in arguments["paths"]):
        return None
    # Deterministik kanıt zaten bir hedef çözümlediyse model onu değiştiremez.
    if current.capability_hint == "files.read":
        current_path = current.arguments.get("path")
        current_paths = current.arguments.get("paths")
        if current_path is not None and arguments.get("path") != current_path:
            return None
        if current_paths is not None and arguments.get("paths") != list(current_paths):
            return None
    if not resolving_file_ambiguity:
        return arguments, ()
    if operation != file_operation_hint or len(slots) != 1:
        return None
    selected_label = slot_labels.get(slots[0])
    if selected_label is None or not selected_label[0]:
        return None
    if sum(1 for label in slot_labels.values() if label == selected_label) != 1:
        return None
    selected = by_slot[slots[0]]
    if selected.owner != owner:
        return None
    if not _selected_file_candidate_is_grounded(text, selected, file_refs):
        return None
    return arguments, (selected,)


# Dayanak kıyaslaması kelime/sayı SINIRI ölçer, alt dize değil. Katlama Türkçe İ/I kasımı ve
# "0532 123 45 67" ile "053212345 67" ayraç farklarını taşır; noktalama ve boşluk ayraçtır,
# token değildir. Bir kelimenin İÇİNDEN kesilen parça veya iki ayrı kelimenin yapıştırılması
# token üretmez, dolayısıyla dayanak olamaz. HARF ile RAKAMIN bitişik yazıldığı tek sözcük
# (`ali123`, `gel123iyorum`) de BÖLÜNMEZ tek token SAYILIR: oradan `ali` veya `gel` kesmek
# alt-dize açığının yeni varyantıdır. Sayısal yuvada alt dize yetmez: rakam dizisinin TAMAMI
# eşit olmalıdır. Bu tablolarda tek bir doğal dil kelimesi bile yoktur — sınır biçimledir.
_SPAN_TOKENS = re.compile(r"[^\W_]+", re.UNICODE)
_DIGITS_ONLY = re.compile(r"[0-9]+")


def _span_tokens(value: str) -> tuple[str, ...]:
    return tuple(_SPAN_TOKENS.findall(value.replace("İ", "i").replace("I", "ı").casefold()))


def _is_contiguous_run(needle: tuple[str, ...], haystack: tuple[str, ...]) -> bool:
    """`needle`, `haystack` içinde bitişik bir token dizisi olarak geçiyor mu."""
    if not needle or len(needle) > len(haystack):
        return False
    return any(haystack[index:index + len(needle)] == needle
               for index in range(len(haystack) - len(needle) + 1))


def _field_is_grounded(field: str, value: str, span: str, spoken: tuple[str, ...]) -> bool:
    """Alan, alıntının ve alıntı cümlenin bitişik token dizileri olmak zorundadır."""
    tokens = _span_tokens(span)
    target = _span_tokens(value)
    if not _is_contiguous_run(tokens, spoken) or not target:
        return False
    if field in _GROUNDING_NUMERIC_FIELDS:
        # Sayı yuvası: bitişik TAM rakam dizisinin tamamı eşittir; ayraç fark serbesttir,
        # alt dize (uzun numaranın içinden kesim veya ön ek) değildir.
        if not all(_DIGITS_ONLY.fullmatch(token) for token in tokens + target):
            return False
        return "".join(target) == "".join(tokens)
    return _is_contiguous_run(target, tokens)


def _arguments_are_grounded(*, capability_id: str, supplied: Mapping[str, Any],
                           sources: Any, text: str) -> bool:
    """§4: kullanıcı-sahibi alanlar yalnız kullanıcının kendi cümlesindeki alıntısıyla öneri olur.

    Kapalı sözleşme tablosu `_USER_OWNED_ARGUMENT_SLOTS`tur; burada hiçbir doğal dil hükmü
    verilmez. Dolu bir alan dayanak taşımıyorsa, dayanak cümlede bitişik kelime/sayı dizileri
    olarak geçmiyorsa ya da alanı o alıntının tam dizileri değilse önerinin TAMAMI düşer
    (fail-closed). Boş slot dayanak istemez: eksik alıcı/gövde oturumun kendi sorusudur,
    uydurulmaz.
    """
    owned = _USER_OWNED_ARGUMENT_SLOTS.get(capability_id)
    if owned is None:
        # Dayanak alanı olmayan bir yetenekte bu anahtar taşımak sözleşme ihlalidir.
        return sources is None
    if sources is None:
        sources = {}
    if not isinstance(sources, Mapping) or any(not isinstance(key, str) or not isinstance(value, str)
                                              for key, value in sources.items()):
        return False
    if set(sources) - owned:
        return False
    spoken = _span_tokens(text)
    if capability_id == "macro.teach":
        actions = supplied.get("actions")
        if (not isinstance(actions, (tuple, list)) or not actions
                or any(not isinstance(action, str) or not _span_tokens(action)
                       or not _is_contiguous_run(_span_tokens(action), spoken) for action in actions)):
            return False
    for field in owned:
        value = supplied.get(field)
        filled = ((isinstance(value, str) and bool(value.strip()))
                  or (field == "index" and type(value) is int and value > 0))
        span = sources.get(field)
        if span is None:
            if filled:
                return False
            continue
        if not filled or not _field_is_grounded(field, str(value) if field == "index" else value, span, spoken):
            return False
    return True


def _action_arguments(*, capability_id: str, supplied: Mapping[str, Any], text: str,
                      deterministic_arguments: Mapping[str, Any], slots: tuple[str, ...],
                      by_slot: Mapping[str, Any], slot_labels: Mapping[str, tuple[str, str]],
                      current: Any, resolving_file_ambiguity: bool,
                      file_operation_hint: str | None, file_refs: list[Any],
                      owner: str) -> tuple[dict[str, Any], tuple[Any, ...]] | None:
    if capability_id == "files.read":
        return _file_read_arguments(
            text=text, supplied=supplied, slots=slots, by_slot=by_slot,
            slot_labels=slot_labels, current=current,
            resolving_file_ambiguity=resolving_file_ambiguity,
            file_operation_hint=file_operation_hint, file_refs=file_refs, owner=owner)
    if slots:
        return None
    # Model alan doldurmadıysa payload deterministik kanıttan gelir; model hiç argüman uydurmaz.
    if capability_id in {"finance.read", "documents.export", "system.diagnose"}:
        payload = dict(supplied)
    elif supplied:
        payload = dict(supplied)
    else:
        payload = dict(deterministic_arguments)
    if capability_id != "finance.read" and "original_text" not in payload:
        payload = {"original_text": text, **payload}
    return payload, ()


def _action_count_matches(operation: str, action_rows: list[Any], goal: Mapping[str, Any] | None,
                          target_ids: tuple[str, ...]) -> bool:
    count = len(action_rows)
    if operation in {"chat", "clarify"}:
        return count == 0 and goal is None and not target_ids
    if operation == "direct_action":
        return count == 1 and goal is None and not target_ids
    if operation == "action_batch":
        return 2 <= count <= MAX_ACTIONS and goal is None and not target_ids
    if operation == "create_goal":
        return count == 0 and goal is not None and not target_ids
    if operation not in GOAL_OPERATIONS:
        return False
    return count == 0 and goal is None and bool(target_ids)


def _build(row: dict[str, Any], *, owner: str, text: str, current: Any,
           deterministic_arguments: Mapping[str, Any], protected_relation: bool,
           file_operation_hint: str | None,
           goal_candidates: tuple[Any, ...] = ()) -> UnderstandingProposal | None:
    from modules.brain_core_map import CORE_INTENTS, core_plan

    operation = row["operation"]
    if not isinstance(operation, str) or operation not in OPERATIONS:
        return _reject('OPERATION_INVALID')
    try:
        relation = ConversationRelation(row["conversation_relation"])
        temporal_need = TemporalNeed(row["temporal_need"])
        confidence = Confidence(row["confidence"])
    except ValueError:
        return _reject('ENUM_VALUE_INVALID')

    file_refs = [reference for reference in current.references
                 if getattr(reference, "kind", None) == "file"]
    _, slot_refs, slot_labels = _file_slots(current)
    by_slot = dict(slot_refs)
    resolving_file_ambiguity = _resolving_file_ambiguity(
        current, file_operation_hint=file_operation_hint,
        protected_relation=protected_relation, file_refs=file_refs)
    offered_goals = set(_offered_goal_ids(goal_candidates))

    target_ids = _text_list("target_goal_ids", row["target_goal_ids"])
    if target_ids is None or len(target_ids) > MAX_TARGET_GOALS:
        return _reject('GOAL_TARGET_NOT_OFFERED')
    # BRAIN-05: hedef işlemi olmayan bir önerinin hedef kimliği taşıması zaten uydurmadır.
    # Hedef işleminde ise sunılmamış kimliği burada düşürmeyiz: öneri kaybolursa cümle legacy
    # planner'a düşer ve YENİ bir GoalState açar — kaçınılması gereken "hedef uydurma". Kimlik
    # olduğu gibi yürütücüye taşınır; `goal_resolver` onu yalnız owner'ın kendi açık
    # kayıtlarında arar, bulamazsa efekt yerine soru üretir (`GOAL_TARGET_NOT_OFFERED`).
    if not set(target_ids) <= offered_goals and row["operation"] not in GOAL_OPERATIONS:
        return _reject('GOAL_TARGET_NOT_OFFERED')
    goal_row = row["goal"]
    goal = None if goal_row is None else _goal_payload(goal_row)
    if goal_row is not None and goal is None:
        return _reject('GOAL_CARD_INVALID')

    clarification_row = row["clarification"]
    if not isinstance(clarification_row, Mapping) or set(clarification_row) - set(CLARIFICATION_KEYS):
        return _reject('CLARIFICATION_SHAPE_INVALID')
    required = clarification_row.get("required")
    question = clarification_row.get("question")
    reason_code = clarification_row.get("reason_code")
    if not isinstance(required, bool) or required != (operation == "clarify"):
        return _reject('CLARIFICATION_FLAG_MISMATCH')
    if required:
        if (not isinstance(question, str) or not question.strip() or len(question) > 600
                or "\x00" in question or not isinstance(reason_code, str)
                or _REASON_CODE.fullmatch(reason_code) is None):
            return _reject('CLARIFICATION_DETAIL_INVALID')
    elif question is not None or reason_code is not None:
        return _reject('CLARIFICATION_UNUSED_DETAIL')

    action_rows = row["actions"]
    if not isinstance(action_rows, list) or not _action_count_matches(
            operation, action_rows, goal, target_ids):
        return _reject('ACTION_COUNT_MISMATCH')

    actions: list[ProposedAction] = []
    grounded_references: list[Any] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(action_rows):
        if not isinstance(item, Mapping) or set(item) - set(ACTION_KEYS):
            return _reject('ACTION_SHAPE_INVALID')
        action_id = item.get("action_id")
        capability_id = item.get("capability_id")
        supplied = item.get("arguments")
        slots = _text_list("reference_slots", item.get("reference_slots"))
        depends_on = _text_list("depends_on", item.get("depends_on"))
        if (not isinstance(action_id, str) or action_id != f"a{index + 1}" or action_id in seen_ids
                or not isinstance(capability_id, str) or capability_id not in CORE_INTENTS
                or slots is None or depends_on is None or not set(slots) <= set(by_slot)
                or not set(depends_on) <= seen_ids):
            return _reject('ACTION_REFERENCE_INVALID')
        if not isinstance(supplied, Mapping):
            return _reject('ARGUMENTS_NOT_OBJECT')
        try:
            _reject_authority_argument_keys(supplied)
            frozen = _freeze_json(supplied)
        except ValueError:
            return _reject('ARGUMENTS_INVALID')
        if _MODEL_DENIED_ARGUMENT_KEYS & _deep_keys(frozen):
            return _reject('ARGUMENT_AUTHORITY_FIELD')
        if capability_id in _MODEL_DENIED_CAPABILITIES:
            return _reject('CAPABILITY_NOT_MODEL_OWNED')
        if not _arguments_are_grounded(capability_id=capability_id, supplied=frozen,
                                      sources=item.get("argument_sources"), text=text):
            return _reject('ARGUMENT_SOURCE_INVALID')
        resolved = _action_arguments(
            capability_id=capability_id, supplied=dict(frozen), text=text,
            deterministic_arguments=deterministic_arguments, slots=slots, by_slot=by_slot,
            slot_labels=slot_labels, current=current,
            resolving_file_ambiguity=resolving_file_ambiguity,
            file_operation_hint=file_operation_hint, file_refs=file_refs, owner=owner)
        if resolved is None or core_plan(capability_id, resolved[0]) is None:
            return _reject('CORE_ARGUMENTS_INVALID')
        arguments, references = resolved
        if any(reference.owner != owner for reference in references):
            return _reject('REFERENCE_OWNER_MISMATCH')
        grounded_references.extend(references)
        seen_ids.add(action_id)
        actions.append(ProposedAction(
            action_id=action_id, capability_id=capability_id, arguments=_freeze_json(arguments),
            reference_slots=slots, depends_on=depends_on))

    proposed = UnderstandingProposal(
        operation=operation,
        conversation_relation=relation,
        temporal_need=temporal_need,
        confidence=confidence,
        actions=tuple(actions),
        target_goal_ids=target_ids,
        goal=goal,
        clarification_required=required,
        clarification_reason_code=reason_code if required else None,
        clarification_question=question if required else None,
        references=tuple(grounded_references),
    )
    return _apply_semantic_fences(
        proposed, current, protected_relation=protected_relation,
        resolving_file_ambiguity=resolving_file_ambiguity,
        has_grounded_reference=bool(grounded_references))


def _apply_semantic_fences(proposed: UnderstandingProposal, current: Any, *,
                           protected_relation: bool, resolving_file_ambiguity: bool,
                           has_grounded_reference: bool) -> UnderstandingProposal | None:
    # Sahibi olan bir devam/düzeltme/tur değişimi deterministik kanıtla kurulur; model onu
    # yeniden adlandıramaz. Korunan turda yalnız aynı ilişkide ve aynı kararda benimsenir.
    artifact_context = bool(
        current.pending_owner is None
        and current.conversation_relation is ConversationRelation.CONTINUE_ACTIVE
        and any(ref.kind == "artifact" and ref.id == "last_doc" and ref.owner == current.owner
                for ref in current.references)
        and not any(ref.kind in _GOAL_CARD_KINDS for ref in current.references)
    )
    free_context = current.pending_owner is None and (
        current.conversation_relation is ConversationRelation.NEW_REQUEST or artifact_context)
    model_owned_action = bool(proposed.actions and proposed.actions[0].capability_id
                              in {"documents.export", "system.diagnose"})
    model_owned_decision = proposed.operation in {'chat','clarify'} or model_owned_action
    # Gerçek sahipliği olmayan serbest turda (pending owner yok, hedef/görev kartı yok) model bir
    # düzeltmeyi sohbet/netleştirme olarak CORRECTION ile adlandırabilir. Etiket kendi anlamıyla
    # kalır, kanonikal değere yazılmaz: CONTINUE_ACTIVE bekleyen bir etkileşimin sahipliğidir ve
    # brain_entry._pending_owns_turn CORRECTION turunu bağımsız sayar. Sahiplik yokken bu yalnız
    # anlam bildirimidir; hiçbir efekt veya yetki taşımaz.
    if proposed.conversation_relation not in {current.conversation_relation,
                                              ConversationRelation.NEW_REQUEST}:
        if not (free_context and proposed.operation in {'chat', 'clarify'}
                and proposed.conversation_relation is ConversationRelation.CORRECTION):
            return _reject('RELATION_NOT_CURRENT')
    if protected_relation and not (free_context and model_owned_decision):
        # BRAIN-05: hedef işlemleri artık yürütücüsüne bağlıdır, dolayısıyla "henüz bağlanmamış
        # işlem" kapısı kalktı. Korunan turda bağlayıcı olan şey işlemin ADI değil, tura kimin
        # sahip olduğudur: ilişki yerinde kalmalı ve bir pending slotun cevabını hedef işlemi
        # devralamaz. REQUEST_KIND_BY_OPERATION hedef işlemlerini GOAL_CONTROL'e eşler; bu kind
        # deterministik katmanların ürettiği bir karar değildir, bu yüzden hedef önerisinde kind
        # eşitliği aranamaz — bağdaşıklık denetimi offered kart kimlikleri üzerinden yapılır.
        goal_proposal = proposed.operation in GOAL_OPERATIONS
        if proposed.conversation_relation is not current.conversation_relation:
            return _reject('PROTECTED_RELATION')
        if goal_proposal:
            if current.pending_owner is not None:
                return _reject('PROTECTED_PENDING_OWNER')
        elif REQUEST_KIND_BY_OPERATION[proposed.operation] is not current.request_kind:
            return _reject('PROTECTED_REQUEST_KIND')
    # Çözülmemiş hedef belirsizliği ancak owner-bound, salt okunur bir dosya seçimiyle açılır.
    if proposed.operation != 'clarify' and bool(getattr(current, "needs_input", False)) and not (
            resolving_file_ambiguity and has_grounded_reference):
        return _reject('UNRESOLVED_TARGET')
    if proposed.operation == "direct_action" and proposed.confidence is Confidence.LOW \
            and not resolving_file_ambiguity:
        return _reject('ACTION_CONFIDENCE_LOW')
    if proposed.operation != 'clarify' and resolving_file_ambiguity and not has_grounded_reference:
        return _reject('FILE_REFERENCE_UNRESOLVED')
    # Legacy capabilities keep their migration fence. For model-owned output/diagnosis,
    # a deterministic LOW guess is not semantic authority over the validated model decision.
    # BRAIN-05 hedef işlemi de model-owned'dır: deterministik katmanın hedef anlamı hakkında
    # hiçbir kararı yoktur (eski sahibi yalnız front-gate grameriydi, o da plan ile yürür).
    # Dayanak veto yerine geçmez — `target_goal_ids` sunulmuş kartların alt kümesi olmak
    # zorundadır ve hedefin sözü kullanıcının cümlesidir.
    goal_operation = proposed.operation in GOAL_OPERATIONS
    if (_CONFIDENCE_RANK[proposed.confidence] > _CONFIDENCE_RANK[current.confidence]
            and not (free_context and model_owned_decision) and not goal_operation):
        if not resolving_file_ambiguity:
            return _reject('LEGACY_CONFIDENCE_VETO')
        proposed = UnderstandingProposal(
            operation=proposed.operation,
            conversation_relation=proposed.conversation_relation,
            temporal_need=proposed.temporal_need,
            confidence=Confidence.MEDIUM,
            actions=proposed.actions,
            target_goal_ids=proposed.target_goal_ids,
            goal=proposed.goal,
            clarification_required=proposed.clarification_required,
            clarification_reason_code=proposed.clarification_reason_code,
            clarification_question=proposed.clarification_question,
            references=proposed.references,
        )
    return proposed


def propose(*, owner: str, text: str, current: Any, arguments: Mapping[str, Any],
            protected_relation: bool = False,
            file_operation_hint: str | None = None,
            goal_candidates: tuple[Any, ...] = (),
            session_artifacts: tuple[dict[str, str], ...] = ()) -> UnderstandingProposal | None:
    """Tek bounded çağrı: yalnız zaten uygun ücretsiz bulut rotası, her hatada kapalı durur.

    Model kararı üretir (işlem, yetenek, önerilen argüman, sunulan yuva seçimi). Gerçek hedef
    kimliği, yol, hesap, jeton veya onay asla modelden gelmez; her alan Core'un kendi
    doğrulayıcısından geçmeden öneri sayılmaz. Kullanıcı-sahibi alanlar (alıcı, gövde, kişi adı,
    telefon) modelden gelebilir ama ancak cümlenin kendisinden alıntılanmış bir dayanakla.
    """
    proposal_diagnostic(clear=True)
    if not owner or not isinstance(text, str) or not text.strip():
        return _reject('INPUT_INVALID')
    try:
        from modules import llm, provider_privacy, requests_state, smart_router
        if llm.current_user() != owner:
            return _reject('PROFILE_OWNER_MISMATCH')
        selected = llm.provider()
        # Açıkça seçilmiş ücretli/yerel rotalar Brain tarafından kullanılmaz veya sessiz geçilmez.
        if selected in _PAID or selected in _LOCAL or llm.privacy.mode() == "yerel":
            return _reject('PROVIDER_ROUTE_DISABLED')
        route = provider_privacy.ROUTE_PRIVATE_GENERAL
        eligible = smart_router.selection(owner, "analysis", route=route).get("candidates", [])
        if not any(name in {"groq", "cloudflare"} for name in eligible):
            return _reject('PROVIDER_UNAVAILABLE')

        from modules.brain_core_map import CORE_INTENTS
        slot_rows, _, _ = _file_slots(current)
        # Model, kendisine kapalı bir yeteneği de seçebilir sanmasın: önerilen katalog, yasak
        # kümeyi taşımaz. Yetki yine `_build`deki fail-closed denetimidir, promptta değil.
        offered_capabilities = sorted(set(CORE_INTENTS) - _MODEL_DENIED_CAPABILITIES)
        prompt = json.dumps({
            "schema": SCHEMA_VERSION,
            "response_schema": _response_schema(offered_capabilities),
            "utterance": text[:2000],
            "current": {
                "request_kind": current.request_kind.value,
                "conversation_relation": current.conversation_relation.value,
                "temporal_need": current.temporal_need.value,
                "capability_hint": current.capability_hint,
                "needs_input": bool(getattr(current, "needs_input", False)),
                "ambiguities": list(getattr(current, "ambiguities", ())),
                "file_operation_hint": file_operation_hint,
                "current_output": _current_output(session_artifacts),
            },
            "allowed": {
                "operation": sorted(OPERATIONS),
                "capability_id": offered_capabilities,
                "conversation_relation": [item.value for item in ConversationRelation],
                "temporal_need": [item.value for item in TemporalNeed],
                "file_operation": list(_FILE_OPERATIONS),
                "argument_schema": {name: _supplied_schema(name) for name in offered_capabilities},
            },
            "file_candidates": slot_rows,
            "goal_candidates": _offered_goal_cards(goal_candidates),
            "session_artifacts": list(session_artifacts),
        }, ensure_ascii=False)
        system = (
            "You are the primary semantic decider, not an agent. Return exactly one bare JSON object "
            "matching response_schema, without a named wrapper or Markdown. "
            f'The schema_version field must equal the literal string "{SCHEMA_VERSION}". '
            "The top-level keys are schema_version, operation, conversation_relation, "
            "temporal_need, target_goal_ids, goal, actions, clarification, confidence. "
            "Do a FINAL JSON CONTRACT CHECK: include these nine keys exactly once, "
            "use the required schema_version literal, always include temporal_need, "
            "never add extra fields, and output no wrapper. Choose "
            "operation among chat, direct_action, action_batch, create_goal, continue_goal, "
            "revise_goal, add_task, pause_goal, resume_goal, cancel_goal, prioritize_goal, clarify. "
            "Each actions entry carries only action_id, capability_id, arguments, reference_slots, "
            "depends_on, argument_sources with action_id a1, a2 in order; chat, clarify and goal "
            "operations carry no action, direct_action exactly one, action_batch two to five. "
            "capability_id must be one of allowed.capability_id. Write no file path, folder, "
            "account, token, credential, approval id or permission claim: for files.read select "
            "only supplied file_candidates slots (one for open/summarize/analyze/locate, two to "
            "ten for compare, none for list) and put only the operation in arguments. "
            "reference_slots are only for files.read; for every other capability use an empty array. "
            "Simple semantic values the schema allows are yours to fill: query, city, number, closed "
            "action enum, and for the capabilities listed in allowed.argument_schema. Each "
            "allowed.argument_schema entry also carries that capability's purpose and precondition: "
            "choose the capability whose purpose matches what the user wants to happen, and treat a "
            "failed precondition as a reason to clarify, never as a reason to pick another capability. "
            "For capabilities whose allowed.argument_schema lists argument_sources, use an object "
            "mapping each filled named field to the exact words the user said; otherwise set it "
            "to null. For macro.teach every action must itself quote a contiguous part of the "
            "utterance. Use goal=null when no goal card is proposed. "
            "goal_candidates contains this owner's own Core-observed open goals, with id, title, state, progress and priority. "
            "GOAL OUTPUT CONTRACT: For continue_goal, revise_goal, add_task, pause_goal, "
            "resume_goal, cancel_goal and prioritize_goal, set goal=null, actions=[], "
            "and target_goal_ids to an array containing the exact id of the named "
            "goal from goal_candidates (typically ONE id). A revise_goal or add_task "
            "MUST NOT supply a new goal card: the user's original utterance is the "
            "revision/task text and the Core resolver owns it. For create_goal only, "
            "set a goal card with kind=goal and title from the utterance, "
            "target_goal_ids=[], actions=[]. For chat or clarify use goal=null, "
            "target_goal_ids=[], actions=[]. Never invent a goal id; clarify when "
            "the target cannot be selected. CRUCIAL: the operation continue_goal "
            "or resume_goal describes an EXISTING GOAL, NOT the conversation relation. "
            "For ALL goal operations COPY current.conversation_relation exactly. "
            "If current.conversation_relation=NEW_REQUEST, keep NEW_REQUEST even for "
            "continue_goal, resume_goal or add_task; CONTINUE_ACTIVE is only valid "
            "when current.conversation_relation itself is CONTINUE_ACTIVE. "
            "A goal operation has no capability actions or arbitrary arguments. "
            "GOAL PRIORITY VS REVISION: prioritize_goal changes only relative priority, "
            "importance, ordering or which goal is first; it never edits goal text or "
            "tasks. For example, 'Put the planning goal at the top of the priority list' "
            "is prioritize_goal, NOT revise_goal. Revise_goal is only for changing the "
            "goal's content, scope or requested result, such as 'Change the planning goal "
            "from a report to a presentation'. Add_task adds a new step, not priority. "
            "GOAL NEGATION SAFETY: Classify the user's ENTIRE utterance before choosing "
            "any effectful goal operation. A prohibition, including Turkish negative "
            "imperatives such as 'iptal etme' and 'duraklatma', negates the commanded "
            "operation. The mere appearance of 'iptal' or a goal title is NOT authority "
            "to cancel. If the user says 'Planlama hedefini iptal etme, bu kavramı anlat' "
            "the ONLY allowed operation is chat with goal=null, target_goal_ids=[] and "
            "actions=[]; never cancel_goal. Conversely 'Planlama hedefini iptal et' "
            "is a cancel_goal request if the goal is uniquely identified. Questions "
            "ABOUT how an operation works are chat, not actions; if the request is "
            "genuinely ambiguous choose clarify instead of making any change. "
            "When clarification is not required use required=false, question=null, reason_code=null. 
            "For each such field argument_sources must quote the exact words of this utterance "
            "carrying it; a value the utterance does not contain, a quote taken from another "
            "sentence, or a missing quote drops the whole proposal, so leave a field empty instead "
            "of inventing it and Core will ask the user. current.current_output states whether this "
            "conversation has a produced result Core can still save: when available is false that "
            "result does not exist yet, so a request to keep, save or export it must clarify instead "
            "of naming one - this says nothing about file_candidates, which still describe files the "
            "user named and stay usable; when available is true that result is the standing target of "
            "such a request, so do not ask for it again. An explicit target the user chose from "
            "file_candidates or reference_slots is judged by the selected capability's own contract: "
            "for the capability it names, that choice decides the target and is not an ambiguity; "
            "choose clarify only when the target genuinely cannot be decided. Judge the operation the "
            "utterance asks Jarvis to perform, not its surface form: a polite or interrogative "
            "request to carry something out is that operation, while a question about what a word, "
            "phrase or capability means, a quotation and a comment about the world are chat. A "
            "negation withdraws only the step it governs: refusing an operation makes the turn chat "
            "about that refusal, and limiting a later step leaves the requested step standing. If "
            "the target cannot be decided choose clarify with a "
            "required reason_code and never guess. If current.needs_input is true keep it unless "
            "the only ambiguity is multiple target references and one supplied file candidate is "
            "clearly named by the utterance. Core revalidates every field."
        )
        deadline = time.monotonic() + _MODEL_BUDGET_SECONDS

        def send(provider: str) -> str:
            requests_state.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests_state.LocalDeadline("Brain model understanding budget expired.")
            # Dördüncü argüman saniye değil token limiti. Süre tek yerden gelir:
            # requests_state bütçesi (yukarıdaki deadline ile aynı _MODEL_BUDGET_SECONDS);
            # llm.transport_timeouts soket zaman aşımlarını o bütçenin üstüne çıkarmaz,
            # ama asıl sınır bütçenin kendisidir — soket süresi toplam deadline değildir.
            return llm._send_provider(provider, prompt, system, _RESPONSE_MAX_TOKENS, None)

        with requests_state.budget(_MODEL_BUDGET_SECONDS):
            # Akıllı Yönlendirici tek sağlayıcı seçicidir; buradan yerel yedek düşürülür.
            raw = smart_router.run(
                owner, prompt + "\\n" + system, send, route=route,
                exclude_providers={"ollama"},
            )
            requests_state.check()
        row = _decode(raw)
        # Retain only closed protocol enums, never arbitrary response fields/arguments.
        detail = {}
        for key, allowed in (('operation', OPERATIONS),
                             ('conversation_relation', {v.value for v in ConversationRelation}),
                             ('confidence', {v.value for v in Confidence})):
            if isinstance(row.get(key), str) and row[key] in allowed:
                detail[key] = row[key]
        action_rows = row.get('actions')
        if isinstance(action_rows, list):
            detail['action_count'] = len(action_rows)
            detail['goal_card_present'] = row.get('goal') is not None
            goal_ids = row.get('target_goal_ids')
            detail['target_goal_count'] = len(goal_ids) if isinstance(goal_ids, list) else None
            detail['capabilities'] = [a['capability_id'] for a in action_rows
                if isinstance(a,dict) and isinstance(a.get('capability_id'),str)
                and a['capability_id'] in CORE_INTENTS]
        _proposal_diagnostic.set(detail)
        result = _build(
            row, owner=owner, text=text, current=current,
            deterministic_arguments=arguments, protected_relation=protected_relation,
            file_operation_hint=file_operation_hint, goal_candidates=goal_candidates)
        if result is not None:
            _proposal_diagnostic.set({**proposal_diagnostic(), 'status':'accepted', 'reason_code':None})
        return result
    except Exception as exc:
        _record_failure("modules/brain_model_understanding.py:propose")
        # Kullanıcı iptali istek sınırına kadar taşınır; diğer her hata deterministik kararı korur.
        from modules import requests_state
        if isinstance(exc, requests_state.Cancelled):
            code = 'REQUEST_CANCELLED'
        elif isinstance(exc, requests_state.LocalDeadline):
            # Yerel süre aşımı ile sağlayıcının yanıt vermemesi ayrı kök nedenlerdir.
            code = 'LOCAL_DEADLINE_EXCEEDED'
        else:
            code = 'MODEL_CALL_OR_VALIDATION_ERROR'
        if proposal_diagnostic().get('status') != 'rejected':
            _reject(code)
        if isinstance(exc, requests_state.Cancelled):
            raise
        return None
