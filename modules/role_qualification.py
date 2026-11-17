"""Button-only Brain role qualification: run the standard free holdout in an exact subprocess.

The measurement itself stays the single contract owner (`scripts/brain_output_diagnose_holdout.py`):
same 20 bounded free-cloud calls, same thresholds, same effect-denial, same report. This module
only starts it, mirrors its own stdout progress and shows its JSON verdict. No paid flag exists
here; the qualification row is written by the script through the existing router_quota contract.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from pathlib import Path

import config
from modules.diagnostics import record_failure as _record_failure

_SCRIPT = 'scripts/brain_output_diagnose_holdout.py'
_CASE = re.compile(r'Semantic case (\d+)/(\d+)')
_lock = threading.Lock()
_state = {'running': False, 'done': 0, 'total': 0, 'error': '', 'last_state': ''}


def report_path() -> Path:
    return config.DATA_DIR / 'router' / 'qualify_report.json'


def _qualified() -> bool:
    """Same evidence gate the runtime uses; any error means not qualified, never assume."""
    try:
        from modules import llm, router_quota, smart_router
        owner = llm.current_user()
        if not owner:
            return False
        candidate = smart_router.qualification_candidate(owner)
        return router_quota.role_qualified(
            owner, candidate.provider, candidate.model, candidate.connection_id,
            fingerprint=smart_router._role_fingerprint(),
            binding=candidate.binding or str(candidate.connection_revision),
            directory=smart_router._STORE)
    except Exception:
        _record_failure('modules/role_qualification.py:_qualified')
        return False


def status() -> dict:
    with _lock:
        snap = dict(_state)
    return {'qualified': _qualified(), **snap}


def prepare() -> dict:
    root = Path(__file__).resolve().parents[1]
    with _lock:
        if _state['running']:
            return {'started': False}
        _state.update(running=True, done=0, total=20, error='', last_state='')

    def run():
        path = report_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                path.unlink()
            proc = subprocess.Popen(
                [sys.executable, '-X', 'utf8', str(root / _SCRIPT), '--run', '--json', str(path)],
                cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', errors='replace')
            for line in proc.stdout or ():
                match = _CASE.search(line)
                if match:
                    with _lock:
                        _state['done'] = max(0, int(match.group(1)) - 1)
                        _state['total'] = int(match.group(2))
            proc.wait()
            try:
                report = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                report = None
            with _lock:
                if not isinstance(report, dict):
                    _state['error'] = 'Doğrulama raporu okunamadı.'
                    _state['last_state'] = 'unmeasured'
                else:
                    _state['last_state'] = str(report.get('state') or 'unmeasured')
                    if _state['last_state'] != 'passed':
                        reason = (report.get('stop_reason') or report.get('reason_code')
                                  or report.get('reason') or '')
                        _state['error'] = ('Doğrulama tamamlanamadı' + (f': {reason}.' if reason else '.'))
                        _state['done'] = int(report.get('cases') or _state['done'])
        except Exception as exc:
            # Type name only: never surface provider text, paths of keys or tracebacks to the UI.
            _record_failure('modules/role_qualification.py:prepare')
            with _lock:
                _state['error'] = 'Doğrulama başlatılamadı: ' + type(exc).__name__
                _state['last_state'] = 'unmeasured'
        finally:
            with _lock:
                _state['running'] = False

    threading.Thread(target=run, daemon=True, name='rol-kabul').start()
    return {'started': True}
