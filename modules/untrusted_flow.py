"""Güvenilmeyen içerikten giden metne taşınan uzun belirteçleri saf olarak bulur."""
from __future__ import annotations

import re

_TRIM = " \t\r\n.,;:!?()[]{}<>\"'`“”‘’"
_URL = re.compile(r"^(?:https?://|www\.)", re.I)


def _tokens(text: str) -> list[str]:
    out = []
    for raw in text.split():
        token = raw.strip(_TRIM)
        if token:
            out.append(token)
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
