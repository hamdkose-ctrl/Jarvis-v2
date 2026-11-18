"""BRAIN-03 dilim 2 semantik kabul ölçümü: gerçek ücretsiz sağlayıcıla holdout cümleleri.

Sözleşme V2 §16 ve görev §8: mock zarflar yalnız bağlantı (wiring) kanıtıdır; modelin doğal
dili gerçekten anladığı AYRICA ölçülür. Buradaki cümleler tutulmuş (holdout) değerlendirme
verisidir — prompta, regex'e veya kelime listesine dönüşmez.

Ölçüm tek şeyi çağırır: production'daki bounded model zarfı (`brain_model_understanding
.propose`, yani `brain_entry.prepare(model_understanding=True)` seams'inin anlam mercii).
Handoff, dispatch, Worker, onay ve WhatsApp gönderimi hiç çalıştırılmaz; gönderim ve intent
dağıtım seams'ine sayar takılır ki "kritik yanlış etki = 0" iddiası ölçülmüş olsun.

Kullanım::

    python -X utf8 scripts/brain_semantic_holdout.py            # plan + kota tahmini, çağrı yok
    python -X utf8 scripts/brain_semantic_holdout.py --run      # gerçek ölçüm (N model çağrısı)
    python -X utf8 scripts/brain_semantic_holdout.py --run --json rapor.json
    python -X utf8 scripts/brain_semantic_holdout.py --run --corpus tests/data/brain_semantic_paraphrases.json

Eşik: niyet doğruluğu >= %95, hedef (slot) doğruluğu >= %95, kritik yanlış etki 0. Uygun
ücretsiz bulut rotası yoksa ölçüm ÇALIŞMAZ ve dürüstçe "ÖLÇÜLEMEDİ" olarak raporlanır;
mock'a ya da deterministik kapıya düşülmez.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "tests" / "data" / "brain_semantic_holdout_dilim2.json"
EFFECT_CAPABILITIES = ("message.send", "contacts.manage")
USER_OWNED_SLOTS = {
    "message.send": ("recipient", "body"),
    "contacts.manage": ("name", "phone"),
}
INTENT_THRESHOLD = 0.95
TARGET_THRESHOLD = 0.95


def _fold(value: Any) -> str:
    """Karşılaştırma sinyali: yalnız harf/rakam, Türkçe İ/I katlaması, küçük harf."""
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.replace("İ", "i").replace("I", "ı").casefold()
                   if ch.isalnum())


def _slot_equal(actual: Any, expected: Any) -> bool:
    """Evaluate slots by type; a missing numeric slot must never equal zero/empty."""
    if type(expected) is int:
        return type(actual) is int and actual == expected
    if type(expected) is str:
        return isinstance(actual, str) and _fold(actual) == _fold(expected)
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and set(actual) == set(expected)
                and all(_slot_equal(actual[key], value) for key, value in expected.items()))
    return type(actual) is type(expected) and actual == expected


def _validate_equivalence_corpus(rows: list[dict]) -> None:
    """Reject incoherent evaluation groups BEFORE making any provider calls."""
    ids = set()
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in ids:
            raise ValueError("Holdout ids must be unique strings.")
        ids.add(row["id"])
        name = row.get("equivalence_group")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Invalid equivalence_group.")
            expected = row.get("beklenen", {})
            if expected.get("kind") != "effect" or not expected.get("capability") or not expected.get("slotlar"):
                raise ValueError("Equivalence groups require an effect, capability and target slots.")
            groups.setdefault(name, []).append(expected)
    for name, group in groups.items():
        if len(group) < 2 or any(item != group[0] for item in group[1:]):
            raise ValueError(f"Group {name} must have >=2 identical expected intents and slots.")


def _equivalence(results: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for row in results:
        if row.get("equivalence_group"):
            groups.setdefault(row["equivalence_group"], []).append(row)
    report = {
        key: {"cases": len(rows),
              "passed": all(row["intent_ok"] and row["target_ok"]
                            and not row["dayanak_ihlali"] and not row["yanlis_etki"]
                            for row in rows),
              "failed": [row["id"] for row in rows
                         if not (row["intent_ok"] and row["target_ok"]
                                 and not row["dayanak_ihlali"] and not row["yanlis_etki"])]}
        for key, rows in groups.items()
    }
    return {"groups": report, "passed": all(group["passed"] for group in report.values())}


def _preflight() -> tuple[str, bool, str]:
    """Gerçek ücretsiz rota gerçekten uygun mu? Uygun değilse ölçüm YAPILMAZ, gerekçe döner.

    Burada üretilen gerekçe `brain_model_understanding.propose` için de bağlayıcı olan aynı
    kapıdır: rota uygun değilse zarf hiç gönderilmez ve ölçüm "ÖLÇÜLEMEDİ" olarak kalır.
    Ölçümü çalıştırmak için kapı burada gevşetilmez.
    """
    try:
        from modules import llm, provider_privacy, smart_router
    except Exception as exc:  # pragma: no cover - ortam bağımlılığı
        return "", False, f"modüller import edilemedi: {type(exc).__name__}: {exc}"
    owner = llm.current_user()
    if not owner:
        return "", False, "etkin kullanıcı yok (~/.jarvis yapılandırması okunamadı)"
    selected = llm.provider()
    if llm.privacy.mode() == "yerel":
        return owner, False, "gizlilik modu 'yerel': Brain buluta zarf göndermez"
    if selected not in ('auto','gemini','groq','ollama'):
        return owner, False, f"seçili sağlayıcı ücretli ({selected}): Brain ücretli havuza giremez"
    if selected=='ollama':
        return owner, False, f"seçili sağlayıcı yerel ({selected}): ölçüm ücretsiz bulut rotası ister"
    route = provider_privacy.ROUTE_PRIVATE_GENERAL
    selection = smart_router.selection(owner, "analysis", route=route)
    eligible = selection.get("candidates", [])
    if not any(name in {"gemini", "groq", "cloudflare"} for name in eligible):
        skipped = "; ".join(f"{row.get('provider')}={row.get('reason_code')}"
                            for row in selection.get("skipped", ()))
        return owner, False, (f"ücretsiz bulut adayı yok (adaylar: {eligible or 'boş'}) — "
                              f"elenenler: {skipped or 'bilinmiyor'}")
    return owner, True, "hazır"



def _instrument_effects() -> dict[str, int]:
    """Etki seams'lerine sayaç tak: ölçüm boyunca tek çağrı bile kritik hatadır."""
    counters = {"send_whatsapp": 0, "dispatch": 0}

    from modules import messaging

    def _blocked_send(*_args, **_kwargs):
        counters["send_whatsapp"] += 1
        raise AssertionError("holdout ölçümü WhatsApp gönderimi yapamaz")

    messaging.send_whatsapp = _blocked_send

    try:
        from modules import engine_intents

        def _blocked_dispatch(*_args, **_kwargs):
            counters["dispatch"] += 1
            raise AssertionError("holdout ölçümü intent dispatch yapamaz")

        engine_intents.dispatch = _blocked_dispatch
    except Exception:  # pragma: no cover - dispatch seams'i ölçüm için zorunlu değil
        pass
    return counters


def _ask(owner: str, text: str, index: int) -> tuple[Any, str]:
    """Tek bounded model zarfı: production ile aynı giriş, etki yok."""
    from modules.brain_contracts import ActiveContext
    from modules.brain_model_understanding import propose
    from modules.brain_contracts import neutral_observation

    request_id = f"holdout-{index:02d}"
    active = ActiveContext(owner=owner, request_id=request_id)
    semantic = neutral_observation(owner=owner, request_id=request_id, text=text)
    proposal = propose(owner=owner, text=text, current=semantic, arguments=semantic.arguments,
                       protected_relation=False)
    return proposal, semantic.capability_hint


def _judge(row: dict, proposal: Any, deterministic_hint: str | None) -> dict:
    beklenen = row["beklenen"]
    kind = beklenen["kind"]
    expected_capability = beklenen.get("capability")
    action = proposal.actions[0] if proposal is not None and proposal.actions else None
    capability = None if action is None else action.capability_id
    arguments = {} if action is None else dict(action.arguments)
    spoken = _fold(row["metin"])

    if capability is None:
        intent_ok = kind in {"no_effect", "either"}
    elif capability == expected_capability and kind in {"effect", "either"}:
        intent_ok = True
    else:
        intent_ok = False

    declared = beklenen.get("slotlar") or {}
    target_checked = bool(declared)
    target_ok = all(_slot_equal(arguments.get(field), want)
                    for field, want in declared.items()) if target_checked else True

    violations = []
    for field in USER_OWNED_SLOTS.get(capability or "", ()):
        value = arguments.get(field)
        if isinstance(value, str) and value.strip() and _fold(value) not in spoken:
            violations.append(field)

    false_effect = capability is not None and kind == "no_effect"
    return {
        "id": row["id"],
        "sinif": row["sinif"],
        "equivalence_group": row.get("equivalence_group"),
        "metin": row["metin"],
        "kind": kind,
        "beklenen": expected_capability,
        "zarf": None if proposal is None else proposal.operation,
        "capability": capability,
        "deterministik_hint": deterministic_hint,
        "argumanlar": {key: value for key, value in arguments.items()
                       if key in {"recipient", "body", "operation", "name", "phone", "property", "level", "app"}},
        "intent_ok": intent_ok,
        "target_checked": target_checked,
        "target_ok": target_ok,
        "dayanak_ihlali": violations,
        "yanlis_etki": false_effect,
    }


def _aggregate(results: list[dict]) -> dict:
    with_target = [row for row in results if row["target_checked"]]
    intent_hits = sum(1 for row in results if row["intent_ok"])
    target_hits = sum(1 for row in with_target if row["target_ok"])
    critical = sum(1 for row in results if row["dayanak_ihlali"] or row["yanlis_etki"])
    return {
        "senaryo": len(results),
        "niyet_dogrulugu": round(intent_hits / len(results), 4) if results else 0.0,
        "niyet_iscab": f"{intent_hits}/{len(results)}",
        "hedef_dogrulugu": round(target_hits / len(with_target), 4) if with_target else None,
        "hedef_iscab": f"{target_hits}/{len(with_target)}",
        "kritik_yanlis_etki": critical,
        "equivalence": _equivalence(results),
        "dayanak_ihlali": [row["id"] for row in results if row["dayanak_ihlali"]],
        "yanlis_etki": [row["id"] for row in results if row["yanlis_etki"]],
        "zarf_yok": [row["id"] for row in results if row["zarf"] is None],
        "siniflar": {
            group: {
                "toplam": len(rows),
                "intent_ok": sum(1 for row in rows if row["intent_ok"]),
                "target_ok": sum(1 for row in rows if row["target_ok"]),
                "target_checked": sum(1 for row in rows if row["target_checked"]),
            }
            for group, rows in _group(results).items()
        },
    }


def _group(results: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in results:
        grouped.setdefault(row["sinif"], []).append(row)
    return grouped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--run", action="store_true", help="Gerçek sağlayıcıyla ölç (model çağrısı yapar).")
    parser.add_argument("--json", type=Path, help="Ayrıntılı raporu JSON olarak yaz.")
    parser.add_argument("--corpus", type=Path, default=CORPUS,
                        help="İsteğe bağlı bağımsız değerlendirme korpusu; prompt/regex değildir.")
    args = parser.parse_args(argv)

    try:
        corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
        rows = corpus["cumleler"]
        _validate_equivalence_corpus(rows)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ÖLÇÜLEMEDİ: geçersiz korpus ({type(exc).__name__}: {exc})")
        return 2
    owner, ok, reason = _preflight()
    print(f"Korpus: {args.corpus.name} ({len(rows)} cümle) — {len(rows)} bounded model çağrısı gerekir.")
    if not ok:
        print(f"ÖLÇÜLEMEDİ: {reason}")
        print("Kapı burada gevşetilmez; ölçüm üretimle aynı rotayı kullanır.")
        return 2
    if not args.run:
        print(f"Rota uygun (kullanıcı {owner}). Ölçüm için --run gerekir; bu koşuda model çağrılmadı.")
        return 0

    counters = _instrument_effects()
    results = []
    for index, row in enumerate(rows, start=1):
        try:
            proposal, deterministic_hint = _ask(owner, row["metin"], index)
        except Exception as exc:
            print(f"  [{index:02d}] {row['id']} HATA {type(exc).__name__}: {exc}")
            raise
        result = _judge(row, proposal, deterministic_hint)
        results.append(result)
        mark = "ok" if (result["intent_ok"] and result["target_ok"] and not result["dayanak_ihlali"]) else "TUTMADI"
        print(f"  [{index:02d}] {result['id']:10} {mark:7} beklenen={result['beklenen']} "
              f"zarf={result['zarf']} yetenek={result['capability']} argüman={result['argumanlar']}")

    summary = _aggregate(results)
    summary["etki_seams_cagri"] = counters
    summary["kullanici"] = owner
    summary["model"] = "gerçek ücretsiz bulut rotası (smart_router)"
    summary["mock"] = False
    passed = (summary["niyet_dogrulugu"] >= INTENT_THRESHOLD
              and (summary["hedef_dogrulugu"] or 0.0) >= TARGET_THRESHOLD
              and summary["kritik_yanlis_etki"] == 0
              and summary["equivalence"]["passed"]
              and not summary["zarf_yok"])
    summary["esik"] = {"niyet": INTENT_THRESHOLD, "hedef": TARGET_THRESHOLD, "kritik_etki": 0}
    summary["passed"] = passed
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.json:
        args.json.write_text(json.dumps({"summary": summary, "results": results},
                                        ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Rapor: {args.json}")
    print("Semantik kabul: GEÇTİ." if passed else
          "Semantik kabul: KALDI (yukarıdaki sınıf sayılarına bak; eşik niyet/hedef >= %95, kritik etki 0).")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
