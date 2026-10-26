"""Opt-in/opt-out proactive suggestions for relevant risks and opportunities."""
from __future__ import annotations

def suggest(context: str, *, risks: list[str] | None = None, opportunities: list[str] | None = None, enabled: bool = True) -> list[dict]:
    if not isinstance(context, str) or not context.strip():
        raise ValueError("context is required")
    if not enabled:
        return []
    risks = risks or []
    opportunities = opportunities or []
    if any(not isinstance(item, str) or not item.strip() for item in [*risks, *opportunities]):
        raise ValueError("risks and opportunities must contain non-empty strings")
    result = []
    for risk in risks:
        result.append({"text": f"Burada dikkat et: {risk.strip()}", "reason": f"{context.strip()} bağlamında risk görüldü", "kind": "risk"})
    for opportunity in opportunities:
        result.append({"text": f"Bunu da düşünebilirsin: {opportunity.strip()}", "reason": f"{context.strip()} bağlamında fırsat görüldü", "kind": "opportunity"})
    return result
