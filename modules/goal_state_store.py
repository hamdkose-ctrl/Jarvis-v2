"""Atomic persisted storage for canonical GoalState snapshots."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path

import release_guard
from modules import goal_state


class PersistedStateConflict(ValueError):
    pass


@contextmanager
def _exclusive(path: Path):
    lock = Path(str(path) + '.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock, 'a+b')
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _read(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding='utf-8'))
    return goal_state.validate(raw)


def load(path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    return _read(path)


def create(path, state: dict) -> dict:
    path = Path(path)
    state = goal_state.validate(state)
    with _exclusive(path):
        if path.exists():
            raise PersistedStateConflict('GoalState kaydı zaten var.')
        release_guard.atomic(path, json.dumps(state, ensure_ascii=False).encode('utf-8'))
    return state


def compare_and_swap(path, *, expected_version: int, next_state: dict) -> dict:
    path = Path(path)
    next_state = goal_state.validate(next_state)
    if next_state['version'] != expected_version + 1:
        raise PersistedStateConflict('GoalState yeni sürümü expected_version + 1 olmalı.')
    with _exclusive(path):
        if not path.exists():
            raise PersistedStateConflict('GoalState kaydı bulunamadı.')
        current = _read(path)
        if current['version'] != expected_version:
            raise PersistedStateConflict('GoalState diskte değişti; eski CAS yazımı reddedildi.')
        for field in ('owner', 'job_id', 'goal', 'execution_mode'):
            if current[field] != next_state[field]:
                raise PersistedStateConflict('GoalState kimliği CAS sırasında değiştirilemez.')
        release_guard.atomic(path, json.dumps(next_state, ensure_ascii=False).encode('utf-8'))
    return next_state
