"""Read-only, optional speaker envelope for mascot presentation."""
import math
import time

from modules.diagnostics import record_failure as _record_failure

_enabled = False
_samples = ()


def enable(wanted: bool) -> None:
    global _enabled, _samples
    _enabled = bool(wanted)
    _samples = ()


def observe(pcm: bytes, frames: int, rate: int, time_info, cancel) -> None:
    """Bounded work; presentation failure cannot interrupt sound."""
    global _samples
    if not _enabled:
        return
    try:
        if rate <= 0 or frames <= 0 or not pcm or cancel.is_set():
            return
        samples = memoryview(pcm).cast("h")
        selected = samples[::max(1, len(samples) // 64)]
        rms = math.sqrt(sum(x * x for x in selected) / len(selected)) / 32768
        level = min(1.0, max(0.0, (rms - .008) / .14)) ** .65
        delay = 0.0
        if time_info is not None:
            delay = max(0.0, min(1.0, float(time_info.outputBufferDacTime)
                                  - float(time_info.currentTime)))
        start = time.monotonic() + delay
        if _enabled:
            _samples = (*_samples[-63:], (start, start + frames / rate, level, cancel))
    except Exception:
        _record_failure("modules/mascot_audio_meter.py:observe")
        return


def aperture(now=None) -> float:
    if not _enabled:
        return 0.0
    now = time.monotonic() if now is None else now
    for start, stop, level, cancel in reversed(_samples):
        if start <= now < stop and not cancel.is_set():
            return level
    return 0.0
