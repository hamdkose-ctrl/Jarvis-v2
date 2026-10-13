"""One running Jarvis per data directory, enforced by an OS-held file lock.

A second launch exits without terminating the first process. Restart children can
wait briefly for the old process to exit. The OS frees the lock after a crash.
"""
from __future__ import annotations
import atexit
import errno
import os
from pathlib import Path
import threading
import time
from modules.diagnostics import record_failure as _record_failure

DATA_DIR = Path(os.environ.get('JARVIS_DATA_DIR') or (Path.home() / '.jarvis'))
PID_FILE = DATA_DIR / 'jarvis.pid'
LOCK_FILE = DATA_DIR / 'jarvis.lock'
_done = False
_lock_handle = None
_guard = threading.RLock()
taken_over = None  # Compatibility: existing processes are never terminated.


def _try_lock(handle):
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return False
        raise
    return True


def take_over():
    """Acquire once before starting devices/services; second launches exit cleanly."""
    global _done, _lock_handle
    with _guard:
        if _done:
            return None
        handle = None
        wait = os.environ.pop('JARVIS_RESTART_WAIT', '') == '1'
        deadline = time.monotonic() + (20 if wait else 0)
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            handle = LOCK_FILE.open('a+b')
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0');handle.flush()
            while not _try_lock(handle):
                if time.monotonic() >= deadline:
                    handle.close()
                    print('Jarvis zaten açık; ikinci kopya başlatılmadı.')
                    raise SystemExit(0)
                time.sleep(.1)
            PID_FILE.write_text(str(os.getpid()), encoding='utf-8')
        except OSError:
            _record_failure('instance.py:take_over')
            if handle is not None:
                handle.close()
            print('Jarvis tek kopya kilidi oluşturulamadı; açılış durduruldu.')
            raise SystemExit(1)
        _lock_handle = handle
        _done = True
        atexit.register(release, unlock=True)
        return None


def release(*, unlock=False):
    """Clean PID but retain lock through shutdown; normal process exit unlocks."""
    global _done, _lock_handle
    with _guard:
        if not _done:
            return
        try:
            if PID_FILE.read_text(encoding='utf-8').strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass
        if unlock and _lock_handle is not None:
            _lock_handle.close()
            _lock_handle = None
            _done = False
        # Never unlink LOCK_FILE: another opener must lock the same file inode.
