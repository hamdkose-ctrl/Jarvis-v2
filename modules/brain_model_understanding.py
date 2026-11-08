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
from typing import Any, Mapping

from modules.diagnostics import record_failure as _record_failure

from modules.brain_contracts import (
    Confidence, ConversationRelation, RequestKind, TemporalNeed,
    _freeze_json, _reject_authority_argument_keys,
)

_PAID = frozenset({"openai", "anthropic"})
_LOCAL = frozenset({"ollama"})

SCHEMA_VERSION = "brain-understanding.v2"
MAX_ACTIONS = 5
MAX_TARGET_GOALS = 8
_GOAL_TEXT_MAX = 200
_RESPONSE_MAX_TOKENS = 2048

OPERATIONS = frozenset({
    "chat", "direct_action", "action_batch", "create_goal", "continue_goal", "revise_goal",
    "add_task", "pause_goal", "resume_goal", "cancel_goal", "prioritize_goal", "clarify",
})
GOAL_OPERATIONS = frozenset({
    "create_goal", "continue_goal", "revise_goal", "add_task", "pause_goal",
    "resume_goal", "cancel_goal", "prioritize_goal",
})
# BRAIN-01'de üretim akışına bağlanan işlemler. Diğerleri burada doğrulanır ama yürütücüleri
# BRAIN-04/BRAIN-05'te yazılacak; bu paket onları çalışıyor gibi göstermez.
ADOPTED_OPERATIONS = frozenset({"chat", "direct_action"})
REQUEST_KIND_BY_OPERATION = {
    "chat": RequestKind.CHAT,
    "direct_action": RequestKind.CAPABILITY,
}

ENVELOPE_KEYS = frozenset({
    "schema_version", "operation", "conversation_relation", "temporal_need",
    "target_goal_ids", "goal", "actions", "clarification", "confidence",
})
ACTION_KEYS = frozenset({"action_id", "capability_id", "arguments", "reference_slots",
                         "depends_on", "argument_sources"})
CLARIFICATION_KEYS = frozenset({"required", "question", "reason_code"})
_GOAL_KEYS = frozenset({"kind", "title"})
_GOAL_CARD_KINDS = frozenset({"goal", "task"})

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
}

# Kullanıcı-sahibi alanlardan hangileri SAYIDIR. Bu bir doğal dil listesi değildir; hangi
# yuvanın rakam dizisi olarak karşılaştırılacağının kapalı sözleşmesidir (telefon). Metin
# alanları kelime dizisiyle, sayısal alanlar rakam dizisinin TAMAMIyla doğrulanır.
_GROUNDING_NUMERIC_FIELDS = frozenset({"phone"})

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
    references: tuple[Any, ...] = ()


def _decode(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > 6000:
        raise ValueError("Model zarfı sınırlandırılmış metin değil.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Model zarfı JSON nesnesi olmalı.")
    if set(value) != set(ENVELOPE_KEYS):
        raise ValueError("Model zarfı şeması uyuşmuyor.")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Model zarfı sürümü uyuşmuyor.")
    return value


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


def _supplied_schema(capability_id: str) -> dict[str, Any]:
    """Modelin bu yetenek için doldurabileceği alanların biçimi; değer kümesini Core doğrular."""
    from modules.brain_core_map import CORE_INTENTS
    if capability_id not in CORE_INTENTS:
        return {}
    owned = _USER_OWNED_ARGUMENT_SLOTS.get(capability_id)
    if owned:
        # Sözleşme modelce görülebilir olsun: bu alanlar cümleden alıntılanmak zorundadır.
        return {"freeform": True, "argument_sources": sorted(owned)}
    if capability_id in {"documents.export", "system.diagnose"}:
        return {"arguments": {}, "target": "current owner's session output" if capability_id == "documents.export" else "read-only system checks"}
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
    validator = CORE_INTENTS[capability_id][1]
    if validator.__name__ in {"_audio_args", "_media_args", "_window_list_args", "_window_op_args"}:
        return {"nested": {"action": "kapalı eylem kümesi"}}
    return {"freeform": True}



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


def _offered_goal_ids(current: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(reference.id) for reference in current.references
        if getattr(reference, "kind", None) in _GOAL_CARD_KINDS
    ))


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
    for field in owned:
        value = supplied.get(field)
        filled = isinstance(value, str) and bool(value.strip())
        span = sources.get(field)
        if span is None:
            if filled:
                return False
            continue
        if not filled or not _field_is_grounded(field, value, span, spoken):
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
           file_operation_hint: str | None) -> UnderstandingProposal | None:
    from modules.brain_core_map import CORE_INTENTS, core_plan

    operation = row["operation"]
    if not isinstance(operation, str) or operation not in OPERATIONS:
        return None
    try:
        relation = ConversationRelation(row["conversation_relation"])
        temporal_need = TemporalNeed(row["temporal_need"])
        confidence = Confidence(row["confidence"])
    except ValueError:
        return None

    file_refs = [reference for reference in current.references
                 if getattr(reference, "kind", None) == "file"]
    _, slot_refs, slot_labels = _file_slots(current)
    by_slot = dict(slot_refs)
    resolving_file_ambiguity = _resolving_file_ambiguity(
        current, file_operation_hint=file_operation_hint,
        protected_relation=protected_relation, file_refs=file_refs)
    offered_goals = set(_offered_goal_ids(current))

    target_ids = _text_list("target_goal_ids", row["target_goal_ids"])
    if (target_ids is None or len(target_ids) > MAX_TARGET_GOALS
            or not set(target_ids) <= offered_goals):
        return None
    goal_row = row["goal"]
    goal = None if goal_row is None else _goal_payload(goal_row)
    if goal_row is not None and goal is None:
        return None
    if goal is not None and (_MODEL_DENIED_ARGUMENT_KEYS & _deep_keys(goal)):
        return None

    clarification_row = row["clarification"]
    if not isinstance(clarification_row, Mapping) or set(clarification_row) - set(CLARIFICATION_KEYS):
        return None
    required = clarification_row.get("required")
    question = clarification_row.get("question")
    reason_code = clarification_row.get("reason_code")
    if not isinstance(required, bool) or required != (operation == "clarify"):
        return None
    if required:
        if (not isinstance(question, str) or not question.strip() or len(question) > 600
                or "\x00" in question or not isinstance(reason_code, str)
                or _REASON_CODE.fullmatch(reason_code) is None):
            return None
    elif question is not None or reason_code is not None:
        return None

    action_rows = row["actions"]
    if not isinstance(action_rows, list) or not _action_count_matches(
            operation, action_rows, goal, target_ids):
        return None

    actions: list[ProposedAction] = []
    grounded_references: list[Any] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(action_rows):
        if not isinstance(item, Mapping) or set(item) - set(ACTION_KEYS):
            return None
        action_id = item.get("action_id")
        capability_id = item.get("capability_id")
        supplied = item.get("arguments")
        slots = _text_list("reference_slots", item.get("reference_slots"))
        depends_on = _text_list("depends_on", item.get("depends_on"))
        if (not isinstance(action_id, str) or action_id != f"a{index + 1}" or action_id in seen_ids
                or not isinstance(capability_id, str) or capability_id not in CORE_INTENTS
                or slots is None or depends_on is None or not set(slots) <= set(by_slot)
                or not set(depends_on) <= seen_ids):
            return None
        if not isinstance(supplied, Mapping):
            return None
        try:
            _reject_authority_argument_keys(supplied)
            frozen = _freeze_json(supplied)
        except ValueError:
            return None
        if _MODEL_DENIED_ARGUMENT_KEYS & _deep_keys(frozen):
            return None
        if capability_id in _MODEL_DENIED_CAPABILITIES:
            return None
        if not _arguments_are_grounded(capability_id=capability_id, supplied=frozen,
                                      sources=item.get("argument_sources"), text=text):
            return None
        resolved = _action_arguments(
            capability_id=capability_id, supplied=dict(frozen), text=text,
            deterministic_arguments=deterministic_arguments, slots=slots, by_slot=by_slot,
            slot_labels=slot_labels, current=current,
            resolving_file_ambiguity=resolving_file_ambiguity,
            file_operation_hint=file_operation_hint, file_refs=file_refs, owner=owner)
        if resolved is None or core_plan(capability_id, resolved[0]) is None:
            return None
        arguments, references = resolved
        if any(reference.owner != owner for reference in references):
            return None
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
        references=tuple(grounded_references),
    )
    return _apply_semantic_fences(
        proposed, current, protected_relation=protected_relation,
        resolving_file_ambiguity=resolving_file_ambiguity,
        has_grounded_reference=bool(grounded_references))


def _apply_semantic_fences(proposed: UnderstandingProposal, current: Any, *,
                           protected_relation: bool, resolving_file_ambiguity: bool,
                           has_grounded_reference: bool) -> UnderstandingProposal | None:
    if proposed.conversation_relation not in {current.conversation_relation,
                                              ConversationRelation.NEW_REQUEST}:
        return None
    # Sahibi olan bir devam/düzeltme/tur değişimi deterministik kanıtla kurulur; model onu
    # yeniden adlandıramaz. Korunan turda yalnız aynı ilişkide ve aynı kararda benimsenir.
    artifact_continuation = bool(
        proposed.actions and proposed.actions[0].capability_id == "documents.export"
        and current.pending_owner is None
        and current.conversation_relation is ConversationRelation.CONTINUE_ACTIVE
        and any(ref.kind == "artifact" and ref.id == "last_doc" and ref.owner == current.owner
                for ref in current.references)
    )
    if protected_relation and not artifact_continuation:
        if proposed.operation not in ADOPTED_OPERATIONS:
            return None
        if proposed.conversation_relation is not current.conversation_relation:
            return None
        if REQUEST_KIND_BY_OPERATION[proposed.operation] is not current.request_kind:
            return None
    # Çözülmemiş hedef belirsizliği ancak owner-bound, salt okunur bir dosya seçimiyle açılır.
    if bool(getattr(current, "needs_input", False)) and not (
            resolving_file_ambiguity and has_grounded_reference):
        return None
    if proposed.operation == "direct_action" and proposed.confidence is Confidence.LOW \
            and not resolving_file_ambiguity:
        return None
    if resolving_file_ambiguity and not has_grounded_reference:
        return None
    # Legacy capabilities keep their migration fence. For model-owned output/diagnosis,
    # a deterministic LOW guess is not semantic authority over the validated model decision.
    model_owned_action = bool(proposed.actions and proposed.actions[0].capability_id
                              in {"documents.export", "system.diagnose"})
    if (_CONFIDENCE_RANK[proposed.confidence] > _CONFIDENCE_RANK[current.confidence]
            and not model_owned_action):
        if not resolving_file_ambiguity:
            return None
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
            references=proposed.references,
        )
    return proposed


def propose(*, owner: str, text: str, current: Any, arguments: Mapping[str, Any],
            protected_relation: bool = False,
            file_operation_hint: str | None = None,
            session_artifacts: tuple[dict[str, str], ...] = ()) -> UnderstandingProposal | None:
    """Tek bounded çağrı: yalnız zaten uygun ücretsiz bulut rotası, her hatada kapalı durur.

    Model kararı üretir (işlem, yetenek, önerilen argüman, sunulan yuva seçimi). Gerçek hedef
    kimliği, yol, hesap, jeton veya onay asla modelden gelmez; her alan Core'un kendi
    doğrulayıcısından geçmeden öneri sayılmaz. Kullanıcı-sahibi alanlar (alıcı, gövde, kişi adı,
    telefon) modelden gelebilir ama ancak cümlenin kendisinden alıntılanmış bir dayanakla.
    """
    if not owner or not isinstance(text, str) or not text.strip():
        return None
    try:
        from modules import llm, provider_privacy, requests_state, smart_router
        if llm.current_user() != owner:
            return None
        selected = llm.provider()
        # Açıkça seçilmiş ücretli/yerel rotalar Brain tarafından kullanılmaz veya sessiz geçilmez.
        if selected in _PAID or selected in _LOCAL or llm.privacy.mode() == "yerel":
            return None
        route = provider_privacy.ROUTE_PRIVATE_GENERAL
        eligible = smart_router.selection(owner, "analysis", route=route).get("candidates", [])
        if not any(name in {"groq", "cloudflare"} for name in eligible):
            return None

        from modules.brain_core_map import CORE_INTENTS
        slot_rows, _, _ = _file_slots(current)
        # Model, kendisine kapalı bir yeteneği de seçebilir sanmasın: önerilen katalog, yasak
        # kümeyi taşımaz. Yetki yine `_build`deki fail-closed denetimidir, promptta değil.
        offered_capabilities = sorted(set(CORE_INTENTS) - _MODEL_DENIED_CAPABILITIES)
        prompt = json.dumps({
            "schema": SCHEMA_VERSION,
            "utterance": text[:2000],
            "current": {
                "request_kind": current.request_kind.value,
                "conversation_relation": current.conversation_relation.value,
                "temporal_need": current.temporal_need.value,
                "capability_hint": current.capability_hint,
                "needs_input": bool(getattr(current, "needs_input", False)),
                "ambiguities": list(getattr(current, "ambiguities", ())),
                "file_operation_hint": file_operation_hint,
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
            "goal_candidates": list(_offered_goal_ids(current)),
            "session_artifacts": list(session_artifacts),
        }, ensure_ascii=False)
        system = (
            "You are the primary semantic decider, not an agent. Return exactly one JSON object "
            f"named {SCHEMA_VERSION} with keys schema_version, operation, conversation_relation, "
            "temporal_need, target_goal_ids, goal, actions, clarification, confidence. Choose "
            "operation among chat, direct_action, action_batch, create_goal, continue_goal, "
            "revise_goal, add_task, pause_goal, resume_goal, cancel_goal, prioritize_goal, clarify. "
            "Each actions entry carries only action_id, capability_id, arguments, reference_slots, "
            "depends_on, argument_sources with action_id a1, a2 in order; chat, clarify and goal "
            "operations carry no action, direct_action exactly one, action_batch two to five. "
            "capability_id must be one of allowed.capability_id. Write no file path, folder, "
            "account, token, credential, approval id or permission claim: for files.read select "
            "only supplied file_candidates slots (one for open/summarize/analyze/locate, two to "
            "ten for compare, none for list) and put only the operation in arguments. Simple "
            "semantic values the schema allows are yours to fill: query, city, number, closed "
            "action enum, and for the capabilities listed in allowed.argument_schema."
            "argument_sources the recipient, body, contact name and phone the user actually said. "
            "For each such field argument_sources must quote the exact words of this utterance "
            "carrying it; a value the utterance does not contain, a quote taken from another "
            "sentence, or a missing quote drops the whole proposal, so leave a field empty instead "
            "of inventing it and Core will ask the user. A question, negation or comment about the "
            "world is chat, not an action. If the target cannot be decided choose clarify with a "
            "required reason_code and never guess. If current.needs_input is true keep it unless "
            "the only ambiguity is multiple target references and one supplied file candidate is "
            "clearly named by the utterance. Core revalidates every field."
        )
        deadline = time.monotonic() + 12.0

        def send(provider: str) -> str:
            requests_state.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests_state.Cancelled("Brain model understanding budget expired.")
            # Transport's fourth argument is an integer token limit, not seconds.
            # The independent requests_state budget still bounds elapsed time.
            return llm._send_provider(provider, prompt, system, _RESPONSE_MAX_TOKENS, None)

        with requests_state.budget(12):
            # Akıllı Yönlendirici tek sağlayıcı seçicidir; buradan yerel yedek düşürülür.
            raw = smart_router.run(
                owner, prompt + "\\n" + system, send, route=route,
                exclude_providers={"ollama"},
            )
            requests_state.check()
        return _build(
            _decode(raw), owner=owner, text=text, current=current,
            deterministic_arguments=arguments, protected_relation=protected_relation,
            file_operation_hint=file_operation_hint)
    except Exception as exc:
        _record_failure("modules/brain_model_understanding.py:propose")
        # Kullanıcı iptali istek sınırına kadar taşınır; diğer her hata deterministik kararı korur.
        from modules import requests_state
        if isinstance(exc, requests_state.Cancelled):
            raise
        return None
