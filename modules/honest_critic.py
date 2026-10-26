"""Direct, respectful critique for work and life topics."""
from __future__ import annotations

def critique(topic: str, weaknesses: list[str], *, strengths: list[str] | None = None, evidence: list[str] | None = None) -> dict:
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic is required")
    if not isinstance(weaknesses, list) or not weaknesses or any(not isinstance(item, str) or not item.strip() for item in weaknesses):
        raise ValueError("at least one weakness is required")
    strengths = strengths or []
    evidence = evidence or []
    if any(not isinstance(item, str) or not item.strip() for item in [*strengths, *evidence]):
        raise ValueError("strengths and evidence must contain non-empty strings")
    points = [{"text": f"Buradaki zayıf nokta şu çünkü: {item.strip()}", "severity": "high"} for item in weaknesses]
    return {"topic": topic.strip(), "points": points, "strengths": [s.strip() for s in strengths], "evidence": [e.strip() for e in evidence], "tone": "dürüst ve saygılı"}
