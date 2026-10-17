"""Jarvis açılış fazlarını ölçer; ölçüm hiçbir ağ veya model çağrısı yapmaz."""
from __future__ import annotations
import json
import threading
import time
from pathlib import Path

from config import DATA_DIR
from modules.diagnostics import record_failure as _record_failure

BUDGET_SECONDS = 30.0
_LOCK = threading.RLock()
_STARTED = time.monotonic()
_MARKS: dict[str, float] = {'process_start': 0.0}


def mark(name: str) -> float:
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Açılış fazı adı gerekli.')
    elapsed = round(time.monotonic() - _STARTED, 4)
    with _LOCK:
        _MARKS[name] = elapsed
    return elapsed


def snapshot() -> dict:
    with _LOCK:
        marks = dict(_MARKS)
    elapsed = max(marks.values(), default=0.0)
    return {
        'budget_seconds': BUDGET_SECONDS,
        'elapsed_seconds': elapsed,
        'over_budget': elapsed > BUDGET_SECONDS,
        'marks': marks,
    }


def ready(name: str = 'window_open') -> dict:
    mark(name)
    data = snapshot()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = Path(DATA_DIR) / 'startup_timing.json'
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
    except OSError:
        _record_failure('modules/startup_metrics.py:ready')
    return data
