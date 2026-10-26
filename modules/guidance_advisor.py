"""Structured practical guidance; independent from Hoca mode."""
from __future__ import annotations

import re


_REQUEST = re.compile(
    r"\b(?:adım\s+adım|adim\s+adim|rehber|yol\s+göster|yol\s+goster|"
    r"nasıl\s+(?:yap|başla|basla|ilerle)|ne\s+yapmalıyım|ne\s+yapmalıyim)\b",
    re.I,
)


def requested(text: str) -> bool:
    return isinstance(text, str) and bool(_REQUEST.search(text))


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} boş olamaz.")
    return value.strip()


def _list(value, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} listesi geçersiz.")
    return [item.strip() for item in value]


def guide(request: str, *, objective: str, steps: list[dict]) -> dict | None:
    if not requested(request):
        return None
    objective = _text(objective, "Hedef")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Rehber en az bir adım içermeli.")
    output = []
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise ValueError("Rehber adımı nesne olmalı.")
        output.append({
            "order": index,
            "action": _text(step.get("action"), "Eylem"),
            "why": _text(step.get("why"), "Neden"),
            "risks": _list(step.get("risks", []), "Risk"),
            "watchouts": _list(step.get("watchouts", []), "Dikkat"),
        })
    return {
        "schema": "guidance.v1",
        "objective": objective,
        "steps": output,
    }


def render(result: dict) -> str:
    if not isinstance(result, dict) or result.get("schema") != "guidance.v1":
        raise ValueError("Rehber şeması geçersiz.")
    lines = ["Uygulama rehberi: " + result["objective"]]
    for step in result["steps"]:
        lines.append(f"\n{step['order']}. {step['action']}")
        lines.append("Neden: " + step["why"])
        lines.append("Riskler: " + (", ".join(step["risks"]) or "Belirgin risk yok."))
        lines.append("Dikkat: " + (", ".join(step["watchouts"]) or "Özel dikkat noktası yok."))
    return "\n".join(lines)
