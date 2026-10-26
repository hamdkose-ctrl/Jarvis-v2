"""Deterministic plus/minus decision analysis."""
from __future__ import annotations


def analyze(options: list[dict]) -> dict:
    if not isinstance(options, list) or not 1 <= len(options) <= 8:
        raise ValueError("En az bir, en fazla sekiz seçenek gerekli.")
    normalized = []
    for option in options:
        if not isinstance(option, dict) or not isinstance(option.get("name"), str) or not option["name"].strip():
            raise ValueError("Seçenek adı gerekli.")
        pros = option.get("pros")
        cons = option.get("cons")
        if not isinstance(pros, list) or not isinstance(cons, list) or not pros and not cons:
            raise ValueError("Her seçeneğin artı veya eksi gerekçesi olmalı.")
        if any(not isinstance(item, str) or not item.strip() for item in [*pros, *cons]):
            raise ValueError("Artı/eksi maddeleri metin olmalı.")
        score = len(pros) - len(cons)
        normalized.append({"name": option["name"].strip(), "pros": list(pros), "cons": list(cons), "score": score})
    best = max(normalized, key=lambda item: (item["score"], -len(item["cons"]), item["name"]))
    return {
        "options": normalized,
        "recommendation": best["name"],
        "reason": f"{best['name']} seçeneği, artı/eksi dengesi ve belirtilen riskler açısından en güçlü seçenek; bu gerekçe sınırlı girdiye dayanır.",
    }
