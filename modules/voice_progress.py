"""Short spoken progress lines while a long job is actually running.

The user's requirement is that Jarvis keeps talking *while* it works and that the
voice never changes identity. The speaking queue already accepts work without
blocking Core (``voice_runtime.say``), and the voice identity comes from the
profile's selected catalog entry, not from the model provider — so a provider
switch cannot change the voice. What was missing was anything to say: a long job
ran silently until its final answer.

This module is the single gate for that narration. It is deliberately quiet:

* at most ``MAX_LINES_PER_JOB`` lines per job and at least ``MIN_GAP_SECONDS``
  apart, so a slow job cannot turn into a monologue;
* short, honest, tool-derived wording — it never claims progress that has not
  happened and never invents a result;
* it speaks through the existing ``say`` event channel, so the same lane, the
  same selected voice, the same privacy gate and the same microphone handoff
  apply as for ordinary answers.
"""
from __future__ import annotations

import time

from modules.diagnostics import record_failure as _record_failure

MIN_GAP_SECONDS = 10.0
MAX_LINES_PER_JOB = 3
_LINES: dict[str, list] = {}

# Tool name -> what the user hears. Only real, already-selected work is named.
_STEP_WORDS = {
    "research": "Kaynakları tarıyorum.",
    "writer": "Yazıyı hazırlıyorum.",
    "coder": "Kodu hazırlıyorum.",
    "files": "Dosyalara bakıyorum.",
    "file": "Dosyalara bakıyorum.",
    "mail": "E-postalara bakıyorum.",
    "calendar": "Takvimi kontrol ediyorum.",
    "finance": "Finans verisine bakıyorum.",
    "news": "Haber kaynaklarını tarıyorum.",
    "verify": "Sonucu doğruluyorum.",
}
_GENERIC_STEP = "Üzerinde çalışıyorum."


def step_words(tool: str) -> str:
    """The honest sentence for one already-selected step tool."""
    if not isinstance(tool, str):
        return _GENERIC_STEP
    return _STEP_WORDS.get(tool.strip().casefold(), _GENERIC_STEP)


def _state(job_id: str) -> list:
    row = _LINES.setdefault(job_id, [0, 0.0])
    return row


def may_speak(job_id: str, *, now: float | None = None) -> bool:
    """True when this job may still say one more progress line."""
    if not isinstance(job_id, str) or not job_id:
        return False
    now = time.monotonic() if now is None else now
    count, last = _state(job_id)
    if count >= MAX_LINES_PER_JOB:
        return False
    return now - last >= MIN_GAP_SECONDS


def _record(job_id: str, *, now: float) -> None:
    row = _state(job_id)
    row[0] += 1
    row[1] = now


def forget(job_id: str) -> None:
    """A finished job keeps no narration budget."""
    _LINES.pop(job_id, None)


def narrate(runtime, job: dict, text: str, *, now: float | None = None) -> bool:
    """Say one short progress line for this job, or stay quiet.

    Returns True when a line was handed to the single voice lane. A muted or
    sleeping profile still works; only the spoken line is skipped.
    """
    if not isinstance(job, dict) or not isinstance(text, str) or not text.strip():
        return False
    job_id = job.get("id")
    owner = job.get("owner")
    if not isinstance(job_id, str) or not isinstance(owner, str) or not owner:
        return False
    now = time.monotonic() if now is None else now
    if not may_speak(job_id, now=now):
        return False
    try:
        if not runtime.flags.get("speak", True) or runtime.flags.get("sleep"):
            return False
        quiet = getattr(runtime, "pause_listening", None)
        if quiet is not None and quiet.is_set():
            # Another notice owns the speaker this instant; a progress line is
            # never worth interrupting it, and the next step will say its own.
            return False
        runtime.events.put(("say", text, owner,
                            {"kind": "progress", "goal_id": job_id}))
    except Exception:                     # noqa: BLE001 - narration is never required work
        _record_failure("modules/voice_progress.py:narrate")
        return False
    _record(job_id, now=now)
    return True
