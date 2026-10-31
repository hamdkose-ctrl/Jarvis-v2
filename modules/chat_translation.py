"""Metin çevirisi: açık komut ve kullanıcıya özel özgün metin bağlamı."""
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from modules.turkish_text import lower
from modules import conversation_reset

_sources = {}
# Sıfırlama kesiti conversation_reset'in sözlüğüdür (aynı nesne); eski adlar uyumluluk için durur.
_resets = conversation_reset._resets
_reset_file = conversation_reset._reset_file
from modules.translation_request import _ACTION, _START, _END, parts as _parts, is_source as _is_source  # noqa: F401  (eski adlar)

def reset(slug):
    _sources.pop(slug, None)
    conversation_reset.mark(slug, _resets, _reset_file)

def recent(slug, rows):
    return conversation_reset.recent(slug, rows, _resets)


def remember(slug, command):
    if not _is_source(command):
        return
    _sources[slug] = (datetime.now(), command.strip())


def resolve(slug, command, rows):
    """Eski komut zinciri (Live) için: kural translation_request'te, yalnız oturum önbelleği buradadır."""
    from modules import translation_request as tr
    request = tr.parse(command)
    if request is None:
        return None
    text, origin, _ = tr.pick_source(request, command, recent(slug, rows))
    if origin == tr.ORIGIN_INLINE:
        _sources[slug] = (datetime.now(), text)
    elif not text and not request.wants_assistant:
        cutoff = max(datetime.now() - timedelta(hours=2),
                     datetime.strptime(_resets[slug], '%Y-%m-%d %H:%M:%S.%f') if slug in _resets else datetime.min)
        cached = _sources.get(slug)
        text = cached[1] if cached and cached[0] >= cutoff else ''
    return text, request.target
