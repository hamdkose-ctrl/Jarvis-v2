"""Practical step-by-step guidance with trade-offs and risks."""
from __future__ import annotations

def build(goal: str, steps: list[str], *, options: list[dict] | None = None, risks: list[str] | None = None) -> dict:
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("goal is required")
    if not isinstance(steps, list) or not steps or any(not isinstance(step, str) or not step.strip() for step in steps):
        raise ValueError("at least one step is required")
    options = options or []
    for option in options:
        if not isinstance(option, dict) or not str(option.get("name", "")).strip() or not str(option.get("why", "")).strip():
            raise ValueError("options need name and why")
    risks = risks or []
    if any(not isinstance(risk, str) or not risk.strip() for risk in risks):
        raise ValueError("risks must contain non-empty strings")
    selected = options[0] if options else None
    return {"goal": goal.strip(), "steps": [{"order": i, "instruction": step.strip()} for i, step in enumerate(steps, 1)], "selected_option": selected, "risks": [{"risk": risk.strip(), "mitigation": "küçük bir denemeyle başla ve sonucu gözlemle"} for risk in risks]}
