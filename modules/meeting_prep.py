"""Toplantı hazırlığı özeti: "toplantıma hazırlan", "sıradaki toplantım için hazırlık yap", "Ahmet'le görüşmeye hazırlan".

Yalnız okur ve modele hiçbir şey göndermez (model çağrısı yok, kota harcamaz): yaklaşan toplantıyı Jarvis kayıtlarından ve
(bağlıysa) Google Takvim'den bulur, başlıktaki ayırt edici sözcüklerle son 30 günün Gmail ve (kuruluysa) Outlook maillerinde
gönderen + konu eşleştirir. Mail gövdesi okunmaz, gönderilmez, taslak yazılmaz. Outlook takvimi okunmaz.
"""
import re
from datetime import datetime, timedelta

from modules import when as whenmod
from modules.diagnostics import record_failure as _record_failure

_FOLD = str.maketrans("çğıöşüâî", "cgiosuai")
_MEETING = re.compile(r"\b(?:toplanti|gorusme|sunum|kesif|randevu|meeting|call|demo|egitim|ders|mulakat|brifing)\w*")
_ASK_TOPIC = re.compile(r"\b(?:toplanti|gorusme|sunum|kesif|randevu|meeting|mulakat|brifing)\w*")
_PREP = re.compile(r"\b(?:hazirlan\w*|hazirlik\w*|brif\w*|hazirla\w*)\b")
_NOT = re.compile(r"\b(?:ekle|sil|kaldir|ertele|otele|kaydir|iptal|gonder|taslak|yaz)\w*|\bhatirlat\w*")
_STOP = set(("toplanti toplantisi toplantim toplantima toplantiya toplantiyi gorusme gorusmem gorusmeye gorusmesi sunum sunumu "
             "sunumum kesif kesfi randevu randevum meeting call demo egitim ders mulakat brifing haftalik gunluk aylik "
             "ile icin sonraki siradaki yaklasan benim bana hazirlan hazirlik hazirla yap bir ilgili ve bu su o").split())
_DAYS = 7
_MAIL_DAYS = 30


def _fold(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower().translate(_FOLD).replace("’", "'")


def _words(text: str) -> list[str]:
    """Başlıktaki ayırt edici sözcükler (ekler atılır: "Ahmet'le" -> "ahmet")."""
    out = []
    for w in re.findall(r"[a-z0-9]+", re.sub(r"'\w*", " ", _fold(text))):
        if len(w) >= 4 and w not in _STOP and w not in out:
            out.append(w)
    return out


def asked(cmd_lower: str) -> bool:
    f = _fold(cmd_lower.strip(" .!?"))
    return bool(_ASK_TOPIC.search(f) and _PREP.search(f) and not _NOT.search(f))


def _jarvis(profile, now) -> list[tuple[datetime, str, str]]:
    out = []
    for e in profile.data.get("events", []):
        when = str(e.get("when", ""))
        if len(when) != 16:
            continue                      # tüm gün kaydında saat yok
        try:
            at = datetime.strptime(when, "%Y-%m-%dT%H:%M")
        except ValueError:
            continue
        out.append((at, e.get("title", ""), "Jarvis kaydı"))
    return out


def _google(now) -> tuple[list[tuple[datetime, str, str]], str]:
    from modules import google_api
    if google_api._ready() is not None:
        return [], ""
    try:
        events = google_api.range_events(0, _DAYS + 1)
    except Exception:
        _record_failure('modules/meeting_prep.py:_google')
        return [], "Google Takvim'e bakamadım. "
    return [(w.replace(tzinfo=None) if w.tzinfo is None else w.astimezone().replace(tzinfo=None), name, "Google Takvim")
            for _d, w, name in events if w is not None], ""


def find_meeting(cmd_lower: str, profile, now) -> tuple[tuple | None, str]:
    """(en yakın toplantı (zaman, ad, kaynak) ya da None, uyarı metni)."""
    hint = _words(_PREP.sub(" ", _fold(cmd_lower)))
    cands, note = _jarvis(profile, now), ""
    more, gnote = _google(now)
    cands += more
    note += gnote
    lo, hi = now - timedelta(minutes=15), now + timedelta(days=_DAYS)
    pool = []
    for at, title, src in sorted(cands, key=lambda x: x[0]):
        if not lo <= at <= hi:
            continue
        f = _fold(title)
        if hint:
            if all(w[:5] in f for w in hint):
                pool.append((at, title, src))
        elif _MEETING.search(f):
            pool.append((at, title, src))
    return (pool[0] if pool else None), note


def _mail_lines(words: list[str]) -> tuple[list[str], str]:
    from modules import google_api, outlook
    lines, notes = [], ""
    if google_api._ready() is None:
        try:
            for m in google_api.search_mail(words, _MAIL_DAYS, 4):
                lines.append(f"Gmail: {m['who']} · {m['subject']} ({_ago(m['days'])})")
        except Exception:
            _record_failure('modules/meeting_prep.py:_mail_lines')
            notes += "Gmail'e bakamadım. "
    if outlook.installed():
        try:
            for m in outlook.search_recent(words, _MAIL_DAYS, 4):
                lines.append(f"Outlook: {m['who']} · {m['subject']} ({_ago(m['days'])})")
        except Exception:
            _record_failure('modules/meeting_prep.py:_mail_lines')
            notes += "Outlook'a bakamadım. "
    return lines, notes


def _ago(days: int) -> str:
    return "bugün" if days <= 0 else "dün" if days == 1 else f"{days} gün önce"


def handle_typed(profile, now, *, hint: str = "") -> str:
    """Model-selected read-only meeting worker; hint is validated by Core."""
    if not isinstance(hint, str) or len(hint) > 120 or any(ord(ch) < 32 for ch in hint):
        return "Toplantı hedefi doğrulanamadı; hiçbir mail okunmadı."
    return _render_meeting(hint, profile, now)


def handle(cmd_lower: str, profile, now) -> str | None:
    if not asked(cmd_lower):
        return None
    return _render_meeting(cmd_lower, profile, now)


def _render_meeting(cmd_lower: str, profile, now) -> str:
    from modules import requests_state
    requests_state.check()
    meeting, note = find_meeting(cmd_lower, profile, now)
    if meeting is None:
        return (note + f"Önümüzdeki {_DAYS} günde hazırlanacak bir toplantı görünmüyor "
                "(Jarvis kayıtların ve bağlıysa Google Takvim'in; Outlook takvimine bakmıyorum).").strip()
    at, title, src = meeting
    words = _words(title)
    head = f"Sıradaki toplantı: {whenmod.describe(at.strftime('%Y-%m-%dT%H:%M'), now)} · {title} ({src})."
    if not words:
        return f"{note}{head} Başlıkta mail aramaya yarayacak ayırt edici sözcük yok, o yüzden maillere bakmadım."
    lines, mnote = _mail_lines(words)
    if lines:
        body = f" Son {_MAIL_DAYS} günde \"{', '.join(words)}\" geçen mailler:\n- " + "\n- ".join(lines)
    else:
        body = f" Son {_MAIL_DAYS} günde \"{', '.join(words)}\" geçen mail bulamadım."
    return (f"{note}{mnote}{head}{body}\nMail içeriklerini okumadım, yalnız gönderen ve konuya baktım; hiçbir şey göndermedim. "
            "Outlook takvimine bakmıyorum.").strip()
