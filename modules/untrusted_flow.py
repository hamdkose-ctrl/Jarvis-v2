"""Güvenilmeyen içerikten giden metne taşınan uzun belirteçleri saf olarak bulur."""
from __future__ import annotations

import re
from contextvars import ContextVar

_SEEN = ContextVar('jarvis_untrusted_flow', default=None)

_TRIM = " \t\r\n.,;:!?()[]{}<>\"'`“”‘’"
_URL = re.compile(r"^(?:https?://|www\.)", re.I)


def _tokens(text: str) -> list[str]:
    out = []
    for raw in text.split():
        token = raw.strip(_TRIM)
        if token:
            out.append(token)
            if '=' in token and not _URL.match(token):
                value = token.split('=', 1)[1].strip(_TRIM)
                if value:
                    out.append(value)
    return out


def _candidate(token: str, min_len: int) -> bool:
    if len(token) < min_len or _URL.match(token) or "://" in token:
        return False
    # Saf ve muhafazakâr sınır: yalnız harflerden oluşan uzun parçalar doğal
    # Türkçe/İngilizce sözcük kabul edilir. Karışık belirteçler akış kanıtıdır.
    if token.isalpha():
        return False
    return True


def shared_tokens(outgoing: str, untrusted: list[str], min_len: int = 12) -> list[str]:
    """Her iki tarafta birebir geçen uzun, boşluksuz belirteçleri giden sırada döndürür.

    Karşılaştırma büyük/küçük harf duyarlıdır. Noktalama yalnız token kenarından
    kırpılır; girdiler bozuksa hiçbir eşleşmeye güvenilmez ve boş liste döner.
    """
    if (not isinstance(outgoing, str) or not isinstance(untrusted, list)
            or type(min_len) is not int or min_len < 1
            or any(not isinstance(item, str) for item in untrusted)):
        return []
    if not outgoing or not untrusted:
        return []
    source = set()
    for text in untrusted:
        source.update(token for token in _tokens(text) if _candidate(token, min_len))
    result = []
    seen = set()
    for token in _tokens(outgoing):
        if token in source and _candidate(token, min_len) and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _texts(value):
    pending = [(value, 0)]
    nodes = size = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 40 or nodes > 20000:
            raise ValueError('Kaynak akışı sınırı aşıldı.')
        if isinstance(item, str):
            size += len(item)
            if size > 4_000_000:
                raise ValueError('Kaynak akışı boyut sınırı aşıldı.')
            yield item
        elif isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend((child, depth + 1) for child in item)


def observe(owner, scope, sources):
    """Sahip/iş bağlamında görülen kaynak belirteçlerini tutar; diske ham değer yazmaz."""
    from modules import service_store
    service_store.identity(owner)
    if not isinstance(scope, str) or not scope or len(scope) > 200:
        raise ValueError('Kaynak akışı için iş kimliği gerekli.')
    previous = _SEEN.get()
    if previous and previous[:2] == (owner, scope) and previous[2] is None:
        raise ValueError('Kaynak akışı tamamlanamadı.')
    seen = set(previous[2]) if previous and previous[:2] == (owner, scope) else set()
    _SEEN.set((owner, scope, None))
    for text in _texts(sources):
        seen.update(token for token in _tokens(text) if _candidate(token, 12))
        if len(seen) > 20000:
            raise ValueError('Kaynak belirteci sınırı aşıldı.')
    _SEEN.set((owner, scope, frozenset(seen)))


def requires_approval(owner, work_key, payload):
    """Giden metin/konu ile aynı işte görülen belirteçleri karşılaştırır."""
    from modules import service_store
    service_store.identity(owner)
    scope = work_key.rpartition(':')[0] or work_key
    # Devam/başka iş parçacığı: planlayıcının seçtiği bağımlılıklar dışındaki,
    # aynı işte daha önce görülen kaynakları da mevcut kalıcı kayıttan yükle.
    if re.fullmatch('[a-f0-9]{16}', scope):
        from modules import goal_executor
        job = goal_executor.latest(owner)
        if job and job['id'] == scope:
            observe(owner, scope, job['outputs'])
    current = _SEEN.get()
    if current and current[:2] == (owner, scope) and current[2] is None:
        raise ValueError('Kaynak akışı tamamlanamadı.')
    sources = list(current[2]) if current and current[:2] == (owner, scope) else []
    outgoing = '\n'.join(payload.get(key, '') for key in ('text', 'subject'))
    return bool(shared_tokens(outgoing, sources))
