"""Opt-in, reasoned and respectful critique output contract."""
from __future__ import annotations

import re


_REQUEST = re.compile(
    r"\b(?:eleştir\w*|elestir\w*|zayıf\s+(?:nokta|yan|yön)\w*|zayif\s+(?:nokta|yan|yon)\w*|"
    r"dürüstçe|durustce|dürüst\s+ol\w*|durust\s+ol\w*|açık\s+sözlü|acik\s+sozlu|"
    r"eksikler\w*|eksik\s+(?:yan|yön|yon|nokta)\w*|neresi\s+(?:kötü|kotu|eksik|zayıf|zayif)|"
    r"nerede\s+hata\s+yap\w*)",
    re.I,
)
_UNSAFE = re.compile(
    r"\b(?:aptal|salak|gerizekalı|gerizekali|deli|narsist|depresif|başarısızsın|"
    r"basarisizsin|kesinlikle\s+(?:başarısız|basarisiz)|mutlaka\s+(?:böyle|boyle))\b",
    re.I,
)


def requested(text: str) -> bool:
    return isinstance(text, str) and bool(_REQUEST.search(text))


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} boş olamaz.")
    value = value.strip()
    if _UNSAFE.search(value):
        raise ValueError("Eleştiri dili hakaret, teşhis veya kesin hüküm içeremez.")
    return value


def critique(
    request: str,
    *,
    weak_point: str,
    because: str,
    impact: str = "",
    next_step: str = "",
) -> dict | None:
    if not requested(request):
        return None
    weak_point = _text(weak_point, "Zayıf nokta")
    because = _text(because, "Gerekçe")
    impact = _text(impact, "Olası etki") if impact else ""
    next_step = _text(next_step, "Sonraki adım") if next_step else ""
    return {
        "schema": "critique.v1",
        "weak_point": weak_point,
        "because": because,
        "impact": impact,
        "next_step": next_step,
        "tone": "direct_respectful",
    }


def render(result: dict) -> str:
    if not isinstance(result, dict) or result.get("schema") != "critique.v1":
        raise ValueError("Eleştiri şeması geçersiz.")
    lines = [result["weak_point"], "Çünkü: " + result["because"]]
    if result.get("impact"):
        lines.append("Olası etkisi: " + result["impact"])
    if result.get("next_step"):
        lines.append("Pratik sonraki adım: " + result["next_step"])
    return "\n".join(lines)
