"""Metin çevirisi isteği: tek dilbilgisi ve kaynak seçim kuralı.

Hem Brain (Understanding -> Core `translate`) hem eski komut zinciri (Live) bu kuralı kullanır; böylece
"hangi metin çevrilir" için ikinci bir karar yeri kalmaz. Saf fonksiyonlar: geçmiş/oturum/model okumaz."""
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from modules.turkish_text import lower
from modules import translation_targets

# The language alternation and the target registry come from translation_targets; this module owns
# only the command grammar and the source-selection rule.
_LANGUAGE_ALTERNATION = "|".join(sorted(translation_targets.command_names(), key=len, reverse=True))
# Yalnız başta/sonda komut; metin içindeki sıradan 'çeviri' sözcüğü komut sayılmaz.
_ACTION = (r"(?:(?:tam|tamamını|tümünü|metni|bu metni|bunu|yazdığımı|yazdigimi|önceki metni|son cevabını|son yanıtını|özeti)\s+)*"
           r"(?:(?:" + _LANGUAGE_ALTERNATION + r")(?:ye|ya|e|a)?\s+)?"
           r"(?:çevir(?:i)?|cevir(?:i)?|tercüme(?: et)?|translate)")
_START = re.compile(r"^" + _ACTION + r"\s*[:：\n]+\s*(.+)$", re.I | re.S)
_END = re.compile(r"(?:^|\s+)" + _ACTION + r"\s*[.!?]*$", re.I)
DEFAULT_TARGET = 'Kaynak Türkçe ise İngilizce; İngilizce ise Türkçe; diğer dillerde Türkçe'
_GENERIC_INLINE = ('metni', 'bu metni', 'bunu', 'tam', 'tamamını', 'yazdığımı', 'yazdigimi')
WINDOW = timedelta(hours=2)

ORIGIN_INLINE, ORIGIN_ASSISTANT, ORIGIN_USER = "inline", "assistant", "user"


def parts(command):
    """(komut ifadesi, satır içi metin) ya da None."""
    m = _START.match(command.strip())
    if m:
        return command[:m.start(1)], m.group(1).strip()
    m = _END.search(command.strip())
    if m:
        return m.group(0), command[:m.start()].strip()
    return None


def is_source(command):
    """Bu kullanıcı cümlesi çevrilebilecek özgün metin mi (komut/sohbet kapanışı değil)."""
    if not command.strip() or parts(command):
        return False
    if lower(command).strip(' .!?') in ('tamam', 'ok', 'teşekkürler', 'tesekkurler', 'dur', 'sus', 'yeter'):
        return False
    if re.search(r"^(?:ses|parlaklık|hava|kullanıcı|kullanici|kamera|ekran|git|ayar|not ekle|görev ekle)\b", command, re.I):
        return False
    if re.match(r'^\s*"[^"\n]+\.(?:pdf|docx|xlsx|txt)"', command, re.I):
        return False
    return True


@dataclass(frozen=True)
class Request:
    target: str
    inline: str
    wants_assistant: bool


def parse(command):
    """Çeviri isteği ise Request; para çevirisi ve gerçek dosya/format dönüşümü başkasına aittir (None)."""
    found = parts(command)
    if not found:
        return None
    instruction, inline = found
    low = unicodedata.normalize('NFKD', lower(instruction).replace('ı', 'i')).encode('ascii', 'ignore').decode()
    if re.search(r'\b(?:dosya\w*|belge\w*|pdf|word|excel|docx|xlsx)\b', lower(inline)) and len(inline) < 100:
        return None
    target = translation_targets.target_from_command(command) or DEFAULT_TARGET
    return Request(target=target, inline=inline, wants_assistant=bool(re.search(r'son (?:cevab|yanit)|ozet', low)))


# "X'e çevir" where X is not a language ("bunu tabloya çevir", "kodu pythona çevir", "bu fotoğrafı çevir",
# "ekrandaki yazıyı çevir") asks for another capability (table, codegen, photo, desktop). The legacy chain
# answered those BEFORE it reached translation; Brain must not take them first.
_OTHER_TARGET = re.compile(
    r"(?<!\w)(?:tablo\w*|grafik\w*|pdf\w*|excel\w*|word\w*|docx?\w*|xlsx?\w*|csv\w*|json\w*|html\w*|markdown\w*|"
    r"python\w*|java\w*|kod\w*|code\w*|ses\w*|sesli\w*|ses\s+dosya\w*|foto\w*|resim\w*|görsel\w*|gorsel\w*|"
    r"ekran\w*|pencere\w*)")


def non_text_target(command):
    """True when a short 'çevir' sentence names a non-language target/object; the other capability owns it."""
    return len(command) < 100 and _OTHER_TARGET.search(lower(command)) is not None


def pick_source(request, command, rows: Iterable[Mapping[str, Any]], now=None):
    """(metin, köken, satır id) ya da ('', None, None). rows: sıfırlama kesitinden sonraki geçmiş, eskiden yeniye.

    Son 2 saat; komutun kendisi kaynak olamaz. Satır içi metin her şeyden önce gelir."""
    cutoff = ((now or datetime.now()) - WINDOW).strftime('%Y-%m-%d %H:%M:%S')
    recent_rows = [r for r in rows if str(r.get('ts', '')) >= cutoff and str(r.get('text', '')).strip() != command.strip()]
    if request.wants_assistant:
        for row in reversed(recent_rows):
            if row.get('role') == 'assistant' and str(row.get('text', '')).strip():
                return row['text'], ORIGIN_ASSISTANT, row.get('id')
        return '', None, None
    if request.inline and lower(request.inline).strip(' .:') not in _GENERIC_INLINE:
        return request.inline, ORIGIN_INLINE, None
    # En son özgün kullanıcı metni kazanır (tek kelime/karakter dahil).
    for row in reversed(recent_rows):
        candidate = str(row.get('text', '')).strip()
        if row.get('role') != 'user':
            continue
        previous = parts(candidate)
        if previous and bool(previous[1]):
            return previous[1], ORIGIN_USER, row.get('id')
        if is_source(candidate):
            return candidate, ORIGIN_USER, row.get('id')
    return '', None, None
