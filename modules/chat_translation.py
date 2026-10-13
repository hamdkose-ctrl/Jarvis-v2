"""Metin çevirisi: açık komut ve kullanıcıya özel özgün metin bağlamı."""
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from config import DATA_DIR
import json
import os
import threading
_lock = threading.RLock()
_reset_file = DATA_DIR / "chat_sessions.json"

_sources = {}
try:
    _resets = json.loads(_reset_file.read_text(encoding="utf-8"))
except (OSError, ValueError):
    _resets = {}
# Yalnız başta/sonda komut; metin içindeki sıradan 'çeviri' sözcüğü komut sayılmaz.
_ACTION = r"(?:(?:tam|tamamını|tümünü|metni|bu metni|bunu|yazdığımı|yazdigimi|önceki metni|son cevabını|son yanıtını|özeti)\s+)*(?:(?:türkçe|turkce|ingilizce|almanca|fransızca|arapça|rusça|ispanyolca)(?:ye|ya|e|a)?\s+)?(?:çevir(?:i)?|cevir(?:i)?|tercüme(?: et)?|translate)"
_START = re.compile(r"^" + _ACTION + r"\s*[:：\n]+\s*(.+)$", re.I | re.S)
_END = re.compile(r"(?:^|\s+)" + _ACTION + r"\s*[.!?]*$", re.I)


def reset(slug):
    _sources.pop(slug, None)
    with _lock:
        _resets[slug] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        tmp = _reset_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(_resets), encoding="utf-8")
        os.replace(tmp, _reset_file)

def recent(slug, rows):
    cutoff = _resets.get(slug, "")
    return [r for r in rows if str(r.get("ts", "")) > cutoff] if cutoff else rows


def _parts(command):
    m = _START.match(command.strip())
    if m:
        return command[:m.start(1)], m.group(1).strip()
    m = _END.search(command.strip())
    if m:
        return m.group(0), command[:m.start()].strip()
    return None


def _is_source(command):
    if not command.strip() or _parts(command):
        return False
    if command.lower().strip(' .!?') in ('tamam', 'ok', 'teşekkürler', 'tesekkurler', 'dur', 'sus', 'yeter'):
        return False
    if re.search(r"^(?:ses|parlaklık|hava|kullanıcı|kullanici|kamera|ekran|git|ayar|not ekle|görev ekle)\b", command, re.I):
        return False
    if re.match(r'^\s*"[^"\n]+\.(?:pdf|docx|xlsx|txt)"', command, re.I):
        return False
    return True


def remember(slug, command):
    if not _is_source(command):
        return
    _sources[slug] = (datetime.now(), command.strip())


def resolve(slug, command, rows):
    parts = _parts(command)
    if not parts:
        return None
    instruction, inline = parts
    low = unicodedata.normalize('NFKD', instruction.lower().replace('ı', 'i')).encode('ascii', 'ignore').decode()
    # Gerçek dosya ve format dönüşümü mevcut dosya işleyicisine aittir.
    if re.search(r'\b(?:dosya\w*|belge\w*|pdf|word|excel|docx|xlsx)\b', inline.lower()) and len(inline) < 100:
        return None
    target = next((label for key, label in [('turkce','Türkçe'),('ingilizce','İngilizce'),('almanca','Almanca'),('fransizca','Fransızca'),('arapca','Arapça'),('rusca','Rusça'),('ispanyolca','İspanyolca')] if key in low), '')
    target = target or 'Kaynak Türkçe ise İngilizce; İngilizce ise Türkçe; diğer dillerde Türkçe'
    cutoff = max(datetime.now()-timedelta(hours=2), datetime.strptime(_resets[slug], '%Y-%m-%d %H:%M:%S.%f') if slug in _resets else datetime.min)
    recent_rows = recent(slug, rows)
    recent_rows = [r for r in recent_rows if str(r.get('ts','')) >= cutoff.strftime('%Y-%m-%d %H:%M:%S') and r.get('text','').strip() != command.strip()]
    if re.search(r'son (?:cevab|yanit)|ozet', low):
        text = next((r['text'] for r in reversed(recent_rows) if r.get('role') == 'assistant'), '')
    elif inline and inline.lower().strip(' .:') not in ('metni','bu metni','bunu','tam','tamamını','yazdığımı','yazdigimi'):
        text = inline
        _sources[slug] = (datetime.now(), text)
    else:
        text = ''
        # The latest original user text wins, including a single word or character.
        # A cached older paragraph must never hide a newer source in history.
        for row in reversed(recent_rows):
            candidate = str(row.get('text','')).strip()
            if row.get('role') != 'user':
                continue
            previous = _parts(candidate)
            if previous and bool(previous[1]):
                text = previous[1]; break
            if _is_source(candidate):
                text = candidate; break
        if not text:
            cached = _sources.get(slug)
            text = cached[1] if cached and cached[0] >= cutoff else ''
    return text, target
