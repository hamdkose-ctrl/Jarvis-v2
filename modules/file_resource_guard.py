"""Scoped OS resource claims for cooperative local file-effect adapters.

Stable canonical path keys and existing inode aliases are reserved together;
all callers use the established resource_leases OS lock, not a new Scheduler.
No model-provided string can substitute a trusted resource identity.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import os
import re
import stat
from pathlib import Path

from modules import resource_leases

# A physical file has one OS-account claim namespace, regardless of which
# JARVIS_DATA_DIR a running Jarvis instance uses. Keep per-instance journals
# in DATA_DIR; only live resource arbitration belongs here.
_FILE_EFFECT_CLAIM_ROOT = Path.home() / '.jarvis' / 'file-effect-claims'


def receipt_owner_suffixes(owner: str) -> tuple[str, str]:
    """Distinct owner identities stay distinct, even after 60-char truncation.

    The second value is the historical filename suffix. Never interpret a
    historical truncated shared receipt as belonging to either long owner.
    Short, already-unambiguous owner paths stay backward compatible.
    """
    if not isinstance(owner, str) or len(owner) > 100:
        raise ValueError('File receipt owner invalid.')
    safe = re.sub(r'[^\w-]', '_', owner) or 'ortak'
    old = safe[:60]
    if len(safe) <= 60:
        return old, old
    return safe[:43] + '-' + hashlib.sha256(owner.encode('utf-8')).hexdigest()[:16], old


@contextmanager
def claim_paths(*paths):
    if not paths or len(paths) > 16:
        raise ValueError('File effect resource set must contain 1–16 paths.')
    root = _FILE_EFFECT_CLAIM_ROOT
    if root.parent.is_symlink() or root.is_symlink():
        raise resource_leases.LeaseConflict('Shared file claim directory invalid.')
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise resource_leases.LeaseConflict('Shared file claim directory was replaced.')
    def snapshot(path):
        if path.is_symlink():
            raise resource_leases.LeaseConflict('File effect cannot target a symlink.')
        try:
            canonical = os.path.normcase(str(path.resolve(strict=False)))
            info = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            info = None
        except (OSError, RuntimeError) as exc:
            raise resource_leases.LeaseConflict('Cannot validate file resource identity.') from exc
        if not canonical:
            raise ValueError('File effect resource path invalid.')
        # Never mistake a directory, symlink or special file for a file alias.
        file_id = (info.st_dev, info.st_ino) if info is not None and stat.S_ISREG(info.st_mode) and info.st_ino else None
        return canonical, file_id, info is not None

    keys = set()
    expected = []
    for supplied in paths:
        path = Path(supplied)
        identity = snapshot(path)
        expected.append((path, identity))
        canonical, file_id, _exists = identity
        digest = hashlib.sha256(os.fsencode(canonical)).hexdigest()
        keys.add(resource_leases.resource_key('file', digest))
        # Existing hardlinks with distinct names share one physical identity.
        # Zero inode is not a unique identity on some Windows filesystems.
        if file_id is not None:
            identifier = f'{file_id[0]}:{file_id[1]}'
            keys.add(resource_leases.resource_key(
                'file', hashlib.sha256(identifier.encode('ascii')).hexdigest(),
            ))
    # Sorted, non-blocking multi-claim acquisition prevents circular waits.
    # ExitStack releases already acquired keys if a later key is occupied.
    with ExitStack() as stack:
        for key in sorted(keys):
            stack.enter_context(resource_leases.process_resource_claim(root, key))
        # The path or hardlink target may have been swapped after preflight.
        # Refuse to act on a different object under the old object's claim.
        for path, identity in expected:
            if snapshot(path) != identity:
                raise resource_leases.LeaseConflict(
                    'File resource identity changed before execution.'
                )
        yield
