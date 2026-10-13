"""Explicit user confirmation; mentioning yes inside a sentence is not approval."""
import re

_YES = {'evet', 'tamam', 'olur', 'onayla', 'onaylıyorum', 'onayliyorum'}
_NO = re.compile(r'\b(?:hayır|hayir|iptal|vazgeç\w*|vazgec\w*|boşver|bosver|gönderme|gonderme|kapatma|düzenleme|duzenleme|onaylamıyorum|onaylamiyorum|istemiyorum|yapma)\b')


def decision(text, *, extra=()):
    normalized = re.sub(r'\s+', ' ', str(text).translate(str.maketrans('İI', 'iı')).lower()).strip(' .!?;:,')
    if _NO.search(normalized):
        return False
    if normalized in _YES or normalized in extra:
        return True
    return None
