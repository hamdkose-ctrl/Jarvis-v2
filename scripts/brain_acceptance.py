"""Canonical Brain acceptance harness: senaryo havuzu baseline'ı ve "aynı veya daha iyi" kapısı.

PR7 Closeout-B (tek-beyin göçü) için kabul kapısı. Davranış DEĞİŞTİRMEZ; yalnız ölçer.

Her senaryo yalıtılmış sahte bir runtime ile canonical Brain girişinden geçirilir:
``brain_entry.prepare`` (ActiveContext → State Gate → Fast Gate → Candidates →
Resolver → Understanding) ve ardından ``brain_entry.handoff``. Core handler ve chat
dispatch gerçek iş yapmaz, yalnız çağrıldıkları kaydedilir. Diskteki kullanıcı
geçmişi, GoalState, görev, masaüstü onayı ve dosya envanteri okunmaz; hepsi
senaryonun ``setup`` alanından gelir. Model, ağ veya worker çağrılmaz.

Kaydedilen çıktı iki parçadır:

- ``decision``: karşılaştırılan canonical karar (outcome, stage, protocol,
  request_kind, capability_hint, manifest id, relation, needs_input, handoff yolu,
  legacy route projeksiyonu).
- ``info``: karşılaştırılmayan gözlem (temporal_need, confidence, ambiguity,
  referanslar, BrainFeedback, clarification metni, kaydedilen failure noktaları).

Karşılaştırma kuralı (senaryo başına):

- karar baseline ile aynı → ``same``
- senaryonun ``expect``/``forbid`` kriterleri varsa: baseline'ın sağladığı bir
  kriter artık sağlanmıyorsa → ``regression``; kayıp yok ve yeni kriter sağlandıysa
  → ``better``; ikisi de yoksa → ``changed``
- kriter yoksa farklı karar → ``changed`` (insan incelemesi ister)
- çalıştırma hatası → ``error``; baseline'da olup havuzda olmayan → ``missing``

Kapı geçer: ``regression``, ``changed``, ``error`` ve ``missing`` yoksa. Bilinçli bir
``changed`` sonucu ``--accept`` dosyasında gerekçesiyle kabul edilebilir; kabul dosyası
verilmediyse repo'daki ``tests/data/brain_acceptance_accepted_changes.json`` okunur.
Kabul izinleri ölü bırakılamaz: dosyada yazılı bir id bu koşuda ``changed`` üretmiyorsa
kapı ``dead_permit`` ile kalır. Varsayılan repo kabul dosyasındaki canlı izinlerin diff
kümesi ayrıca ``brain_acceptance_accepted_fingerprint.txt`` ile pinlenir; aynı senaryo
başka bir ``changed`` karara kayarsa eski gerekçe onu yeşile çeviremez. Canlı izinlerin
gerekçeleri append-only denetim kaydına ``tests/data/brain_acceptance_kabul_gecmisi.json``
da birebir yazılır; kayıt tüketilmiş izinleri de taşıyabilir, canlı liste taşıyamaz.

Kullanım::

    python -X utf8 scripts/brain_acceptance.py list
    python -X utf8 scripts/brain_acceptance.py capture [--out tests/data/brain_acceptance_baseline.json]
    python -X utf8 scripts/brain_acceptance.py compare [--baseline ...] [--accept kabul.json] [--report rapor.json]

    python -X utf8 scripts/brain_acceptance.py import matris.json [--out tests/data/brain_acceptance_matris_160.json]

Ek havuz aynı şemayla ``--pool dosya.json`` ile eklenir. 160 maddelik audit kabul
matrisi önce ``import`` ile (satır: id, girdi, kategori, beklenen, yasak, setup)
havuz şemasına çevrilir; ardından ``--pool`` ile baseline'a katılır.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Mapping
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
CURATED_POOL = DATA / "brain_acceptance_senaryolari.json"
ROUTING_CORPUS = DATA / "yonlendirme_cumleleri.json"
INJECTION_CORPUS = DATA / "enjeksiyon_senaryolari.json"
DEFAULT_BASELINE = DATA / "brain_acceptance_baseline.json"
DEFAULT_ACCEPTED = DATA / "brain_acceptance_accepted_changes.json"
DEFAULT_ACCEPTED_FINGERPRINT = DATA / "brain_acceptance_accepted_fingerprint.txt"
MATRIX_POOL = DATA / "brain_acceptance_matris_160.json"
PR10_MATRIX_POOL = DATA / "brain_acceptance_matris_pr10_160.json"
# Matris dosyası → senaryo id öneki. Satırı "girdi" taşıyanlar Brain harness'inde koşar.
MATRICES = {MATRIX_POOL: "m160-", PR10_MATRIX_POOL: "p10-"}

OWNER = "hamdi"
FORMAT_VERSION = 1
DECISION_KEYS = (
    "outcome",
    "stage",
    "protocol",
    "request_kind",
    "capability_hint",
    "manifest_capability_id",
    "conversation_relation",
    "needs_input",
    "temporal_need",
    "handoff_path",
    "legacy_projection_intent",
    "goal_question",
)
FAILING_VERDICTS = frozenset({"regression", "changed", "error", "missing"})
_HANDLER_OUTPUT = "<<core-handler>>"
_DISPATCH_OUTPUT = "<<chat-dispatch>>"
_FAKE_SECRET = "SAHTE-ANAHTAR-0000"
_GOAL_CLOSED = frozenset({"done", "cancelled"})


# --------------------------------------------------------------------------- havuz

def _stable_id(prefix: str, text: str) -> str:
    return prefix + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _outcome_from_legacy_label(label: str) -> str:
    if label == "chat":
        return "chat"
    if label == "clarify":
        return "clarify"
    return "action"


def _routing_scenarios(path: Path = ROUTING_CORPUS) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in data.get("cumleler", []):
        text = row["metin"]
        scenario: dict[str, Any] = {
            "id": _stable_id("rota-", text),
            "group": "yonlendirme",
            "text": text,
            "meta": {key: row[key] for key in ("beklenen", "alan", "bolum", "bilinen_hata", "tartismali", "kaynak") if key in row},
        }
        if not row.get("tartismali"):
            scenario["expect"] = {"outcome": _outcome_from_legacy_label(str(row.get("beklenen") or ""))}
        rows.append(scenario)
    return rows


def _injection_scenarios(path: Path = INJECTION_CORPUS) -> list[dict]:
    rows = []
    for row in json.loads(path.read_text(encoding="utf-8")):
        text = str(row.get("gizli_icerik") or "").replace("{secret}", _FAKE_SECRET).strip()
        if not text:
            continue
        rows.append({
            "id": "enj-" + str(row["id"]),
            "group": "enjeksiyon",
            "text": text,
            # Kullanıcı ağzından gelen gömülü talimat bounded/fast bir protokole eşleşmemeli.
            "forbid": {"stage": ["state", "fast"]},
            "meta": {"kaynak": row.get("kaynak"), "kural": row.get("kural")},
        })
    return rows


def _pool_file(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("senaryolar") if isinstance(data, Mapping) else data
    if not isinstance(rows, list):
        raise ValueError(f"{path}: 'senaryolar' listesi bekleniyordu.")
    return [dict(row) for row in rows]


def _validate_scenario(row: Mapping[str, Any]) -> None:
    ident = row.get("id")
    if not isinstance(ident, str) or not ident.strip():
        raise ValueError("Senaryo id boş olamaz.")
    if not isinstance(row.get("text"), str) or not row["text"].strip():
        raise ValueError(f"{ident}: text boş olamaz.")
    for key in ("expect", "forbid", "setup"):
        if key in row and not isinstance(row[key], Mapping):
            raise ValueError(f"{ident}: {key} sözlük olmalı.")
    for key in list(row.get("expect", {})) + list(row.get("forbid", {})):
        if key not in DECISION_KEYS:
            raise ValueError(f"{ident}: bilinmeyen kriter alanı {key!r}.")


def load_pool(extra: Iterable[Path] = (), *, include_corpora: bool = True,
              curated: Path | None = CURATED_POOL, matrices: Mapping[Path, str] | None = None) -> list[dict]:
    rows: list[dict] = []
    if curated is not None:
        rows.extend(_pool_file(curated))
    for path, prefix in (MATRICES if matrices is None else matrices).items():
        rows.extend(matrix_scenarios(path, prefix)[0])
    if include_corpora:
        rows.extend(_routing_scenarios())
        rows.extend(_injection_scenarios())
    for path in extra:
        rows.extend(_pool_file(Path(path)))
    seen: set[str] = set()
    for row in rows:
        _validate_scenario(row)
        if row["id"] in seen:
            raise ValueError(f"Senaryo id tekrarlanıyor: {row['id']}")
        seen.add(row["id"])
    return rows


# --------------------------------------------------------------------------- yalıtılmış çalıştırma

def _session_state(fields: Mapping[str, Any]):
    from modules.session_state import SessionState

    state = SessionState()
    for key, value in fields.items():
        setattr(state, key, value)
    return state


def _timed(value: Any) -> Any:
    """``age_seconds`` taşıyan sözlükte ``ts`` alanını şimdiye göre üretir."""
    if isinstance(value, Mapping) and "age_seconds" in value:
        out = {k: v for k, v in value.items() if k != "age_seconds"}
        out["ts"] = time.time() - float(value["age_seconds"])
        return out
    return value


def _session_fields(fields: Mapping[str, Any]) -> dict:
    """``<alan>_age_seconds`` anahtarını ``<alan>_at`` zaman damgasına çevirir (last_property_at gibi)."""
    out = {}
    for key, value in fields.items():
        if key.endswith("_age_seconds"):
            out[key[: -len("_age_seconds")] + "_at"] = time.time() - float(value)
        else:
            out[key] = _timed(value)
    return out


def _runtime(setup: Mapping[str, Any], owner: str):
    states = {owner: _session_state(_session_fields(dict(setup.get("session") or {})))}
    for foreign_owner, fields in dict(setup.get("foreign_sessions") or {}).items():
        state = _session_state(_session_fields(dict(fields)))
        states[str(foreign_owner)] = state
    photo = setup.get("pending_photo")
    pending_photo = dict(photo) if isinstance(photo, Mapping) else None
    if pending_photo is not None and "age_seconds" in pending_photo:
        pending_photo["t"] = time.time() - float(pending_photo.pop("age_seconds"))
    return SimpleNamespace(
        profile=SimpleNamespace(slug=owner, name=owner.title(), data=dict(setup.get("profile") or {})),
        _sessions=SimpleNamespace(_states=states, _lock=None),
        _session=lambda: states[owner],
        flags={"sleep": bool(setup.get("sleeping"))},
        _pending_photo={owner: pending_photo} if pending_photo is not None else {},
        event_log=[],
    )


def _history_rows(setup: Mapping[str, Any], owner: str) -> list[dict]:
    rows = []
    for index, row in enumerate(setup.get("history") or (), start=1):
        rows.append({
            "id": f"h{index}",
            "owner": owner,
            "role": row.get("role", "user"),
            "text": row.get("text", ""),
            "ts": row.get("ts", 1_700_000_000 + index),
            "source": row.get("source", "yazı"),
        })
    return rows


def _job(setup: Mapping[str, Any]) -> dict | None:
    job = setup.get("job")
    if not isinstance(job, Mapping):
        return None
    return {"id": job.get("id", "job-1"), "state": job.get("state", "interrupted"),
            "updated": job.get("updated"), "stale": bool(job.get("stale", False))}


def _outcome(stage: str | None, request_kind: str | None, needs_input: bool, handoff_path: str | None) -> str:
    if stage == "clarify" or needs_input or request_kind == "CLARIFY" or handoff_path == "clarify":
        return "clarify"
    if stage in {"state", "fast"} or request_kind == "CAPABILITY":
        return "action"
    if request_kind == "CHAT":
        return "chat"
    if request_kind == "CONTEXT_CONTROL":
        return "context_control"
    return "unknown"


def _ref_summary(refs: Iterable[Any]) -> list[str]:
    return sorted(f"{ref.kind}:{ref.source}:{ref.id}" for ref in refs)


def _goal_question(entry: Any) -> str:
    """Brain's verdict if this utterance arrived while a goal waited for an answer."""
    from modules import brain_entry
    with brain_entry.bind(entry):
        return "new_request" if brain_entry.goal_question_superseded() else "answer"


def run_scenario(scenario: Mapping[str, Any], *, owner: str = OWNER) -> dict:
    """Bir senaryoyu yalıtılmış canonical Brain akışından geçirip kararını döndürür."""
    from modules import brain_candidates, brain_context, brain_entry

    setup = dict(scenario.get("setup") or {})
    text = scenario["text"]
    request_id = "acc-" + hashlib.sha1(scenario["id"].encode("utf-8")).hexdigest()[:12]
    source = scenario.get("source", "yazı")
    failures: list[str] = []
    history = _history_rows(setup, owner)
    goal = setup.get("goal") if isinstance(setup.get("goal"), Mapping) else None
    files = [dict(row) for row in setup.get("files") or ()]
    original_context = brain_context.build_active_context
    original_candidates = brain_candidates.build_candidates

    def context(**kwargs):
        kwargs.setdefault("history_reader", lambda _owner, *, limit: history[-limit:])
        kwargs.setdefault("history_filter", lambda _owner, rows: rows)
        kwargs.setdefault("goal_reader", lambda _owner: dict(goal, owner=owner) if goal else None)
        kwargs.setdefault("goal_is_open", lambda row: str(row.get("state") or "") not in _GOAL_CLOSED)
        return original_context(**kwargs)

    def candidates(**kwargs):
        kwargs["file_reader"] = lambda *, limit: files[:limit]
        return original_candidates(**kwargs)

    def record(site: str) -> None:
        failures.append(site)

    handler_calls: list[str] = []
    dispatch_calls: list[tuple[str, str]] = []

    def handler(command: str):
        handler_calls.append(command)
        return _HANDLER_OUTPUT

    def dispatch(_runtime, intent, _args, command, _low):
        dispatch_calls.append((str(intent), command))
        return _DISPATCH_OUTPUT

    runtime = _runtime(setup, owner)
    with ExitStack() as stack:
        stack.enter_context(patch.object(brain_context, "build_active_context", context))
        stack.enter_context(patch.object(brain_entry, "build_candidates", candidates))
        for module in (brain_entry, brain_context, brain_candidates):
            if hasattr(module, "_record_failure"):
                stack.enter_context(patch.object(module, "_record_failure", record))
        stack.enter_context(patch("modules.job_front.observe", lambda _owner: _job(setup)))
        stack.enter_context(patch("modules.desktop_agent._load", lambda _owner: setup.get("desktop")))
        stack.enter_context(patch("modules.engine_intents.dispatch", dispatch))
        # Legacy front-gate precedence (macro/user/planner/...) is pinned by tests/test_brain_b3a.py;
        # the harness measures the Brain decision on an isolated stub runtime.
        stack.enter_context(patch("modules.brain_precedence.claim", lambda *_a, **_k: None))
        # Core guard'ları global modülleri sarmalar; ölçüm sırasında kurulmaz.
        stack.enter_context(patch.object(brain_entry, "_install_core_guards", lambda _runtime: None))
        stack.enter_context(patch.object(brain_entry, "_correlated_job_id", lambda _entry: None))
        entry = brain_entry.prepare(
            runtime, owner=owner, request_id=request_id, text=text, source=source,
            model_refinement=False,
        )
        proposal = brain_entry.core_proposal(entry)
        projection_fn = getattr(brain_entry, "_legacy_route_projection", None)
        projection = projection_fn(entry) if callable(projection_fn) else None
        output, brain_feedback, _job_id = brain_entry.handoff(runtime, entry, handler, text)

    semantic = entry.understanding
    question = brain_entry.clarification(entry)
    if question is not None and not handler_calls and not dispatch_calls:
        handoff_path = "clarify"
    elif handler_calls:
        handoff_path = "existing_handler"
    elif dispatch_calls:
        handoff_path = "chat_dispatch"
    else:
        handoff_path = "context_control"
    request_kind = semantic.request_kind.value if semantic is not None else None
    needs_input = bool(semantic.needs_input) if semantic is not None else entry.stage == "clarify"
    protocol = proposal.get("protocol")
    decision = {
        "outcome": _outcome(entry.stage, request_kind, needs_input, handoff_path),
        "stage": entry.stage,
        "protocol": protocol,
        "request_kind": request_kind,
        "capability_hint": proposal.get("capability_hint"),
        "manifest_capability_id": proposal.get("manifest_capability_id"),
        "conversation_relation": semantic.conversation_relation.value if semantic is not None else None,
        "needs_input": needs_input,
        "temporal_need": semantic.temporal_need.value if semantic is not None else None,
        "handoff_path": handoff_path,
        "legacy_projection_intent": projection.get("intent") if isinstance(projection, Mapping) else None,
        "goal_question": _goal_question(entry),
    }
    gate = entry.state_gate if entry.state_gate.matched else entry.fast_gate
    info = {
        "selection": gate.selection if gate is not None and gate.matched else None,
        "state_reason": entry.state_gate.reason_code,
        "fast_reason": entry.fast_gate.reason_code if entry.fast_gate is not None else None,
        "confidence": semantic.confidence.value if semantic is not None else None,
        "ambiguities": list(semantic.ambiguities) if semantic is not None else [],
        "reason_codes": list(semantic.reason_codes) if semantic is not None else [],
        "references": _ref_summary(entry.references),
        "context_last_property": next((ref.provenance.get("value") for ref in entry.active_context.recent_references
                                       if ref.id == "last_property"), None),
        "candidate_count": len(entry.candidates),
        "clarification": output if handoff_path in {"clarify", "context_control"} else None,
        "dispatch_intents": [intent for intent, _ in dispatch_calls],
        "feedback": brain_feedback.to_dict(),
        "failures": sorted(set(failures)),
    }
    return {"decision": decision, "info": info}


def _safe_run(scenario: Mapping[str, Any], runner: Callable[[Mapping[str, Any]], dict]) -> dict:
    try:
        return runner(scenario)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def _git_head() -> str | None:
    try:
        cp = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout.strip() or None if cp.returncode == 0 else None


def capture(pool: list[dict], *, runner: Callable[[Mapping[str, Any]], dict] = run_scenario) -> dict:
    results = {}
    for scenario in pool:
        row = _safe_run(scenario, runner)
        row["group"] = scenario.get("group", "kritik")
        row["text"] = scenario["text"]
        results[scenario["id"]] = row
    return {
        "format_version": FORMAT_VERSION,
        "git_head": _git_head(),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenario_count": len(results),
        "results": results,
    }


# --------------------------------------------------------------------------- karşılaştırma

def _accepts(expected: Any, value: Any) -> bool:
    return value in expected if isinstance(expected, list) else value == expected


def criteria_status(scenario: Mapping[str, Any], decision: Mapping[str, Any] | None) -> dict[str, bool]:
    """Her expect/forbid kriteri için sağlandı mı (karar yoksa hepsi False)."""
    status: dict[str, bool] = {}
    for key, expected in dict(scenario.get("expect") or {}).items():
        status["expect:" + key] = decision is not None and _accepts(expected, decision.get(key))
    for key, forbidden in dict(scenario.get("forbid") or {}).items():
        status["forbid:" + key] = decision is not None and not _accepts(forbidden, decision.get(key))
    return status


def verdict(scenario: Mapping[str, Any], base: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict:
    cur_decision = current.get("decision")
    if "error" in current:
        same_error = base is not None and base.get("error") == current["error"]
        return {"verdict": "same" if same_error else "error", "error": current["error"]}
    if base is None:
        return {"verdict": "new"}
    base_decision = base.get("decision")
    if base_decision == cur_decision:
        return {"verdict": "same"}
    if isinstance(base_decision, Mapping) and isinstance(cur_decision, Mapping) \
            and base_decision == {k: cur_decision.get(k) for k in base_decision}:
        return {"verdict": "same"}  # keys added after the baseline was captured do not count as change
    base_status = criteria_status(scenario, base_decision)
    cur_status = criteria_status(scenario, cur_decision)
    lost = sorted(k for k, ok in base_status.items() if ok and not cur_status.get(k))
    gained = sorted(k for k, ok in cur_status.items() if ok and not base_status.get(k))
    diff = {k: {"baseline": (base_decision or {}).get(k), "current": cur_decision.get(k)}
            for k in DECISION_KEYS if (base_decision or {}).get(k) != cur_decision.get(k)}
    if lost:
        result = "regression"
    elif gained:
        result = "better"
    else:
        result = "changed"
    return {"verdict": result, "lost": lost, "gained": gained, "diff": diff}


def _accepted_diff_fingerprint(rows: Mapping[str, Mapping[str, Any]], accepted_ids: Iterable[str]) -> str:
    """Canlı accepted kararlarının exact diff kümesini kararlı biçimde mühürler."""
    payload = {
        ident: rows[ident].get("diff", {})
        for ident in sorted(accepted_ids)
        if rows.get(ident, {}).get("verdict") == "accepted"
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _default_acceptance_fingerprint(accepted: Mapping[str, str]) -> str | None:
    """Yalnız repo'daki varsayılan canlı izin kümesi fingerprint zorunluluğu taşır.

    ``--accept`` geçici reviewer dosyasıdır; kalıcı kapı DEFAULT_ACCEPTED ile çalışır. Doğrudan
    unit testlerde kullanılan sentetik kabul haritaları bu disk sözleşmesine bağlanmaz.
    """
    if not accepted or not DEFAULT_ACCEPTED.is_file():
        return None
    try:
        committed = json.loads(DEFAULT_ACCEPTED.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    if dict(accepted) != dict(committed):
        return None
    try:
        return DEFAULT_ACCEPTED_FINGERPRINT.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def compare(pool: list[dict], baseline: Mapping[str, Any], current: Mapping[str, Any],
            accepted: Mapping[str, str] | None = None) -> dict:
    accepted = dict(accepted or {})
    base_rows = dict(baseline.get("results") or {})
    cur_rows = dict(current.get("results") or {})
    by_id = {row["id"]: row for row in pool}
    rows: dict[str, dict] = {}
    for ident, scenario in by_id.items():
        row = verdict(scenario, base_rows.get(ident), cur_rows[ident])
        if row["verdict"] == "changed" and ident in accepted:
            row["verdict"] = "accepted"
            row["reason"] = accepted[ident]
        rows[ident] = row
    for ident in base_rows:
        if ident not in by_id:
            rows[ident] = {"verdict": "missing"}
    counts: dict[str, int] = {}
    for row in rows.values():
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    expectation = {"baseline": 0, "current": 0, "with_criteria": 0}
    for ident, scenario in by_id.items():
        if not (scenario.get("expect") or scenario.get("forbid")):
            continue
        expectation["with_criteria"] += 1
        base_status = criteria_status(scenario, (base_rows.get(ident) or {}).get("decision"))
        cur_status = criteria_status(scenario, cur_rows[ident].get("decision"))
        expectation["baseline"] += int(bool(base_status) and all(base_status.values()))
        expectation["current"] += int(bool(cur_status) and all(cur_status.values()))
    failing = sorted(i for i, r in rows.items() if r["verdict"] in FAILING_VERDICTS)
    # Ölü izin: kabul yazılı olduğu hâlde bu koşuda ``changed`` üretmeyen id. Havuzdan çıkmış
    # ya da artık aynı/better olan karar için izin bırakılamaz; izin ile değişiklik eş olmalı.
    dead = sorted(i for i in accepted if rows.get(i, {}).get("verdict") != "accepted")
    actual_fingerprint = _accepted_diff_fingerprint(rows, accepted)
    expected_fingerprint = _default_acceptance_fingerprint(accepted)
    fingerprint_match = expected_fingerprint is None or (
        bool(expected_fingerprint) and actual_fingerprint == expected_fingerprint
    )
    return {
        "passed": not failing and not dead and fingerprint_match,
        "counts": dict(sorted(counts.items())),
        "expectations_met": expectation,
        "failing": failing,
        "dead_permits": dead,
        "accepted_diff_fingerprint": actual_fingerprint,
        "accepted_diff_fingerprint_expected": expected_fingerprint,
        "accepted_diff_fingerprint_match": fingerprint_match,
        "rows": rows,
        "baseline_head": baseline.get("git_head"),
        "current_head": current.get("git_head"),
        "scenario_count": len(pool),
        "baseline_scenario_count": len(base_rows),
    }


# --------------------------------------------------------------------------- 160 audit matrisi

_SECTION = re.compile(r"^##\s+([A-Z])\s+[—-]\s+(.+?)\s+[—-]\s+(\d+)\s*[–-]\s*(\d+)\s*$")
_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.+)\|\s*$")
_MAPPING = re.compile(r"^Eşleme:\s*(.+?)\.?\s*(?:Kaynak:.*)?$")
MATRIX_KEEP = ("girdi", "setup", "source", "expect", "forbid", "katman", "not")


def parse_audit_matrix(text: str) -> list[dict]:
    """Audit metnindeki "ADVERSARIAL ... ACCEPTANCE SCENARIOS" tablolarını satır satır okur.

    Beklenen davranış metni olduğu gibi korunur; kriter üretilmez. Bölüm altındaki
    ``Eşleme:`` satırı, tabloda eşleme sütunu olmayan satırlara uygulanır.
    """
    rows: list[dict] = []
    section: tuple[str, str] | None = None
    pending: list[dict] = []

    def flush(mapping: str | None) -> None:
        for row in pending:
            row.setdefault("esleme", mapping)
        pending.clear()

    for line in text.splitlines():
        line = line.strip()
        head = _SECTION.match(line)
        if head:
            flush(None)
            section = (head.group(1), head.group(2).strip())
            continue
        mapping = _MAPPING.match(line)
        if mapping and pending:
            flush(mapping.group(1).strip())
            continue
        if line.startswith("#"):
            flush(None)
            section = None if not line.startswith("##") else section
            continue
        cells = _ROW.match(line)
        if section is None or not cells:
            continue
        parts = [part.strip() for part in cells.group(2).split("|")]
        row = {
            "no": int(cells.group(1)),
            "kategori": f"{section[0]} — {section[1]}",
            "senaryo": parts[0],
            "beklenen": parts[1] if len(parts) > 1 else "",
        }
        if len(parts) > 2 and parts[2]:
            row["esleme"] = parts[2]
        rows.append(row)
        pending.append(row)
    flush(None)
    numbers = [row["no"] for row in rows]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Audit matrisinde tekrarlanan senaryo numarası var.")
    return rows


_NUM_SECTION = re.compile(r"^###\s+(.+?)\s+[—-]\s+(\d+)\s*[–-]\s*(\d+)\s*$")
_NUM_ROW = re.compile(r"^(\d+)\.\s+(.+?)\s*$")


def parse_numbered_matrix(text: str) -> list[dict]:
    """PR10 cutover denetimindeki "### Bölüm — a–b" + "N. madde" listesini okur.

    Madde metni kabul edilecek özelliğin kendisidir; ``senaryo`` alanına aynen yazılır.
    Yalnız bölüm başlığındaki numara aralığına düşen maddeler alınır.
    """
    rows: list[dict] = []
    section: tuple[str, int, int] | None = None
    for line in text.splitlines():
        line = line.strip()
        head = _NUM_SECTION.match(line)
        if head:
            section = (head.group(1).strip(), int(head.group(2)), int(head.group(3)))
            continue
        if line.startswith("#"):
            section = None
            continue
        item = _NUM_ROW.match(line)
        if section is None or not item:
            continue
        number = int(item.group(1))
        if not section[1] <= number <= section[2]:
            continue
        rows.append({"no": number, "kategori": section[0], "senaryo": item.group(2)})
    numbers = [row["no"] for row in rows]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Matriste tekrarlanan madde numarası var.")
    return rows


PARSERS = {"audit": parse_audit_matrix, "pr10": parse_numbered_matrix}
_DESCRIPTIONS = {
    "audit": (
        "Çalışan 1 Resource/Stopping audit'inin 160 maddelik adversarial kabul matrisi "
        "(audit metni: 'yeni test implementation'ı değildir; kabul matrisi taslağıdır'). "
        "senaryo/beklenen/esleme metinden aynen alınır. Yalnız 'girdi' taşıyan satırlar "
        "canonical Brain harness'inde koşar; diğerleri 'katman'/'esleme'deki runtime/provider/worker "
        "testlerine aittir."
    ),
    "pr10": (
        "PR10 final legacy sweep / cutover ön denetiminin 'final cutover acceptance' 160 maddelik "
        "matrisi. Madde metni ('senaryo') aynen alınır. Yalnız 'girdi' taşıyan maddeler canonical "
        "Brain harness'inde koşar ve kriterleri madde metninden birebir türetilir; diğerleri "
        "'katman'daki unit/Core/statik testlere aittir. Denetimin durum ve blocker tabloları "
        "30 Ekim tarihlidir, buraya alınmadı."
    ),
}


def merge_matrix(parsed: list[dict], existing: Mapping[str, Any] | None, *, kind: str = "audit") -> dict:
    """Yeni ayrıştırılan satırlara eski dosyadaki elle eklenmiş girdi/setup/kriterleri taşır."""
    old = {row.get("no"): row for row in (existing or {}).get("senaryolar", [])}
    out = []
    for row in parsed:
        merged = dict(row)
        for key in MATRIX_KEEP:
            if key in old.get(row["no"], {}):
                merged[key] = old[row["no"]][key]
        out.append(merged)
    return {
        "aciklama": (existing or {}).get("aciklama") or _DESCRIPTIONS[kind],
        "kaynak": (existing or {}).get("kaynak"),
        "senaryolar": out,
    }


def matrix_scenarios(path: Path = MATRIX_POOL, prefix: str = "m160-") -> tuple[list[dict], list[dict]]:
    """Matristen (Brain'de koşan senaryolar, Brain harness'i dışında kalan satırlar)."""
    if not Path(path).is_file():
        return [], []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    runnable, outside = [], []
    for row in data.get("senaryolar", []):
        if not row.get("girdi"):
            outside.append(row)
            continue
        scenario = {
            "id": f"{prefix}{int(row['no']):03d}",
            "group": "matris_" + prefix.rstrip("-"),
            "text": row["girdi"],
            "meta": {k: row.get(k) for k in ("kategori", "senaryo", "beklenen", "esleme", "not") if row.get(k)},
        }
        for key in ("setup", "source", "expect", "forbid"):
            if row.get(key):
                scenario[key] = row[key]
        runnable.append(scenario)
    return runnable, outside


# --------------------------------------------------------------------------- CLI

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _write_baseline(path: Path, data: Mapping[str, Any]) -> None:
    """Her senaryo tek satır: baseline yeniden alındığında diff senaryo bazında okunur."""
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in data.items() if k != "results"}
    lines = ["{"]
    for key in sorted(head):
        lines.append(f" {json.dumps(key)}: {json.dumps(head[key], ensure_ascii=False)},")
    lines.append(' "results": {')
    rows = sorted(data.get("results", {}).items())
    for index, (ident, row) in enumerate(rows):
        comma = "," if index < len(rows) - 1 else ""
        lines.append(f"  {json.dumps(ident, ensure_ascii=False)}: "
                     f"{json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}{comma}")
    lines.append(" }")
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _isolate_data_dir() -> None:
    if not os.environ.get("JARVIS_DATA_DIR"):
        os.environ["JARVIS_DATA_DIR"] = tempfile.mkdtemp(prefix="jarvis-brain-acceptance-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "capture", "compare"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--pool", action="append", default=[], type=Path, help="Ek senaryo havuzu (JSON).")
        cmd.add_argument("--no-corpora", action="store_true", help="Yönlendirme/enjeksiyon korpuslarını katma.")
        if name == "capture":
            cmd.add_argument("--out", type=Path, default=DEFAULT_BASELINE)
        if name == "compare":
            cmd.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
            cmd.add_argument("--accept", type=Path, help="{id: gerekçe} bilinçli değişiklik listesi.")
            cmd.add_argument("--report", type=Path, help="Ayrıntılı raporu JSON olarak yaz.")
    imp = sub.add_parser("import", help="Audit metnindeki 160 maddelik matrisi havuz dosyasına aktar.")
    imp.add_argument("source", type=Path, help="Denetim metni (.md/.txt).")
    imp.add_argument("--format", choices=sorted(PARSERS), default="audit",
                     help="audit: resource/stopping tablo matrisi; pr10: cutover numaralı liste.")
    imp.add_argument("--out", type=Path, help="Varsayılan: biçime göre tests/data/brain_acceptance_matris_*.json")
    args = parser.parse_args(argv)
    if args.command == "import":
        out = args.out or (MATRIX_POOL if args.format == "audit" else PR10_MATRIX_POOL)
        parsed = PARSERS[args.format](args.source.read_text(encoding="utf-8"))
        existing = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
        _write_json(out, merge_matrix(parsed, existing, kind=args.format))
        args.out = out
        runnable, outside = matrix_scenarios(out, MATRICES.get(out, "m-"))
        print(f"Matris yazıldı: {args.out} ({len(parsed)} satır; Brain harness'inde {len(runnable)}, "
              f"harness dışı {len(outside)}).")
        return 0
    _isolate_data_dir()
    pool = load_pool(args.pool, include_corpora=not args.no_corpora)

    if args.command == "list":
        groups: dict[str, int] = {}
        for row in pool:
            groups[row.get("group", "kritik")] = groups.get(row.get("group", "kritik"), 0) + 1
        outside_report = {}
        for path, prefix in MATRICES.items():
            outside = matrix_scenarios(path, prefix)[1]
            layers: dict[str, int] = {}
            for row in outside:
                layer = row.get("katman") or row.get("esleme") or "?"
                layers[layer] = layers.get(layer, 0) + 1
            outside_report[path.name] = {"harness_disi": len(outside), "katman": layers}
        print(json.dumps({"toplam": len(pool), "gruplar": groups, "matrisler": outside_report},
                         ensure_ascii=False, indent=1))
        return 0

    current = capture(pool)
    if args.command == "capture":
        _write_baseline(args.out, current)
        errors = sum(1 for row in current["results"].values() if "error" in row)
        print(f"Baseline yazıldı: {args.out} ({current['scenario_count']} senaryo, {errors} hata)")
        return 0

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    # Gerekçeli kabul izinleri repo'daki kabul dosyasındadır; --accept yalnız geçici gözden geçirme içindir.
    accept_path = args.accept or (DEFAULT_ACCEPTED if DEFAULT_ACCEPTED.is_file() else None)
    accepted = json.loads(accept_path.read_text(encoding="utf-8")) if accept_path else {}
    report = compare(pool, baseline, current, accepted)
    if args.report:
        _write_json(args.report, report)
    keys = ("passed", "counts", "expectations_met", "scenario_count", "baseline_scenario_count",
            "dead_permits", "accepted_diff_fingerprint_match")
    print(json.dumps({k: report[k] for k in keys}, ensure_ascii=False, indent=1))
    if report["scenario_count"] < report["baseline_scenario_count"]:
        print(f"Havuz daraldı: baseline {report['baseline_scenario_count']} → {report['scenario_count']} "
              "senaryo. Kabul için senaryo sayısı hiç azalmamalı.")
        return 1
    if report["accepted_diff_fingerprint_match"] is False:
        expected = report["accepted_diff_fingerprint_expected"] or "<missing>"
        actual = report["accepted_diff_fingerprint"]
        print(f"Accepted diff fingerprint drift: expected {expected}, current {actual}")
    for ident in report["dead_permits"][:20]:
        print(f"  dead_permit {ident} gerekçesi kabul dosyasında duruyor ama bu koşuda changed üretmedi.")
    for ident in report["failing"][:50]:
        row = report["rows"][ident]
        print(f"  {row['verdict']:10} {ident} {json.dumps(row.get('diff') or row.get('error') or '', ensure_ascii=False)}")
    print("Kapı: GEÇTİ (aynı veya daha iyi)." if report["passed"] else "Kapı: KALDI.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
