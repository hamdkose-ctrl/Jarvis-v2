"""Read-only ResearchWorker boundary.

The worker performs one bounded public HTTPS read and returns source-bound
WorkerResult evidence.  It never logs in, posts, downloads a file, uploads,
publishes, sends, writes local files, calls a model, or mutates GoalState.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

from modules import worker_result

CAPABILITY_ID = 'research.readonly'
CAPABILITY_VERSION = '1'
_MAX_CONTENT = 20_000
_EFFECT_OPS = frozenset({'download', 'login', 'post', 'upload', 'send', 'publish', 'write', 'delete', 'submit'})
_TEXT_TYPES = frozenset({
    'text/html', 'text/plain', 'application/json', 'application/rss+xml',
    'application/atom+xml', 'application/xml', 'text/xml',
})


class ReadOnlyViolation(PermissionError):
    """The request crosses the ResearchWorker read-only boundary."""


def _request_digest(request: dict) -> str:
    if not isinstance(request, dict):
        raise ValueError('ResearchWorker isteği sözlük olmalı.')
    raw = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _check_fence(fence: dict, request: dict) -> None:
    if not isinstance(fence, dict):
        raise ReadOnlyViolation('ResearchWorker execution fence gerekli.')
    if fence.get('capability_id') != CAPABILITY_ID or fence.get('capability_version') != CAPABILITY_VERSION:
        raise ReadOnlyViolation('ResearchWorker capability fence uyuşmuyor.')
    if fence.get('input_digest') != _request_digest(request):
        raise ReadOnlyViolation('ResearchWorker input digest uyuşmuyor.')


def _origin(url: str) -> str:
    from modules import public_sources

    normalized = public_sources.address(url)
    parsed = urlsplit(normalized)
    return f'{parsed.scheme}://{parsed.hostname}'


def _allowed(request: dict, url: str) -> str:
    allowed = request.get('allowed_origins')
    if not isinstance(allowed, list) or not allowed or not all(isinstance(item, str) for item in allowed):
        raise ReadOnlyViolation('ResearchWorker allowed_origins gerekli.')
    origins = set()
    for item in allowed:
        from modules import public_sources
        normalized = public_sources.address(item)
        parsed = urlsplit(normalized)
        if parsed.path not in ('', '/') or parsed.query:
            raise ReadOnlyViolation('ResearchWorker allowed_origins yalnız origin içermeli.')
        origins.add(f'{parsed.scheme}://{parsed.hostname}')
    origin = _origin(url)
    if origin not in origins:
        raise ReadOnlyViolation('ResearchWorker kaynak origin izinli değil.')
    return origin


def _max_chars(request: dict) -> int:
    value = request.get('max_chars', 12_000)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > _MAX_CONTENT:
        raise ValueError(f'ResearchWorker max_chars 1-{_MAX_CONTENT} aralığında olmalı.')
    return value


def _summary(text: str, limit: int = 600) -> str:
    value = re.sub(r'\s+', ' ', str(text)).strip()
    if len(value) <= limit:
        return value
    return value[:limit - 1].rsplit(' ', 1)[0] + '…'


def _decode(response: dict) -> str:
    content_type = str(response.get('content_type', '')).split(';', 1)[0].strip().lower()
    if content_type not in _TEXT_TYPES:
        raise ReadOnlyViolation('ResearchWorker dosya/binary indirme yapmaz; yalnız metinsel kaynak okur.')
    body = response.get('body')
    if not isinstance(body, (bytes, bytearray)):
        raise ValueError('ResearchWorker kaynak gövdesi bytes olmalı.')
    if content_type == 'text/html':
        from modules import public_sources
        return public_sources.text(bytes(body))
    return bytes(body).decode('utf-8', 'replace').strip()


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


def run(fence: dict, request: dict, *, fetcher=None) -> dict:
    """Read one explicitly allowed public source and return WorkerResult v1 evidence."""
    if not isinstance(request, dict):
        raise ValueError('ResearchWorker isteği sözlük olmalı.')
    operation = request.get('operation')
    if operation in _EFFECT_OPS or operation != 'read':
        raise ReadOnlyViolation('ResearchWorker yalnız read işlemine izin verir.')
    _check_fence(fence, request)

    url = request.get('url')
    if not isinstance(url, str) or not url:
        raise ValueError('ResearchWorker url gerekli.')
    expected_origin = _allowed(request, url)

    if fetcher is None:
        from modules import public_sources
        fetcher = public_sources.fetch
    response = fetcher(url)
    if not isinstance(response, dict):
        raise ValueError('ResearchWorker kaynak yanıtı geçersiz.')

    final_url = response.get('url')
    if not isinstance(final_url, str) or _origin(final_url) != expected_origin:
        raise ReadOnlyViolation('ResearchWorker yönlendirme sonrası izinli origin dışına çıkamaz.')
    text = _decode(response)
    if not text:
        raise ValueError('ResearchWorker kaynak metni boş.')

    limit = _max_chars(request)
    content = text[:limit]
    body = bytes(response['body'])
    parsed = urlsplit(final_url)
    evidence = {
        'kind': 'research_source',
        'source': {
            'url': final_url,
            'publisher': parsed.hostname or '',
            'sha256': hashlib.sha256(body).hexdigest(),
            'content_type': str(response.get('content_type', '')).split(';', 1)[0].strip().lower(),
        },
        'extractor': 'modules.public_sources',
        'summary': _summary(text),
        'content': content,
        'truncated': len(text) > len(content),
    }
    return _base_result(fence, evidence)
