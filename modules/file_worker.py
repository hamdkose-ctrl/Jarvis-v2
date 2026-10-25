"""Read-only FileWorker boundary.

The worker only observes files/directories under an explicit root and returns
WorkerResult evidence.  It never creates, modifies, deletes, moves, exports,
uploads, downloads, or sends files and it never mutates GoalState.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from modules import worker_result

CAPABILITY_ID = 'file.readonly'
CAPABILITY_VERSION = '1'
_MAX_CONTENT = 20_000
_EFFECT_OPS = frozenset({'write', 'delete', 'move', 'rename', 'download', 'upload', 'send', 'export', 'save'})


class ReadOnlyViolation(PermissionError):
    """The request crosses the FileWorker read-only boundary."""


def _request_digest(request: dict) -> str:
    if not isinstance(request, dict):
        raise ValueError('FileWorker isteği sözlük olmalı.')
    raw = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _check_fence(fence: dict, request: dict) -> None:
    if not isinstance(fence, dict):
        raise ReadOnlyViolation('FileWorker execution fence gerekli.')
    if fence.get('capability_id') != CAPABILITY_ID or fence.get('capability_version') != CAPABILITY_VERSION:
        raise ReadOnlyViolation('FileWorker capability fence uyuşmuyor.')
    if fence.get('input_digest') != _request_digest(request):
        raise ReadOnlyViolation('FileWorker input digest uyuşmuyor.')


def _root(root) -> Path:
    path = Path(root).resolve(strict=True)
    if not path.is_dir():
        raise ReadOnlyViolation('FileWorker root klasör olmalı.')
    return path


def _target(root: Path, value) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('FileWorker path gerekli.')
    candidate = (root / value).resolve(strict=True)
    if candidate != root and root not in candidate.parents:
        raise ReadOnlyViolation('FileWorker root dışına çıkamaz.')
    return candidate


def _relative(root: Path, path: Path) -> str:
    if path == root:
        return '.'
    return path.relative_to(root).as_posix()


def _summary(text: str, limit: int = 600) -> str:
    value = re.sub(r'\s+', ' ', str(text)).strip()
    if len(value) <= limit:
        return value
    return value[:limit - 1].rsplit(' ', 1)[0] + '…'


def _max_chars(request: dict) -> int:
    value = request.get('max_chars', 12_000)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > _MAX_CONTENT:
        raise ValueError(f'FileWorker max_chars 1-{_MAX_CONTENT} aralığında olmalı.')
    return value


def _base_result(fence: dict, evidence: dict) -> dict:
    result = {
        'schema': worker_result.SCHEMA,
        'status': 'succeeded',
        'evidence': [evidence],
    }
    for key in ('owner', 'job_id', 'step_id', 'command_id', 'attempt', 'expected_job_version',
                'capability_id', 'capability_version', 'input_digest'):
        result[key] = fence[key]
    return worker_result.validate(result)


def _list(root: Path, target: Path) -> dict:
    if not target.is_dir():
        raise ValueError('FileWorker list hedefi klasör olmalı.')
    rows = []
    for entry in sorted(target.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
        stat = entry.lstat()
        kind = 'symlink' if entry.is_symlink() else 'directory' if entry.is_dir() else 'file'
        rows.append({
            'name': entry.name,
            'path': _relative(root, entry),
            'kind': kind,
            'size': stat.st_size if kind == 'file' else None,
        })
    digest = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    return {
        'kind': 'directory_listing',
        'source': {'path': _relative(root, target), 'sha256': digest},
        'summary': f'{len(rows)} girdi okundu.',
        'content': rows,
    }


def _read(root: Path, target: Path, request: dict) -> dict:
    if not target.is_file():
        raise ValueError('FileWorker read hedefi dosya olmalı.')
    from modules import docs

    text = docs.read_document(str(target), keep_pages=True, cache=False)
    limit = _max_chars(request)
    content = text[:limit]
    hasher = hashlib.sha256()
    with target.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            hasher.update(block)
    return {
        'kind': 'file_content',
        'source': {
            'path': _relative(root, target),
            'sha256': hasher.hexdigest(),
            'size': target.stat().st_size,
        },
        'extractor': 'modules.docs.read_document',
        'summary': _summary(text),
        'content': content,
        'truncated': len(text) > len(content),
    }


def run(fence: dict, request: dict, *, root) -> dict:
    """Execute one bounded read-only file observation and return WorkerResult v1."""
    if not isinstance(request, dict):
        raise ValueError('FileWorker isteği sözlük olmalı.')
    operation = request.get('operation')
    if operation in _EFFECT_OPS or operation not in {'list', 'read'}:
        raise ReadOnlyViolation('FileWorker yalnız list/read işlemlerine izin verir.')
    _check_fence(fence, request)
    base = _root(root)
    target = _target(base, request.get('path'))
    evidence = _list(base, target) if operation == 'list' else _read(base, target, request)
    return _base_result(fence, evidence)
