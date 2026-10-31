"""Explicit user confirmation; mentioning protocol words is not a decision."""
import re

_YES = {'evet', 'tamam', 'olur', 'onayla', 'onaylıyorum', 'onayliyorum'}
_NO_EXACT = {
    'hayır', 'hayir', 'iptal', 'boşver', 'bosver', 'gönderme', 'gonderme',
    'kapatma', 'düzenleme', 'duzenleme', 'onaylamıyorum', 'onaylamiyorum',
    'istemiyorum', 'yapma',
}
_NO_WORD = r'(?:hayır|hayir|iptal|boşver|bosver|gönderme|gonderme|kapatma|düzenleme|duzenleme|onaylamıyorum|onaylamiyorum|istemiyorum|yapma|vazgeç\w*|vazgec\w*)'
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


def choice_index(answer, choices):
    """Pick exactly one offered choice by 1-based number, exact title or unique substring; else None.

    Single definition shared by the Brain state gate (recognition) and Core resume (execution)."""
    text = str(answer).casefold().strip(' .!?')
    choices = [str(c) for c in (choices or [])]
    if text.isdigit() and 1 <= int(text) <= len(choices):
        return int(text) - 1
    exact = [i for i, c in enumerate(choices) if c.casefold().strip() == text]
    if len(exact) == 1:
        return exact[0]
    if len(text) >= 3:
        part = [i for i, c in enumerate(choices) if text in c.casefold()]
        if len(part) == 1:
            return part[0]
    return None
