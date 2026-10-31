"""Brain failure synthesis (PR8): the one place that turns a Core/handler failure into user text.

``synthesize(feedback, exc)`` never returns raw exception text. It uses the correlated
``BrainFeedback`` (reason/recovery/needs_input) and the exception *class* (``failure_policy`` category),
and produces a fixed Turkish sentence. Whatever text still comes from a policy-built message is scrubbed
of URLs, key-looking tokens and file paths. It grants nothing, retries nothing and marks nothing done.
"""
from __future__ import annotations

import re

from modules import failure_policy
from modules.diagnostics import record_failure as _record_failure

CANCELLED_TEXT = "İsteği iptal ettim."
FILE_TEXT = "İstediğin dosyayı ya da bileşeni bulamadım."
VALIDATION_TEXT = "İsteği tamamlayamadım: bilgi eksik ya da geçersiz. Biraz daha ayrıntılı söyler misin?"
NEEDS_INPUT_TEXT = "Devam etmem için senden bir bilgi ya da onay gerekiyor."
GENERIC_TEXT = "Şu anda yanıt veremiyorum, biraz sonra tekrar dener misiniz?"

_URL = re.compile(r"(?i)\b(?:https?|ftp|wss?)://\S+|\bwww\.\S+")
_SECRET = re.compile(r"(?i)\b(?:sk|pk|gsk|ghp|xox[a-z]|AIza)[-_A-Za-z0-9]{8,}|"
                     r"(?:key|token|secret|password|passwd|authorization|bearer)\s*[=:]\s*\S+|"
                     r"\b[A-Za-z0-9_\-]{32,}\b")
_WIN_PATH = re.compile(r"\b[A-Za-z]:[\\/][^\s\"']*")
_NIX_PATH = re.compile(r"(?<![\w.])/(?:[\w.\-]+/)+[\w.\-]*")


def scrub(text: str) -> str:
    """Remove URLs, secret-looking tokens and file paths from policy-built text."""
    out = str(text)
    for pattern in (_URL, _WIN_PATH, _NIX_PATH, _SECRET):
        out = pattern.sub("[gizlendi]", out)
    return out.strip()


def _is_cancelled(feedback, exc) -> bool:
    from modules import requests_state
    return isinstance(exc, requests_state.Cancelled) or getattr(feedback, "result_status", None) == "cancelled"


def synthesize(feedback, exc: BaseException) -> str:
    """User-facing sentence for a failed request. Safe by construction; never raises."""
    try:
        if _is_cancelled(feedback, exc):
            return CANCELLED_TEXT
        if getattr(feedback, "needs_input", False) or getattr(feedback, "result_status", None) == "needs_input":
            return NEEDS_INPUT_TEXT
        if isinstance(exc, FileNotFoundError):
            return FILE_TEXT
        category = failure_policy.classify(exc)
        if category == failure_policy.VALIDATION or category == failure_policy.USER_INPUT:
            return VALIDATION_TEXT
        if isinstance(exc, failure_policy.ProviderExhaustedError) or category in failure_policy.PROVIDER_CATEGORIES \
                or category in (failure_policy.PERMISSION, failure_policy.SOURCE_INVALID):
            return scrub(failure_policy.explain(exc)) or GENERIC_TEXT
        return GENERIC_TEXT
    except Exception:
        _record_failure("modules/brain_failure.py:synthesize")
        return GENERIC_TEXT
