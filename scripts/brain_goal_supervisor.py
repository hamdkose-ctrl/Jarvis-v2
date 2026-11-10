"""Bounded live Brain Goal holdout process supervisor (no model calls here).

The original holdout continues in a child process with the exact same preflight,
privacy/free route, scoring and effect-denial guards. A per-read socket timeout
and requests_state.budget are *cooperative*; they cannot interrupt all possible
blocked Windows requests. This parent detects missing progress, terminates its
child, and writes state=unmeasured, never a fabricated semantic pass.

Child stdout goes to a file (not an interactive QuickEdit/Select console).
No credentials, prompt text or model answers are copied to parent progress.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

DEFAULT_STALL_SECONDS = 240.0
DEFAULT_POLL_SECONDS = 2.0
_CASE = re.compile(r'^Semantic case (\d+)/(\d+)$')
_WAIT = re.compile(r'^Waiting (\d+(?:\.\d+)?)s for the token budget$')


def _save_report(path: Path | None, data: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.tmp-' + str(os.getpid()))
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                        encoding='utf-8')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _parse_progress(buffer: str, chunk: str, *, show: bool) -> tuple[str, int]:
    """Only forward bounded, known-safe progress lines, not model/user content."""
    pending = buffer + chunk
    last_case = 0
    while '\n' in pending:
        line, pending = pending.split('\n', 1)
        line = line.strip()
        match = _CASE.fullmatch(line)
        if match:
            last_case = int(match.group(1))
            if show:
                print(line, flush=True)
        elif _WAIT.fullmatch(line) and show:
            print(line, flush=True)
    return pending[-2048:], last_case


def _verified_verdict(row: object, metadata: dict, exit_code: int | None) -> bool:
    """Reject stale/corrupt success reports, not just mismatched run identifiers."""
    if not isinstance(row, dict):
        return False
    state = row.get('state')
    if (row.get('head') != metadata['head']
            or row.get('corpus_sha256') != metadata['corpus_sha256']
            or row.get('scope') != metadata['scope']
            or state not in {'passed', 'failed', 'unmeasured'}
            or exit_code != {'passed':0,'failed':1,'unmeasured':2}[state]):
        return False
    if state != 'passed':
        return True
    if row.get('attempted_effects') != 0:
        return False
    if row.get('scope') == 'connection':
        return row.get('connection_ok') is True and row.get('provider_responses',0) >= 1
    cases = row.get('cases')
    responses = row.get('model_responses')
    score = row.get('accuracy')
    return (row.get('semantic_acceptance') is True
            and type(cases) is int and cases == 20
            and type(responses) is int and responses == cases
            and type(score) in (int,float) and .95 <= score <= 1
            and row.get('incorrect_action_proposals') == 0)


def supervise(*, script: Path, args: list[str], cwd: Path,
              report_path: Path | None, metadata: dict,
              stall_seconds: float = DEFAULT_STALL_SECONDS,
              poll_seconds: float = DEFAULT_POLL_SECONDS) -> int:
    """Supervise a real child; never auto-retry a stalled provider request."""
    if stall_seconds <= 0 or poll_seconds <= 0:
        raise ValueError('Watchdog duration must be positive.')
    output = None if report_path is None else Path(report_path)
    pending = dict(metadata)
    pending.update(state='unmeasured', semantic_acceptance=False,
                   reason_code='HOLDOUT_RUNNING')
    _save_report(output, pending)  # Clear previous 'passed' result immediately.
    with tempfile.TemporaryDirectory(prefix='jarvis-brain-goal-') as tmp:
        tmp = Path(tmp)
        logfile = tmp / 'worker.log'
        worker_json = tmp / 'worker.json'
        command = [sys.executable, '-X', 'utf8', str(script), '--_worker',
                   *args, '--json', str(worker_json)]
        kwargs = dict(cwd=str(cwd), stdin=subprocess.DEVNULL,
                      stderr=subprocess.STDOUT)
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        else:
            kwargs['start_new_session'] = True
        last_case = 0
        state_error = None
        return_code = None
        with logfile.open('w', encoding='utf-8') as log:
            try:
                child = subprocess.Popen(command, stdout=log, **kwargs)
            except OSError as exc:
                state_error = 'HOLDOUT_WORKER_START_FAILED'
                return_code = 2
                print('Test alt süreci başlatılamadı: ' + type(exc).__name__, flush=True)
            else:
                tail = ''
                offset = 0
                last_activity = time.monotonic()
                last_notice = last_activity
                try:
                    while True:
                        with logfile.open('r', encoding='utf-8', errors='replace') as reader:
                            reader.seek(offset)
                            chunk = reader.read()
                            offset = reader.tell()
                        if chunk:
                            tail, seen = _parse_progress(tail, chunk, show=True)
                            last_case = max(last_case, seen)
                            last_activity = time.monotonic()
                        return_code = child.poll()
                        if return_code is not None:
                            break
                        now = time.monotonic()
                        if now - last_activity >= stall_seconds:
                            state_error = 'HOLDOUT_STALLED'
                            print('Test ilerlemiyor; alt süreç durduruluyor. '
                                  f'Son başlayan senaryo: {last_case or "bilinmiyor"}.', flush=True)
                            break
                        if now - last_notice >= 60:
                            print('Brain Goal testi çalışıyor; sonraki yanıt bekleniyor '
                                  f'(son senaryo: {last_case or "bilinmiyor"}).', flush=True)
                            last_notice = now
                        time.sleep(poll_seconds)
                except KeyboardInterrupt:
                    state_error = 'HOLDOUT_INTERRUPTED'
                    print('Test kullanıcı tarafından durduruldu.', flush=True)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=15)
        # A completed worker report is adopted ONLY with exact version, corpus
        # and scope evidence, plus a consistent state/exit code. A terminated
        # process never upgrades an old report to success.
        valid = None
        if state_error is None and worker_json.is_file():
            try:
                row = json.loads(worker_json.read_text(encoding='utf-8'))
                if _verified_verdict(row, metadata, return_code):
                    valid = row
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if valid is None:
            valid = dict(pending)
            valid.update(reason_code=state_error or 'HOLDOUT_WORKER_INVALID',
                         last_started_case=last_case,
                         generated_at=datetime.now(timezone.utc).isoformat())
            if state_error == 'HOLDOUT_STALLED':
                valid['reason'] = 'Worker progress stalled; no semantic verdict.'
            else:
                valid['reason'] = 'Worker ended without a matching completed report.'
        _save_report(output, valid)
        print(json.dumps(valid, ensure_ascii=False), flush=True)
        return {'passed': 0, 'failed': 1, 'unmeasured': 2}[valid['state']]
