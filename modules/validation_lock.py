"""One release suite at a time, and never the same tree twice on this machine.

Two independent callers reach the full suite on the same PC: the updater while it
installs a version, and the PC acceptance watcher that tests an open PR. They used
to run together and fight over the speaker, the microphone, the ``~/.jarvis``
resource claims and the CPU, so a healthy tree was reported as failed (issue 679).

Two boundaries keep that honest without weakening the suite:

* ``only_one_run`` is a machine-wide exclusive claim. A second caller waits a
  bounded time and then reports that no verdict exists instead of racing.
* ``cached_verdict``/``remember_verdict`` reuse an earlier PASS for the exact same
  source tree, tests and interpreter. An identical tree cannot contain a new
  regression, so a remembered pass is evidence, not a shortcut. Failures are
  never cached: a red result must always be re-earned.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

LOCK_NAME = "validation.lock"
CACHE_DIR_NAME = "validation-cache"
STALE_SECONDS = 6 * 60 * 60
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
             ".backups", "backups", ".gradle", "build", ".claude"}


def root_dir() -> Path:
    return Path(os.environ.get("JARVIS_DATA_DIR") or (Path.home() / ".jarvis"))


def _record_failure(location: str) -> None:
    """Every broad catch below is a recovery path; it must leave a trace."""
    try:
        from modules.diagnostics import record_failure
        record_failure(location)
    except ImportError:
        import sys
        print(f"[Uyarı] {location}", file=sys.stderr)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:              # noqa: BLE001 - an unusual OS error is not proof of life
        _record_failure("modules/validation_lock.py:_pid_alive")
        return True
    return True


def _acquire(path: Path, owner: str) -> bool:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "owner": owner, "at": time.time()}))
    return True


def _reclaimable(path: Path) -> bool:
    """A dead owner or an ancient entry must not block every later run forever."""
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return True
    if not isinstance(data, dict):
        return True
    age = time.time() - float(data.get("at") or 0)
    if age > STALE_SECONDS:
        return True
    return not _pid_alive(int(data.get("pid") or 0))


@contextmanager
def only_one_run(owner: str, *, wait_seconds: float = 0.0, poll_seconds: float = 2.0):
    """Yield True when this caller owns the machine's single suite run.

    Yielding False is a real answer: another run owns the machine, so this caller
    has no verdict to publish. It is never rewritten into a pass or a failure.
    """
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("Doğrulama sahibi geçersiz.")
    if not 0 <= wait_seconds <= 3600 or not 0.05 <= poll_seconds <= 30:
        raise ValueError("Doğrulama kilidi sınırları dışında.")
    folder = root_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOCK_NAME
    deadline = time.monotonic() + wait_seconds
    held = False
    while True:
        if _acquire(path, owner):
            held = True
            break
        if _reclaimable(path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_seconds)
    try:
        yield held
    finally:
        if held:
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except (OSError, ValueError):
                data = {}
            if isinstance(data, dict) and int(data.get("pid") or 0) == os.getpid():
                path.unlink(missing_ok=True)


def tree_digest(root: Path, python: str = "") -> str:
    """Identity of one validated unit: sources, tests, contract files and interpreter."""
    digest = hashlib.sha256()
    digest.update(str(python or "").encode("utf-8"))
    digest.update(b"\0")
    base = Path(root)
    for path in sorted(base.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or SKIP_DIRS.intersection(path.relative_to(base).parts):
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        digest.update(path.relative_to(base).as_posix().encode("utf-8", "surrogatepass"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def _cache_path(key: str) -> Path:
    folder = root_dir() / CACHE_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (key + ".json")


def cached_verdict(key: str) -> str | None:
    """Return the remembered log tail of a PASS for this exact tree, or None."""
    try:
        data = json.loads(_cache_path(key).read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("ok") is not True:
        return None
    return str(data.get("log") or "")


def remember_verdict(key: str, ok: bool, log: str) -> None:
    """Store only successes; a failure must always be re-earned by a real run."""
    if ok is not True:
        return
    path = _cache_path(key)
    temporary = path.with_suffix(".tmp-" + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps({"ok": True, "log": log[-4000:],
                                         "at": time.time()}, ensure_ascii=False),
                              encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
