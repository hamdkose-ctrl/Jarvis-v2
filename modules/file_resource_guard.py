"""Scoped OS resource claims for cooperative local file-effect adapters.

Stable canonical path keys and existing inode aliases are reserved together;
all callers use the established resource_leases OS lock, not a new Scheduler.
No model-provided string can substitute a trusted resource identity.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path

from config import DATA_DIR
from modules import resource_leases


@contextmanager
def claim_paths(*paths):
    if not paths or len(paths) > 16:
        raise ValueError('File effect resource set must contain 1–16 paths.')
    root = DATA_DIR / 'file_resource_claims'
    if root.is_symlink():
        raise resource_leases.LeaseConflict('Shared file claim directory invalid.')
    root.mkdir(parents=True, exist_ok=True)
    keys = set()
    for supplied in paths:
        path = Path(supplied)
        if path.is_symlink():
            raise resource_leases.LeaseConflict('File effect cannot target a symlink.')
        canonical = os.path.normcase(str(path.resolve(strict=False)))
        if not canonical:
            raise ValueError('File effect resource path invalid.')
        digest = hashlib.sha256(os.fsencode(canonical)).hexdigest()
        keys.add(resource_leases.resource_key('file', digest))
        # Hardlinks with distinct paths still refer to the same physical file.
        if path.is_file():
            info = path.stat(follow_symlinks=False)
            # Some Windows filesystems report a zero inode for every file.
            # A non-unique alias must NEVER become a global file mutex.
            if info.st_ino:
                identifier = f'{info.st_dev}:{info.st_ino}'
                keys.add(resource_leases.resource_key(
                    'file', hashlib.sha256(identifier.encode('ascii')).hexdigest(),
                ))
    # Sorted, non-blocking multi-claim acquisition prevents circular waits.
    # ExitStack releases already acquired keys if a later key is occupied.
    with ExitStack() as stack:
        for key in sorted(keys):
            stack.enter_context(resource_leases.process_resource_claim(root, key))
        yield
