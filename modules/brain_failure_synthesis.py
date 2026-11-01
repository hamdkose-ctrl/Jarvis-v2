"""Canonical Brain failure synthesis / recovery presentation (PR8 slice).

This module turns one already-classified Core/handoff outcome into a single
grounded user-facing message. It composes `failure_policy` (the only failure
classifier) and `BrainFeedback` (the already-recorded Core outcome); it never
classifies a raw exception itself, never re-runs or retries a worker, and never
grants permission or execution authority. A caller that wants a retry decides
and performs it elsewhere, using `recovery_class` as the signal; this module
only describes what happened.
"""
from __future__ import annotations

from modules import failure_policy
from modules.brain_contracts import BrainFeedback

_FAILED_STATUSES = frozenset({"failed", "cancelled"})

# Presentation for reason codes that never carry the original exception (the
# refusal was decided in Brain/Core before any provider call happened).
_REASON_TEXT = {
    "CORE_CANCELLED": "İşlem senin isteğinle durduruldu.",
    "FILE_TARGET_NOT_ACCESSIBLE": (
        "Bu dosyaya erişemiyorum (izinli klasörlerin dışında, bulunamıyor veya "
        "hedef doğrulanamadı); işlem başlatılmadı."
    ),
    "PHOTO_CANCELLED": "Fotoğraf işlemi senin isteğinle durduruldu.",
}

_FALLBACK_TEXT = "İşlem tamamlanamadı; tanı kaydına bakılmalı."


def synthesize(fb: BrainFeedback, exc: BaseException | None = None) -> str:
    """Return one grounded message for a failed/cancelled BrainFeedback.

    `exc` is the original exception when the caller still has it (handoff()
    re-raises it after recording `fb`); it is passed straight to the single
    `failure_policy` classifier, never re-interpreted here. The returned text
    never claims an automatic retry happened, whatever `fb.recovery_class` is.
    """
    if not isinstance(fb, BrainFeedback):
        raise ValueError("synthesize BrainFeedback bekler.")
    if fb.result_status not in _FAILED_STATUSES:
        raise ValueError("synthesize yalnız failed/cancelled BrainFeedback için çağrılır.")
    if exc is not None:
        return failure_policy.user_message(exc)
    return _REASON_TEXT.get(fb.reason_code or "", _FALLBACK_TEXT)
