"""Bellek kapısı (A7): ne hatırlanır, ne özetlenir, ne unutulur.

Kullanıcı kararı: "bunu kaydet / bunu yap" gibi komutlar tahmin edilmeden
çözülmeli; geçmiş sınırsız büyümemeli. Bu modül karar verir, yazma sahibi değildir.

Kurallar:
- Sınır: `MAX_TURNS` tur / `MAX_CHARS` karakter.
- Sınır aşılırsa **özetle**: eski turlar özete iner, son `SUMMARY_KEEP` tur ham kalır.
- Sabitlenen bilgi (`remember`) **hiç düşmez**.
- Gönderme ("bunu") yalnız **son adımda gerçekten olan** hedefe çözülür; yoksa `None`.
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.diagnostics import record_failure as _record_failure

MAX_TURNS = 40
MAX_CHARS = 12_000
SUMMARY_KEEP = 12
PIN_FILE = Path.home() / ".jarvis" / "bellek" / "sabitler.json"


def plan(history: list[dict]) -> dict:
    """Geçmiş için karar: keep | summarize."""
    turns = [item for item in history if isinstance(item, dict)]
    chars = sum(len(str(item.get("text") or "")) for item in turns)
    if len(turns) <= MAX_TURNS and chars <= MAX_CHARS:
        return {"action": "keep", "drop": 0, "keep": len(turns), "chars": chars}
    older = turns[: max(0, len(turns) - SUMMARY_KEEP)]
    return {"action": "summarize", "drop": len(older), "keep": min(len(turns), SUMMARY_KEEP),
            "chars": chars, "summary_source": older}


def summary_text(older: list[dict], limit: int = 6) -> str:
    """Özetlenecek turlardan kısa, dürüst bir özet satırı üretir."""
    lines = []
    for item in older[-limit:]:
        text = " ".join(str(item.get("text") or "").split())
        if text:
            lines.append(text[:120])
    return "Önceki konuşma: " + " | ".join(lines) if lines else ""


def resolve_reference(text: str, last_action: dict | None) -> dict | None:
    """"bunu/şunu" ile geri gönderme: yalnız son gerçek adımın hedefi."""
    folded = " ".join(str(text or "").casefold().split())
    if not any(word in folded for word in ("bunu", "şunu", "sunu", "onu")):
        return None
    if not last_action or not last_action.get("target"):
        return None
    return {"target": last_action["target"], "kind": last_action.get("kind") or "action",
            "window": last_action.get("window") or ""}


LAST_FILE = Path.home() / ".jarvis" / "bellek" / "son-adim.json"


def record_action(capability: str, args: dict, result: dict | None = None) -> dict:
    """Gerçekleşmiş son adımı yazar; "bunu/şunu" yalnız buna çözülür."""
    step = {"kind": str(capability or ""),
            "target": str((args or {}).get("target") or (args or {}).get("name")
                          or (args or {}).get("text") or (args or {}).get("path") or ""),
            "window": str((args or {}).get("window") or ""),
            "status": str((result or {}).get("status") or "done")}
    try:
        LAST_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_FILE.write_text(json.dumps(step, ensure_ascii=False), encoding="utf-8")
    except OSError:
        _record_failure("modules/memory_gate.py:record_action")
    return step


def last_action() -> dict | None:
    try:
        step = json.loads(LAST_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        _record_failure("modules/memory_gate.py:last_action")
        return None
    return step if isinstance(step, dict) and step.get("target") else None


def summarise_history(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Kalıcı geçmişi sınırlar: aşılırsa eskiler tek özet satırına iner."""
    turns = [{"text": text, "role": role} for role, text in items]
    karar = plan(turns)
    if karar["action"] == "keep":
        return list(items)
    older = karar["summary_source"]
    keep_count = max(0, len(items) - len(older))
    summary = summary_text(older)
    kept = list(items[-keep_count:]) if keep_count else []
    return ([("assistant", summary)] if summary else []) + kept


def remember(key: str, value: str) -> dict:
    items = _load()
    items[str(key)] = str(value)
    _save(items)
    return {"status": "done", "text": f"Not aldım: {key} = {value}"}


def forget(key: str) -> dict:
    items = _load()
    if items.pop(str(key), None) is None:
        return {"status": "missing", "text": f"“{key}” diye bir notum yok."}
    _save(items)
    return {"status": "done", "text": f"“{key}” notunu sildim."}


def pinned() -> dict:
    return _load()


def _load() -> dict:
    try:
        return json.loads(PIN_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        _record_failure("modules/memory_gate.py:_load")
        return {}


def _save(items: dict) -> None:
    PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PIN_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
