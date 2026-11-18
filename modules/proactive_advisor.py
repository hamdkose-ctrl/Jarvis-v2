"""Low-noise proactive risk/opportunity suggestions (on by default, can be turned off)."""
from __future__ import annotations

from dataclasses import dataclass


KINDS = frozenset({"risk", "opportunity"})


@dataclass(frozen=True)
class SuggestionPolicy:
    enabled: bool = True
    max_per_response: int = 1
    priority: str = "low"

    @classmethod
    def from_settings(cls, settings: dict | None) -> "SuggestionPolicy":
        settings = settings if isinstance(settings, dict) else {}
        # Roadmap: default on; only an explicit False in settings turns it off.
        enabled = settings.get("proactive_suggestions", True) is not False
        max_per_response = settings.get("proactive_max_per_response", 1)
        if not isinstance(max_per_response, int) or isinstance(max_per_response, bool):
            max_per_response = 1
        return cls(
            enabled=enabled,
            max_per_response=max(0, min(1, max_per_response)),
            priority="low",
        )


def suggest(
    kind: str,
    text: str,
    *,
    settings: dict | None = None,
    title: str = "Ek öneri",
) -> dict | None:
    policy = SuggestionPolicy.from_settings(settings)
    if not policy.enabled or policy.max_per_response == 0:
        return None
    if kind not in KINDS:
        return None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Öneri metni boş olamaz.")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Öneri başlığı boş olamaz.")
    return {
        "schema": "proactive_suggestion.v1",
        "kind": kind,
        "priority": policy.priority,
        "title": title.strip(),
        "text": text.strip(),
        "phrasing": "Bunu da düşünebilirsin" if kind == "opportunity" else "Burada dikkat et",
    }


def render(result: dict) -> str:
    if not isinstance(result, dict) or result.get("schema") != "proactive_suggestion.v1":
        raise ValueError("Proaktif öneri şeması geçersiz.")
    return f"{result['phrasing']}: {result['text']}"
