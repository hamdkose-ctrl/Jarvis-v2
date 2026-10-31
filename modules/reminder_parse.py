"""Single reminder-creation parser: Understanding proposes from it, the planner and Core both consume it.

Pure (no runtime, no state). Time words are parsed only by ``modules.when`` — this module never
adds a second time grammar. It only decides whether a sentence is a reminder *creation* request and
splits it into title / when / repeat."""
from __future__ import annotations

import re
from datetime import datetime

from modules import when as whenmod

_START = re.compile(r'^(?:takvime ekle|takvime not et|takvime yaz|hatırlat|bana hatırlat|bana .*hatırlat|randevu ekle|etkinlik ekle)\b')
_CALENDAR_TAIL = re.compile(r'\btakvime\s+(?:ekle|yaz|not et)\w*\s*$')
_REMIND = re.compile(r'\bhatırlat\w*\b')
_TIME_WORD = re.compile(
    r"\b(yarın|bugün|pazartesi|salı|çarşamba|perşembe|cuma|cumartesi|pazar|saat|gün sonra|saat sonra|dakika sonra|her\s|hergün|hafta\s*içi|"
    r"\d{1,2}[:.]\d{2}|\d{1,2}['’]?(?:da|de|ta|te)\b)")
_REPEAT_OK = re.compile(r'^(?:weekdays|daily|weekly:[0-6]|monthly:(?:[1-9]|[12]\d|3[01])|unknown)$')
_WHEN_OK = re.compile(r'^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?$')


def is_creation_request(command: str) -> bool:
    """Same sentence test the planner used inline: calendar/remind opener, or 'hatırlat' plus a time word."""
    tr = whenmod._turkish(command.replace('İ', 'i').replace('I', 'ı').lower())
    return bool(_CALENDAR_TAIL.search(tr) or _START.match(tr) or (_REMIND.search(tr) and _TIME_WORD.search(tr)))


_STRAY_APOSTROPHE = re.compile(r"(?:(?<=\s)|^)['’](?=\s|$)")


def _plain(text: str) -> str:
    """Whitespace and punctuation cleanup. A lone apostrophe is the leftover of a removed time suffix
    ("14:30'da" -> "'"); apostrophes inside words ("Ahmet'e") are kept."""
    text = _STRAY_APOSTROPHE.sub(' ', text)
    return re.sub(r'\s+', ' ', text).strip(' .,:;!-')


def parse(command: str, now: datetime | None = None) -> dict[str, str | None]:
    """{'title', 'when', 'repeat'}; 'repeat' may be 'unknown' (caller must refuse). 'when' None = ask."""
    now = now or datetime.now()
    body = re.sub(r'^(?:bana\s+)?(?:takvime (?:ekle|not et|yaz)|hat[ıi]rlat\w*|randevu ekle|etkinlik ekle)\s*[:,]?\s*', '', command, flags=re.I)
    body = re.sub(r'\b(?:diye\s+)?hat[ıi]rlat\w*\b|\b(?:için\s+)?takvime\s+(?:ekle|yaz|not et)\w*', '', body, flags=re.I)
    repeat, body = whenmod.parse_repeat(body)
    if repeat == 'unknown':
        return {'title': None, 'when': None, 'repeat': 'unknown'}
    when, title = whenmod.parse_when(body, now)
    title = re.sub('^(?:günü|gün|günleri)\\s+', '', _plain(title))
    if repeat:
        hhmm = when[11:16] if when and len(when) > 10 else '09:00'   # saat yoksa tüm gün kaydı gibi 09:00
        first = whenmod.next_occurrence(repeat, now, int(hhmm[:2]), int(hhmm[3:]))
        when = first.strftime('%Y-%m-%dT%H:%M')
    return {'title': title or None, 'when': when, 'repeat': repeat}


def valid_args(title: object, when: object, repeat: object) -> bool:
    """Shape check Core applies to Brain-proposed values (types, bounds, formats)."""
    if title is not None and (not isinstance(title, str) or len(title) > 200):
        return False
    if when is not None and (not isinstance(when, str) or _WHEN_OK.fullmatch(when) is None):
        return False
    if repeat is not None and (not isinstance(repeat, str) or _REPEAT_OK.fullmatch(repeat) is None):
        return False
    return True
