"""Shared visual type vocabulary.

The Brain owns whether a user turn requests a visual and which bounded kind
it proposes. Visual execution consumes this vocabulary but does not classify
the chat turn itself.
"""
from __future__ import annotations

import re


TYPE_PATTERNS: dict[str, tuple[str, ...]] = {
    "mindmap": (r"zihin\s*harita", r"mind\s*map"),
    "flowchart": (r"akış\s*şema", r"süreç\s*şema", r"flowchart"),
    "timeline": (r"zaman\s*çizelge", r"zaman\s*çizgi", r"kronoloji", r"timeline"),
    "infographic": (r"infografik", r"bilgi\s*grafi", r"infographic"),
    "handwritten": (r"el\s*yazı", r"elle\s*yazılmış"),
    "blueprint": (r"teknik\s*çizim", r"şema\s*plan", r"blueprint", r"mimari\s*çizim"),
    "visualize": (r"görselleştir", r"özet(?:i|ini)?\s+görsel", r"süreç\s+özet"),
}

TYPES = tuple(TYPE_PATTERNS)
LABELS = {
    "mindmap": "zihin haritası",
    "flowchart": "akış şeması",
    "infographic": "infografik",
    "timeline": "zaman çizelgesi",
    "handwritten": "el yazısı notu",
    "blueprint": "teknik çizim",
    "visualize": "görsel özet",
}


def normalize(text: str) -> str:
    # Turkish dotted/dotless I normalization matches the existing visual grammar.
    return (text or "").replace("İ", "i").replace("I", "i").lower()


def match_type(text: str) -> str | None:
    normalized = normalize(text)
    for kind, patterns in TYPE_PATTERNS.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            return kind
    return None
