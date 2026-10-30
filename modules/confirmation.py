"""Explicit user confirmation; mentioning protocol words is not a decision."""
import re

_YES = {'evet', 'tamam', 'olur', 'onayla', 'onaylıyorum', 'onayliyorum'}
_NO_EXACT = {
    'hayır', 'hayir', 'iptal', 'boşver', 'bosver', 'gönderme', 'gonderme',
    'kapatma', 'düzenleme', 'duzenleme', 'onaylamıyorum', 'onaylamiyorum',
    'istemiyorum', 'yapma',
}
_NO_WORD = (r'(?:hayır|hayir|iptal|boşver|bosver|gönderme|gonderme|kapatma|'
            r'düzenleme|duzenleme|onaylamıyorum|onaylamiyorum|istemiyorum|yapma|vazgeç\w*|vazgec\w*)')
_YES_WORD = r'(?:evet|tamam|olur|onayla|onaylıyorum|onayliyorum)'


def _negative(normalized):
    if normalized in _NO_EXACT or re.fullmatch(r'vazgeç\w*|vazgec\w*', normalized):
        return True
    if re.fullmatch(rf'{_YES_WORD}(?:\s+(?:ama|fakat|ancak))?\s+{_NO_WORD}', normalized):
        return True
    if re.fullmatch(rf'(?:hayır|hayir)\s+{_YES_WORD}', normalized):
        return True
    return False


def decision(text, *, extra=()):
    normalized = re.sub(r'\s+', ' ', str(text).translate(str.maketrans('İI', 'iı')).lower()).strip(' .!?;:,')
    normalized = re.sub(r'\s*[,;:]\s*', ' ', normalized)
    if _negative(normalized):
        return False
    if normalized in _YES or normalized in extra:
        return True
    return None
