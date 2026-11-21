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
    'PROVIDER_REQUEST_TOO_LARGE': (
        'Bu turu anlamlandırmak için gereken bağlam seçili modelin istek sınırını aşıyor; '
        'uygun kapasitede bir model gerekli. Hiçbir işlem başlatmadım.'
    ),
    'PROVIDER_QUOTA_AND_REQUEST_TOO_LARGE': (
        'Bir model kota sınırına takıldı. Yedek model de isteğin boyutunu kabul etmedi. '
        'Herhangi bir işlem başlatılmadı.'
    ),
    'PROVIDER_CONFIGURATION_REQUIRED': 'Bu istek için Ayarlar’daki model bağlantısı eksik.',
    'LOCAL_DEADLINE_EXCEEDED': 'Model bu tur için ayrılan sürede yanıt vermedi.',
    "CORE_CANCELLED": "İşlem senin isteğinle durduruldu.",
    "FILE_TARGET_NOT_ACCESSIBLE": (
        "Bu dosyaya erişemiyorum (izinli klasörlerin dışında, bulunamıyor veya "
        "hedef doğrulanamadı); işlem başlatılmadı."
    ),
    "PHOTO_CANCELLED": "Fotoğraf işlemi senin isteğinle durduruldu.",
}

_FALLBACK_TEXT = "İşlem tamamlanamadı; tanı kaydına bakılmalı."

PROVIDER_RECOVERY = {
    'PROVIDER_REQUEST_TOO_LARGE': 'request_change_required',
    'PROVIDER_QUOTA_AND_REQUEST_TOO_LARGE': 'fallback_possible',
    'PROVIDER_CONFIGURATION_REQUIRED': 'user_action_required',
    'LOCAL_DEADLINE_EXCEEDED': 'fail_closed',
}


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
