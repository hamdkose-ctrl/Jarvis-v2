"""Single response-format boundary for advisory chat output.

This module only formats model text. It never dispatches work, writes GoalState,
checks permission, or executes a worker. Invalid/non-JSON model output falls
back to the existing direct answer.
"""
from __future__ import annotations

import json

from modules import critique_advisor, decision_advisor, guidance_advisor, proactive_advisor
from modules.diagnostics import record_failure as _record_failure


def _mode(command: str) -> str | None:
    if decision_advisor.requested(command):
        return "decision"
    if critique_advisor.requested(command):
        return "critique"
    if guidance_advisor.requested(command):
        return "guidance"
    return None


def prompt_for(command: str, settings: dict | None) -> str:
    blocks = []
    mode = _mode(command)
    if mode == "decision":
        blocks.append(
            'Açık karar isteği var. Yalnız şu JSON alanlarını üret: '
            '{"options":[{"name":"...","pros":["..."],"cons":["..."]}],'
            '"recommendation":{"option":"...","rationale":"..."},'
            '"uncertainties":["..."]}. Şema adı: decision_analysis.v1.'
        )
    elif mode == "critique":
        blocks.append(
            'Açık eleştiri isteği var. Yalnız şu JSON alanlarını üret: '
            '{"weak_point":"...","because":"...","impact":"...","next_step":"..."}. '
            'Hakaret, teşhis, manipülasyon veya kesin hüküm kullanma. Şema adı: critique.v1.'
        )
    elif mode == "guidance":
        blocks.append(
            'Açık rehberlik isteği var. Yalnız şu JSON alanlarını üret: '
            '{"objective":"...","steps":[{"action":"...","why":"...","risks":["..."],'
            '"watchouts":["..."]}]}. Şema adı: guidance.v1.'
        )
    settings = settings if isinstance(settings, dict) else {}
    if proactive_advisor.SuggestionPolicy.from_settings(settings).enabled:
        blocks.append(
            'İlgili ve gerçekten yararlı bir risk/fırsat varsa JSON içine isteğe bağlı '
            '"suggestion":{"kind":"risk|opportunity","title":"...","text":"..."} alanını ekle; '
            'gereksizse ekleme. Öneri şema adı: proactive_suggestion.v1.'
        )
    return " ".join(blocks)


def _json_object(raw: str) -> dict | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    fence = chr(96) * 3
    if text.lower().startswith(fence + "json"):
        text = text[7:]
    elif text.startswith(fence):
        text = text[3:]
    if text.endswith(fence):
        text = text[:-3]
    try:
        value = json.loads(text.strip())
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _with_suggestion(answer: str, value: dict | None, settings: dict | None) -> str:
    if not value:
        return answer
    suggestion = value.get("suggestion")
    if not isinstance(suggestion, dict):
        return answer
    try:
        item = proactive_advisor.suggest(
            suggestion.get("kind"),
            suggestion.get("text"),
            settings=settings,
            title=suggestion.get("title", "Ek öneri"),
        )
    except (TypeError, ValueError):
        return answer
    return answer + "\n\n" + proactive_advisor.render(item) if item else answer


def finalize(command: str, raw: str, *, settings: dict | None = None) -> str:
    """Render a valid advisory response; preserve ordinary/raw answers."""
    value = _json_object(raw)
    mode = _mode(command)
    try:
        if mode == "decision" and value is not None:
            result = decision_advisor.analyze(
                command,
                value.get("options"),
                recommendation=(value.get("recommendation") or {}).get("option"),
                rationale=(value.get("recommendation") or {}).get("rationale", ""),
                uncertainties=value.get("uncertainties", []),
            )
            return _with_suggestion(decision_advisor.render(result), value, settings)
        if mode == "critique" and value is not None:
            result = critique_advisor.critique(
                command,
                weak_point=value.get("weak_point"),
                because=value.get("because"),
                impact=value.get("impact", ""),
                next_step=value.get("next_step", ""),
            )
            return _with_suggestion(critique_advisor.render(result), value, settings)
        if mode == "guidance" and value is not None:
            result = guidance_advisor.guide(
                command,
                objective=value.get("objective"),
                steps=value.get("steps"),
            )
            return _with_suggestion(guidance_advisor.render(result), value, settings)
        return _with_suggestion(raw, value, settings)
    except (TypeError, ValueError, KeyError):
        return raw
    except Exception:
        _record_failure("modules/advisory_router.py:finalize")
        return raw
