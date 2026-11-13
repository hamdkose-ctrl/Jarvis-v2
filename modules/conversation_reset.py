"""Durable cross-process boundary for 'yeni sohbet' history filtering.

This only records conversation reset cutoffs; history rows are not deleted.
Brain's canonical context reader remains the owner of the filter.
"""
import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from config import DATA_DIR
from modules import file_resource_guard, resource_leases
from modules.diagnostics import record_failure as _record_failure

_lock = threading.RLock()
_reset_file = DATA_DIR / "chat_sessions.json"
_MAX_RESET_BYTES = 128 * 1024


def _disk_snapshot(path):
    """Never accept a truncated/foreign JSON document as permission to reset."""
    try:
        with path.open('rb') as stream:
            raw = stream.read(_MAX_RESET_BYTES + 1)
    except FileNotFoundError:
        return {}
    if len(raw) > _MAX_RESET_BYTES:
        raise ValueError('Sohbet sınırı dosyası çok büyük.')
    data = json.loads(raw.decode('utf-8'))
    if not isinstance(data, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in data.items()
    ):
        raise ValueError('Sohbet sınırı kaydı geçersiz.')
    return data


try:
    _resets = _disk_snapshot(_reset_file)
except (OSError, ValueError, UnicodeError):
    _record_failure('modules/conversation_reset.py:initial_snapshot')
    _resets = {}


def mark(slug):
    """Persist a new-chat boundary, preserving every other owner's cutoff.

    The old process-local snapshot + fixed .tmp name could overwrite another
    Jarvis process's reset. Both the read/merge and fsynced replacement now
    hold the existing physical path claim. Memory changes only after commit.
    """
    if not isinstance(slug, str) or not slug:
        raise ValueError('Sohbet sahibi geçersiz.')
    with _lock:
        path = _reset_file
        with file_resource_guard.claim_paths(path):
            existing = _disk_snapshot(path)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            # A clock correction must not reopen conversation context.
            existing[slug] = max(now, existing.get(slug, ''))
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix='.chat-sessions-', suffix='.tmp', dir=path.parent,
            )
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(json.dumps(
                        existing, ensure_ascii=False, sort_keys=True,
                    ).encode('utf-8'))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            _resets.clear()
            _resets.update(existing)


def recent(slug, rows):
    """Never reintroduce pre-reset context when a peer process moved the cutoff."""
    with _lock:
        path = _reset_file
        if path.exists():
            try:
                with file_resource_guard.claim_paths(path):
                    fresh = _disk_snapshot(path)
            except (OSError, ValueError, UnicodeError,
                    resource_leases.LeaseConflict):
                _record_failure('modules/conversation_reset.py:recent_snapshot')
                # A transient lock or broken reset file cannot resurrect
                # potentially stale conversation content.
                return []
            _resets.clear()
            _resets.update(fresh)
        cutoff = _resets.get(slug, "")
        return [r for r in rows if str(r.get("ts", "")) > cutoff] if cutoff else rows
