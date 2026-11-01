"""Structured decision analysis output contract.

Choosing whether a sentence asks for a decision is canonical Brain understanding;
this module validates and renders the advisory JSON only.
"""
from __future__ import annotations


def _list(value, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} listesi geçersiz.")
    return [item.strip() for item in value]


def analyze(
    question: str,
    options: list[dict],
    *,
    recommendation: str | None = None,
    rationale: str = "",
    uncertainties: list[str] | None = None,
) -> dict:
    if not isinstance(options, list) or len(options) < 2:
        raise ValueError("Karar analizi için en az iki seçenek gerekir.")
    rows = []
    names = set()
    for option in options:
        if not isinstance(option, dict) or not isinstance(option.get("name"), str):
            raise ValueError("Seçenek adı geçersiz.")
        name = option["name"].strip()
        if not name or name in names:
            raise ValueError("Seçenek adları tekil ve dolu olmalı.")
        names.add(name)
        rows.append({
            "name": name,
            "pros": _list(option.get("pros", []), "Artı"),
            "cons": _list(option.get("cons", []), "Eksi"),
        })
    if recommendation is not None and recommendation not in names:
        raise ValueError("Öneri seçeneklerden biri olmalı.")
    if recommendation is None:
        recommendation = rows[0]["name"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Gerekçeli öneri gerekir.")
    uncertainties = [] if uncertainties is None else _list(uncertainties, "Belirsizlik")
    return {
        "schema": "decision_analysis.v1",
        "question": question.strip(),
        "options": rows,
        "recommendation": {
            "option": recommendation,
            "rationale": rationale.strip(),
        },
        "uncertainties": uncertainties,
    }


def render(result: dict) -> str:
    if not isinstance(result, dict) or result.get("schema") != "decision_analysis.v1":
        raise ValueError("Karar analizi şeması geçersiz.")
    lines = ["Karar analizi:"]
    for option in result["options"]:
        lines.append(f"\n{option['name']}")
        lines.append("Artıları: " + (", ".join(option["pros"]) or "Belirgin artı yok."))
        lines.append("Eksileri: " + (", ".join(option["cons"]) or "Belirgin eksi yok."))
    rec = result["recommendation"]
    lines.append(f"\nÖnerim: {rec['option']} — {rec['rationale']}")
    if result["uncertainties"]:
        lines.append("Belirsizlikler: " + ", ".join(result["uncertainties"]))
    return "\n".join(lines)
