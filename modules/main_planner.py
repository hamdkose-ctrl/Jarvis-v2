"""Focused runtime actions with explicitly injected dependencies."""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import json
import hashlib
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from modules import reminder_parse

def _plain(runtime, text: str) -> str:
    return runtime.re.sub('\\s+', ' ', text).strip(' .,:;!-')

def _note_text(runtime, command: str, cmd_lower: str) -> str:
    """Komut bir not isteğiyse notun metnini döndürür: "Not pazartesi ekip gelecek", "not ekle …", "… diye not al"."""
    m = runtime._NOTE_HEAD.match(cmd_lower.strip())
    if m:
        body = m.group(1)
        if runtime.re.match('(?:defter|listesi|lar|ları|larım)\\b', body):
            return ''
        text = runtime._plain(command.strip()[len(command.strip()) - len(body):])
        if cmd_lower.startswith('hatırlatma'):
            text = 'Hatırlatma: ' + runtime.re.sub('^(?:ve|ile|da|de)\\s+', '', text, flags=runtime.re.I)
        return text
    m = runtime._NOTE_TAIL.match(cmd_lower.strip())
    if m and len(m.group(1).split()) >= 2:
        return runtime._plain(command.strip()[:len(m.group(1))])
    return ''

def _add_note(runtime, text: str, photo: str | None=None) -> dict:
    item = runtime.profile.add_note_item(text + (' 📷' if photo else ''))
    if photo:
        item['photo'] = photo
        runtime.profile.save()
    runtime._last_note[runtime.profile.slug] = runtime.time.time()
    return item

def _fix_word(runtime, text: str, right: str) -> str | None:
    """Son nottaki, doğru yazılışa en çok benzeyen kelimeyi düzeltir ("israliyesini" + "irsaliye" -> "irsaliyesini")."""
    words, rl = (text.split(), runtime._tr_lower(right))
    best, bi = (0.0, -1)
    for i, w in enumerate(words):
        r = runtime.difflib.SequenceMatcher(None, rl, runtime._tr_lower(w)[:len(rl)]).ratio()
        if r > best:
            best, bi = (r, i)
    if best < 0.6:
        return None
    w = words[bi]
    new = right if not w[:1].islower() else runtime._tr_lower(right)
    words[bi] = new + (w[len(right):] if len(w) > len(right) else '')
    return ' '.join(words)

def _note_fix(runtime, command: str, cmd_lower: str) -> str | None:
    """Son notu sil / düzelt. Kısa düzeltmeler ("X olarak değiştir", "X değil Y") yalnızca nottan hemen sonra (15 dk)."""
    items = runtime.profile.data['items']
    if not items:
        return None
    last = items[-1]
    cl = cmd_lower.strip(' .!?')
    if runtime.re.fullmatch('son not(?:u|umu)?\\s+(?:sil|kaldır|iptal et)', cl):
        runtime.profile.delete_note_item(last['id'])
        return f"Son notu sildim: {last['text']}"
    m = runtime.re.match('^son not(?:u|umu)?\\s+(?:düzelt|değiştir)\\w*\\s*[:,]?\\s+(.+)$', cl)
    if m:
        last['text'] = runtime._plain(command.strip()[len(command.strip()) - len(m.group(1)):])
        runtime.profile.save()
        return f"Son notu düzelttim: {last['text']}"
    if runtime.time.time() - runtime._last_note.get(runtime.profile.slug, 0) > 900:
        return None
    m = runtime.re.match('^(?:yanlış oldu\\s+|doğrusu\\s+|hayır\\s+)?(.+?)\\s+(?:olarak|diye)\\s+(?:değiştir|düzelt)\\w*$', cl) or runtime.re.match('^(?:yanlış oldu|doğrusu|yanlış yazdın)[\\s:,]+(.+)$', cl)
    loose = None if m else runtime.re.match('^(?:.+?)\\s+değil[\\s,]+(.+?)(?:\\s+(?:olacak|olsun|yaz))?$', cl)
    if not (m or loose):
        return None
    right = (m or loose).group(1).strip()
    if ' ' in right:
        return None
    new = runtime._fix_word(last['text'], right)
    if not new and loose:
        return None
    if not new:
        return f"Son notta “{right}” kelimesine benzeyen bir yer bulamadım. Not şu an: {last['text']}. “Son notu düzelt: …” diyerek tamamını yeniden yazabilirsin."
    last['text'] = new
    runtime.profile.save()
    runtime._last_note[runtime.profile.slug] = runtime.time.time()
    return f'Düzelttim: {new}'

def _notes_text(runtime) -> str:
    items = runtime.profile.data['items']
    if not items:
        return 'Not defterin boş.'
    return 'Notların: ' + '; '.join((f"{i}) {n['text']}" for i, n in enumerate(items, 1)))

def _agenda_text(runtime, day: str, label: str) -> str:
    """O günün programı: Jarvis'in kendi takvimi + (bağlıysa) Google Takvim. "Takvimimde ne var" sorusu önce
    yalnızca Jarvis'in takvimine bakıyordu; Google Takvim'deki etkinlikler hiç söylenmiyordu."""
    evs = runtime.profile.events_on(day)
    parts = [(e['when'][11:16] + ' ' if len(e['when']) > 10 else '') + e['title'] for e in evs]
    google = ''
    try:
        if runtime.google_api._ready() is None:
            offset = (runtime.datetime.strptime(day, '%Y-%m-%d').date() - runtime.datetime.now().date()).days
            google = runtime.google_api.agenda(offset, label)
    except Exception:
        _record_failure('main.py:_agenda_text')
    g_empty = not google or 'etkinlik yok' in google
    if not parts and g_empty:
        return f'{label} için takviminde bir şey yok' + (" (Google Takvim'e de baktım)." if google else '.')
    out = []
    if parts:
        out.append(f'{label}: ' + '; '.join(parts) + '.')
    if google and (not g_empty):
        out.append(google)
    return ' '.join(out)

_MONTHS_TR = ('Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık')
_DAYS_TR = ('Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar')
# "bugünün planı", "bugün ne yapmalıyım", "günümü planla", "yarın planım ne" (ASCII yazım da)
# Eşleşme ASCII'ye indirilmiş metinde yapılır (`_fold`): "bugunun plani", "yarinki plan", "bugun ne yapmaliyim" da çalışır.
_PLAN_ASK = re.compile(r"\b(?:bugun(?:un|ku)?|yarin(?:in|ki)?|gunun|gunumun|gunluk)\s+plan\w*(?!\s+yap)|\bgunumu\s+planla\w*|"
                       r"^plani?m(?:i\s+(?:soyle|goster|oku)\w*|\s+ne(?:dir)?)?\s*[?.!]*$|"
                       r"\b(?:bugun|yarin)\s+ne(?:ler)?\s+(?:yapmaliyim|yapacagim|yapmam\s+lazim)")


def _ago(minutes: int) -> str:
    h, m = divmod(max(minutes, 0), 60)
    return ' '.join(x for x in (f'{h} saat' if h else '', f'{m} dakika' if m or not h else '') if x)


def _day_plan(runtime, offset: int = 0) -> str:
    """Modelsiz günlük plan: takvim (Jarvis + Google), sıradaki iş, gecikmiş/bugünkü görevler, okunmamış mail sayısı.

    Model çağrılmaz (kota harcamaz); Google yalnız okunur. Okunamayan kaynak cevabın içinde açıkça söylenir."""
    from datetime import timedelta
    from modules import google_api as _google_api
    now = runtime.datetime.now()
    day = (now + timedelta(days=offset)).date()
    label = 'Bugünün' if offset == 0 else 'Yarının'
    head = f'{label} planı ({day.day} {_MONTHS_TR[day.month - 1]} {_DAYS_TR[day.weekday()]}).'
    items, problems, reconnect = [], [], False
    for e in runtime.profile.events_on(day.strftime('%Y-%m-%d')):
        hhmm = e['when'][11:16] if len(e['when']) > 10 else ''
        items.append((hhmm, e['title']))
    try:
        if runtime.google_api.connected():
            for start, name in runtime.google_api.day_events(offset):
                # Google etkinliği, kullanıcının takvim saat diliminde gelir; çalışan
                # makinenin yerel saat dilimine çevirmek planı ve eşsizleştirmeyi bozar.
                items.append((start.strftime('%H:%M') if start else '', name))
    except Exception as exc:
        _record_failure('main.py:_day_plan')
        problems.append("Google Takvim'e bakamadım")
        reconnect = reconnect or _google_api.needs_reconnect(exc)
    seen, timed, allday = set(), [], []
    for hhmm, name in sorted(items, key=lambda x: (x[0] or '', x[1])):
        key = (hhmm, name.strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        (timed if hhmm else allday).append((hhmm, name))
    parts = [head]
    cur = now.strftime('%H:%M')
    if timed or allday:
        cal = [f"{h} {n}" + (' (geçti)' if offset == 0 and h < cur else '') for h, n in timed]
        cal += [f'tüm gün {n}' for _, n in allday]
        parts.append('Takvim: ' + '; '.join(cal) + '.')
        nxt = next(((h, n) for h, n in timed if offset or h >= cur), None)
        if nxt and offset == 0:
            mins = int(nxt[0][:2]) * 60 + int(nxt[0][3:]) - (now.hour * 60 + now.minute)
            parts.append(f'Sıradaki: {nxt[0]} {nxt[1]}, ' + (f'{_ago(mins)} sonra.' if mins > 0 else 'şimdi.'))
    else:
        parts.append('Takviminde bir şey yok.')
    late, carry, today, other = [], [], [], []
    real_today = now.date().isoformat()
    for t in runtime.profile.data.get('tasks', []):
        if t.get('done'):
            continue
        d = str(t.get('when') or '')[:10]
        if d and d < real_today:
            late.append(t['text'])
        elif d and d < day.isoformat():       # yarının planında: bugün bitmezse yarına kalacaklar (henüz gecikmiş değil)
            carry.append(t['text'])
        elif d == day.isoformat():
            today.append(t['text'])
        else:
            other.append(t['text'])
    task = []
    if late:
        task.append(f"{len(late)} gecikmiş ({', '.join(late[:3])})")
    if carry:
        task.append(f"bugün bitmezse yarına kalır {len(carry)} ({', '.join(carry[:3])})")
    if today:
        task.append(f"{'bugün' if offset == 0 else 'yarın'} {len(today)} ({', '.join(today[:3])})")
    if other:
        task.append(f'ayrıca {len(other)} açık görev')
    if task:
        parts.append('Görevler: ' + ', '.join(task) + '.')
    if offset == 0:
        try:
            if runtime.google_api.connected():
                n = runtime.google_api.unread_count()
                parts.append(f"Gmail'de {n} okunmamış mail var." if n else "Gmail'de okunmamış mail yok.")
        except Exception as exc:
            _record_failure('main.py:_day_plan')
            problems.append("Gmail'e bakamadım")
            reconnect = reconnect or _google_api.needs_reconnect(exc)
        try:
            from modules import handoff
            line, trouble = handoff.brief_status()
            if line:
                parts.append(line)
            elif trouble:
                parts.append(trouble if trouble.startswith('Devir') else f'Devir notlarına bakamadım: {trouble}')
        except Exception:
            _record_failure('main.py:_day_plan')
    if problems:
        parts.append(' ve '.join(problems) + '.')
        if reconnect:                         # Takvim ve Gmail aynı izni kullanır: neden ve çare tek kez söylenir
            parts.append(_google_api.reconnect_help())
    return ' '.join(parts)


# "bu haftam nasıl", "haftaya ne var", "gelecek haftanın planı", "önümüzdeki 7 gün": ileriye dönük hafta planı (modelsiz).
_WEEK_ASK = re.compile(r"\bbu\s+haft\w*\s+(?:nasil|ne\s+var|neler\s+var|plan\w*|program\w*|ajanda\w*|takvim\w*)|"
                       r"\b(?:gelecek|onumuzdeki)\s+haft\w*\s+(?:nasil|ne\s+var|neler\s+var|plan\w*|program\w*|ajanda\w*|takvim\w*)|"
                       r"\bhaftaya\s+(?:ne|neler)\s+(?:var|yapiyoruz|yapacagiz|yapiyorum)|"
                       r"\bhaftalik\s+plan\w*|\bhaftam(?:i)?\s+(?:soyle|goster|oku|plan)\w*|\bhafta\s+plan\w*|"
                       r"\bonumuzdeki\s+(?:7|yedi)\s+gun\w*")
_WEEK_NOT = re.compile(r"\b(?:ozet\w*|oldu\w*|dondu\w*|gecti\w*|rapor\w*|yap|yapin|yapar\w*|hazirla\w*|olustur\w*|hatirlat\w*|ekle\w*)\b")


def _week_range(f: str) -> str | None:
    """Folded metin hafta planı isteğiyse 'this' | 'next' | 'seven', değilse None (geçmişi anlatan özet/rapor değil)."""
    if not _WEEK_ASK.search(f) or _WEEK_NOT.search(f):
        return None
    if re.search(r"\bonumuzdeki\s+(?:7|yedi)\s+gun", f):
        return 'seven'
    return 'next' if re.search(r"\b(?:gelecek|onumuzdeki)\s+haft|\bhaftaya\b", f) else 'this'


def _week_plan(runtime, kind: str) -> str:
    """Modelsiz hafta planı: gün gün takvim (Jarvis + Google), çakışma uyarısı, boş günler, görevler. Google yalnız okunur."""
    from datetime import timedelta
    from modules import google_api as _google_api
    now = runtime.datetime.now()
    today = now.date()
    wd = today.weekday()
    if kind == 'this':
        start, days, title, note = today, 7 - wd, 'Bu hafta', ', bugünden pazara'
    elif kind == 'next':
        start, days, title, note = today + timedelta(days=7 - wd), 7, 'Gelecek hafta', ''
    else:
        start, days, title, note = today, 7, 'Önümüzdeki 7 gün', ''
    end = start + timedelta(days=days - 1)
    span = (f'{start.day}–{end.day} {_MONTHS_TR[end.month - 1]}' if start.month == end.month
            else f'{start.day} {_MONTHS_TR[start.month - 1]}–{end.day} {_MONTHS_TR[end.month - 1]}')
    parts = [f'{title} planı ({span}{note}).']
    per_day = {start + timedelta(days=i): [] for i in range(days)}
    for d in per_day:
        for e in runtime.profile.events_on(d.isoformat()):
            per_day[d].append((e['when'][11:16] if len(e['when']) > 10 else '', e['title']))
    problems, reconnect = [], False
    try:
        if runtime.google_api.connected():
            for d, when, name in runtime.google_api.range_events((start - today).days, days):
                if d in per_day:
                    per_day[d].append((when.strftime('%H:%M') if when else '', name))
    except Exception as exc:
        _record_failure('main.py:_week_plan')
        problems.append("Google Takvim'e bakamadım")
        reconnect = _google_api.needs_reconnect(exc)
    cur = now.strftime('%H:%M')
    lines, empty, clashes, busiest = [], [], [], None
    for d, items in per_day.items():
        seen, timed, allday = set(), [], []
        for hhmm, name in sorted(items, key=lambda x: (x[0] or '', x[1])):
            key = (hhmm, name.strip().casefold())
            if key in seen:
                continue
            seen.add(key)
            (timed if hhmm else allday).append((hhmm, name))
        if not timed and not allday:
            empty.append(_DAYS_TR[d.weekday()])
            continue
        texts = [f"{h} {n}" + (' (geçti)' if d == today and h < cur else '') for h, n in timed] + \
                [f'tüm gün {n}' for _, n in allday]
        lines.append(f"{_DAYS_TR[d.weekday()]} {d.day} {_MONTHS_TR[d.month - 1]}: " + '; '.join(texts) + '.')
        for (h1, n1), (h2, n2) in zip(timed, timed[1:]):
            if int(h2[:2]) * 60 + int(h2[3:]) - (int(h1[:2]) * 60 + int(h1[3:])) < 30:
                clashes.append(f'{d.day} {_MONTHS_TR[d.month - 1]} {h1} {n1} ile {h2} {n2}')
        if len(timed) + len(allday) >= 4 and (busiest is None or len(timed) + len(allday) > busiest[0]):
            busiest = (len(timed) + len(allday), f"{_DAYS_TR[d.weekday()]} {d.day} {_MONTHS_TR[d.month - 1]}")
    if lines:
        parts.extend(lines)
        if empty:
            parts.append('Boş günler: ' + ', '.join(empty) + '.')
    else:
        parts.append('Bu aralıkta takviminde bir şey yok.')
    if clashes:
        parts.append('Çakışabilir: ' + '; '.join(clashes[:3]) + '.')
    if busiest:
        parts.append(f'En yoğun gün: {busiest[1]} ({busiest[0]} kayıt).')
    late, dated, undated = [], [], 0
    for t in runtime.profile.data.get('tasks', []):
        if t.get('done'):
            continue
        d = str(t.get('when') or '')[:10]
        if d and d < today.isoformat():
            late.append(t['text'])
        elif d and start.isoformat() <= d <= end.isoformat():
            dd = datetime.strptime(d, '%Y-%m-%d')
            dated.append(f"{t['text']} {dd.day} {_MONTHS_TR[dd.month - 1]}")
        else:
            undated += 1
    task = []
    if late:
        task.append(f"{len(late)} gecikmiş ({', '.join(late[:3])})")
    if dated:
        task.append(f"bu aralıkta {len(dated)} ({', '.join(dated[:4])})")
    if undated:
        task.append(f'ayrıca {undated} açık görev')
    if task:
        parts.append('Görevler: ' + ', '.join(task) + '.')
    if problems:
        parts.append(' ve '.join(problems) + '.')
        if reconnect:
            parts.append(_google_api.reconnect_help())
    return ' '.join(parts)



def _add_event(runtime, title: str, when: str) -> str:
    runtime.profile.add_event(title, when)
    return f'Takvime ekledim: {title}, {runtime.whenmod.describe(when)}.'

def _conflicts(runtime, when: str) -> list[str]:
    """Aynı saatte (±30 dk) Jarvis kaydı ya da Google Takvim toplantısı. Tüm gün kayıtta çakışma sorulmaz."""
    if len(when) <= 10:
        return []
    from datetime import datetime, timedelta
    start = datetime.strptime(when, '%Y-%m-%dT%H:%M')
    window = timedelta(minutes=30)
    out = []
    days = {(start - window).date(), start.date(), (start + window).date()}
    for day in sorted(days):
        for e in runtime.profile.events_on(day.isoformat()):      # tekrarlayan kayıtların o günkü oluşumları dahil
            raw = str(e.get('when') or '')
            try:
                t = datetime.strptime(raw, '%Y-%m-%dT%H:%M')
            except ValueError:
                continue
            if abs(t - start) < window:
                out.append(f"{raw[11:16]} {e.get('title', '')}".strip())
    try:
        for a, _b, name in runtime.google_api.busy_between(start - window + timedelta(minutes=1), start + window):
            out.append(f"{a.strftime('%H:%M')} {name} (Google Takvim)")
    except Exception:
        _record_failure('main.py:_conflicts')
    return out

def _save_reminder(runtime, title: str, when: str, repeat: str | None) -> str:
    if repeat:
        runtime.profile.add_event(title, when, repeat=repeat)
        hhmm = when[11:16]
        rule = runtime.whenmod.describe_repeat(repeat, int(hhmm[:2]), int(hhmm[3:]))
        return f'Tamam, {rule} hatırlatacağım: {title}. İlki {runtime.whenmod.describe(when)}.'
    return runtime._add_event(title, when)

def _reminder_or_confirm(runtime, title: str, when: str, repeat: str | None = None) -> str:
    """Çakışma varsa eklemeden önce sorar; cevap pending_event_title üzerinden gelir."""
    clash = _conflicts(runtime, when)
    if clash:
        runtime._session().pending_event_title = {'confirm': (title, when, repeat)}
        return (f"{runtime.whenmod.describe(when)} saatinde zaten şu var: {'; '.join(clash[:3])}. "
                f"'{title}' kaydını yine de ekleyeyim mi?")
    return _save_reminder(runtime, title, when, repeat)

def _hoca_assignment_reminder(runtime, course_id: int, assignment_id: int, time: str = '09:00') -> str:
    """Hoca'nın bir ödevini/deadline'ını hatırlatma olarak takvime ekler (5. adım, Hamdi'nin
    kararı: mail-takvim.md'deki mevcut çakışma-sorma hattı (`_reminder_or_confirm`) aynen
    kullanılır, Hoca'ya özel ayrı bir onay kuralı yazılmaz). Henüz bir sohbet komutuna/ekrana
    bağlı değil; UI/komut yazılınca bu fonksiyon çağrılacak."""
    from modules import hoca_workspace
    assignment = hoca_workspace.get_assignment(runtime.profile, course_id, assignment_id)
    hhmm = time if re.fullmatch(r'\d{2}:\d{2}', time or '') else '09:00'
    when = f"{assignment.get('due', '')}T{hhmm}"
    try:
        datetime.strptime(when, '%Y-%m-%dT%H:%M')
    except ValueError:
        raise hoca_workspace.HocaWorkspaceError(
            f"'{assignment['title']}' ödevinin geçerli bir tarihi yok (YYYY-MM-DD biçiminde olmalı).")
    return _reminder_or_confirm(runtime, assignment['title'], when)

_FOLD = str.maketrans('çğıöşüâî', 'cgiosuai')


def _fold(text: str) -> str:
    """Küçük harf + Türkçe harfsiz (ASCII) biçim: "Hatırlatmasını" ve "hatirlatmasini" aynı olur."""
    return text.replace('İ', 'i').replace('I', 'ı').lower().translate(_FOLD)


_EDIT_ASK = re.compile(r"\b(?:sil|kaldir|iptal|ertele|otele|kaydir)\w*|\batla\b|\batlar\s+misin|\batlayabilir")
_EDIT_TOPIC = re.compile(r"\b(?:hatirlat|etkinli|randevu|takvim)\w*")
_NUM = {"bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "on": 10, "yirmi": 20, "otuz": 30}
_DAYS_FOLD = {"pazartesi": 0, "sali": 1, "carsamba": 2, "persembe": 3, "cuma": 4, "cumartesi": 5, "pazar": 6}
_DAY_TO = r"\b(cumartesi|cuma|pazartesi|pazar|sali|carsamba|persembe)(?:ya|ye|a|e)?\b"
_EDIT_NOISE = (r"hatirlat\w*|etkinli\w*|randevu\w*|takvim\w*|sil\w*|kaldir\w*|iptal\w*|et|ertele\w*|otele\w*|bana|su|bu|"
               r"son|ekledigim|ekledi\w*|lutfen|ve|\d+|dakika\w*|dk|saat\w*|gun\w*|yarin\w*|haftaya|bir|iki|uc|bes|on|"
               r"yarim|ceyrek|dort|yirmi|otuz|bugun\w*|hafta\w*|seferlik|sadece|sonraki|atla\w*|kaydir\w*|"
               r"(?:cumartesi|cuma|pazartesi|pazar|sali|carsamba|persembe)(?:ya|ye|a|e)?|beni|bunu")

_DUR = r"(?:\d+|bir|iki|uc|dort|bes|on|yirmi|otuz)\s*(?:dakika|dk|saat)\w*|yarim saat|ceyrek saat"
_DAYPART = re.compile(r"\b(sabah|ogleden sonra|oglen|aksam|gece)\w*")
_DAYPART_HOUR = {"sabah": 9, "ogleden sonra": 14, "oglen": 12, "aksam": 18, "gece": 21}
_DAYPART_TR = {"sabah": "sabah", "ogleden sonra": "öğleden sonra", "oglen": "öğle", "aksam": "akşam", "gece": "gece"}
_SNOOZE_SAY = re.compile(r"(?:(?P<dur>" + _DUR + r")\s+sonra\s+|(?:biraz|daha)\s+sonra\s+)?"
                         r"(?:tekrar|yine|bir daha|yeniden)\s+(?:cal|hatirlat|uyar)\w*")
_SNOOZE_BARE = re.compile(r"^(?:lutfen\s+)?(?:(?:biraz|daha)\s+)?sonra\s+(?:tekrar\s+)?(?:hatirlat|cal|uyar)\w*$")
_DAYPART_BARE = re.compile(r"^(?:lutfen\s+)?(?:yarin\s+)?(?:sabah|ogleden sonra|oglen|aksam|gece)\w*\s+(?:tekrar\s+)?hatirlat\w*$")


def _say_to_postpone(tr: str) -> str:
    """Erteleme sözü olmayan söyleyişleri ("10 dk sonra tekrar çal", "daha sonra hatırlat", "yarın sabah hatırlat")
    mevcut erteleme yoluna çevirir; "… dk sonra hatırlat" (tekrar/yine yok) yeni hatırlatma eklemedir, buraya girmez."""
    if re.search(r"\b(?:ertele|otele)", tr):
        return tr
    t = tr.strip(" .!?")
    if _SNOOZE_BARE.match(t):
        return "ertele"
    if _DAYPART_BARE.match(t):
        return re.sub(r"\s+", " ", re.sub(r"\btekrar\b", " ", re.sub(r"\b(?:hatirlat|cal|uyar)\w*", "ertele", t))).strip()
    m = _SNOOZE_SAY.search(t)
    if m:
        return (t[:m.start()] + " " + (m.group("dur") or "") + " ertele " + t[m.end():]).strip()
    return tr


def _daypart_time(tr: str, now):
    """"sabaha/akşama/öğleden sonraya": (zaman, söz). "yarın" varsa yarın, yoksa bugün (saat geçtiyse yarın)."""
    from datetime import timedelta
    m = _DAYPART.search(tr)
    if not m:
        return None
    new = now.replace(hour=_DAYPART_HOUR[m.group(1)], minute=0, second=0, microsecond=0)
    if re.search(r"\byarin", tr):
        new += timedelta(days=1)
    elif new <= now:
        new += timedelta(days=1)
    return new, _DAYPART_TR[m.group(1)]


def _hint(runtime, tr: str) -> str:
    hint = runtime.re.sub(r"\b(?:" + _EDIT_NOISE + r")\b", " ", tr)
    return runtime.re.sub(r"\s+", " ", hint).strip(" ,.:-'’")


def _word_in(w: str, title: str) -> bool:
    """Başlık ipucu eşleşmesi: kelimenin ilk 5 harfi; "ilacı"/"ilaç" gibi tamlama ünlüsü de kabul."""
    return w[:5] in title or (len(w) > 3 and w[-1] in "iuae" and w[:-1] in title)


def _title_hits(runtime, tr: str) -> list:
    hint = _hint(runtime, tr)
    if not hint:
        return []
    return [e for e in runtime.profile.data['events'] if all(_word_in(w, _fold(e['title'])) for w in hint.split())]


def _edit_target(runtime, tr: str, delete: bool, pool=None):
    """(kayıt, mesaj): komuttaki başlık ipucuna göre tek kayıt; belirsizse kayıt None ve soru mesajı."""
    events = list(pool if pool is not None else runtime.profile.data['events'])
    if not events:
        return None, 'Kayıtlı bir hatırlatman yok.'
    hint = _hint(runtime, tr)
    if hint:
        hits = [e for e in events if all(_word_in(w, _fold(e['title'])) for w in hint.split())]
        if not hits:
            return None, f"'{hint}' adında bir kaydın yok."
    elif pool is not None:
        hits = events
    elif runtime.re.search(r"\bson\b", tr) and delete:
        hits = [max(events, key=lambda e: e['id'])]
    elif not delete:
        done = sorted((e for e in events if (e.get('notified') and not e.get('repeat')) or (e.get('repeat') and e.get('fired'))),
                      key=lambda e: e['fired'] if e.get('repeat') else e['when'], reverse=True)
        single = [e for e in events if not e.get('repeat')]
        hits = done[:1] or (single if len(single) == 1 else [])
    else:
        hits = events if len(events) == 1 else []
    if len(hits) == 1:
        return hits[0], ''
    pool = hits or events
    shown = '; '.join(f"{runtime.whenmod.describe(e['when'])} {e['title']}" for e in sorted(pool, key=lambda e: e['when'])[:5])
    return None, f"Hangisini kastettin? Kayıtların: {shown}. Başlığını söyleyerek tekrar dene."


def _recently_fired(ev: dict, now) -> bool:
    from datetime import datetime
    try:
        return 0 <= (now - datetime.strptime(str(ev.get('fired')), '%Y-%m-%dT%H:%M')).total_seconds() < 6 * 3600
    except ValueError:
        return False


def _snooze_repeating(runtime, ev: dict, tr: str, now) -> str | None:
    """Az önce çalan tekrarlayan hatırlatma: "10 dakika sonra tekrar çal". Gün/hafta/gün adı dendiyse None (sıradaki oluşum kayar)."""
    from datetime import timedelta
    if runtime.re.search(r"\bhaftaya\b|\byarin|" + _DAY_TO, tr):
        return None
    dp = _daypart_time(tr, now)
    if dp:
        runtime.profile.snooze_event(ev['id'], dp[0].strftime('%Y-%m-%dT%H:%M'))
        return (f"{ev['title']} için {dp[0].strftime('%H:%M')} ({dp[1]}) yeniden hatırlatacağım. "
                f"Sıradaki normal tekrar değişmedi: {runtime.whenmod.describe(ev['when'], now)}.")
    mm = runtime.re.search(r"\b(\d+|bir|iki|uc|dort|bes|on|yirmi|otuz)\s*(dakika|dk|saat|gun)\w*", tr)
    if runtime.re.search(r"yarim saat", tr):
        n, unit = 30, 'dakika'
    elif runtime.re.search(r"ceyrek saat", tr):
        n, unit = 15, 'dakika'
    elif mm:
        n = int(mm.group(1)) if mm.group(1).isdigit() else _NUM[mm.group(1)]
        unit = {'dakika': 'dakika', 'dk': 'dakika', 'saat': 'saat', 'gun': 'gün'}[mm.group(2)]
    else:
        n, unit = 10, 'dakika'
    if unit == 'gün':
        return None
    if not 1 <= n <= 1000:
        return 'Bu süreyi anlayamadım; "10 dakika" ya da "1 saat" gibi söyle.'
    at = now + (timedelta(minutes=n) if unit == 'dakika' else timedelta(hours=n))
    runtime.profile.snooze_event(ev['id'], at.strftime('%Y-%m-%dT%H:%M'))
    return (f"{ev['title']} için {n} {unit} sonra yeniden hatırlatacağım ({at.strftime('%H:%M')}). "
            f"Sıradaki normal tekrar değişmedi: {runtime.whenmod.describe(ev['when'], now)}.")


def _edit_repeating(runtime, ev: dict, new_when, said: str, verb: str, now) -> str:
    """Tekrarlayan kaydın yalnız sıradaki oluşumunu kaydırır; kural ve sonraki oluşumların saati değişmez."""
    from datetime import datetime
    cur = datetime.strptime(str(ev['when'])[:16], '%Y-%m-%dT%H:%M')
    base = ev.get('base') or cur.strftime('%H:%M')
    out = new_when.strftime('%Y-%m-%dT%H:%M')
    runtime.profile.reschedule_event(ev['id'], out, base=None if out[11:16] == base else base)
    after = datetime.combine(cur.date(), datetime.strptime(base, '%H:%M').time())
    following = runtime.whenmod.next_occurrence(ev['repeat'], after, int(base[:2]), int(base[3:]))
    msg = f"{ev['title']} kaydının sıradaki tekrarını {said} {verb}: {runtime.whenmod.describe(out, now)}."
    if out[11:16] != base:
        msg += f" Sonraki tekrarlar eski saatinde ({base}) kalır."
    if new_when.date() > following.date():
        msg += ' Aradaki tekrarlar bu sefer çalmaz.'
    return msg


def _edit_reminder(runtime, text: str, now) -> str | None:
    """Hatırlatma silme, erteleme, kaydırma ve atlama: "ilaç hatırlatmasını sil", "toplantıyı yarına ertele",
    "yarınki hatırlatmayı 1 saat ertele", "toplantıyı cumaya kaydır", "bugünkünü atla" (tekrarlayanda yalnız sıradaki oluşum)."""
    from datetime import datetime, timedelta
    tr = _say_to_postpone(_fold(text))
    # Negated and quoted words are not legacy reminder mutation authority.
    # This veto leaves the actual Core capability and fallback executor alone.
    if (re.search(r"\b(?:silme|kaldirma|iptal etme|erteleme|oteleme|kaydirma|atlama)\b", tr)
            or re.search(r"\b(?:sil|kaldir|iptal et|ertele|otele|kaydir|atla)\b\s+demedim\b", tr)
            or re.search(r"""["“”]|'[^']{3,}'""", text)):
        return None
    if not _EDIT_ASK.search(tr):
        return None
    skip = bool(runtime.re.search(r"\batla\b|\batlar\s+misin|\batlayabilir", tr))
    move = bool(runtime.re.search(r"\bkaydir\w*", tr))
    postpone = bool(runtime.re.search(r"\b(?:ertele|otele)\w*", tr)) or move
    qual = 'today' if runtime.re.search(r"\bbugunku", tr) else 'tomorrow' if runtime.re.search(r"\byarinki", tr) else ''
    if not (postpone and not move) and not _EDIT_TOPIC.search(tr):
        # "kaydır"/"atla" günlük konuşmada başka şeyler için de geçer: kayıt başlığı ya da bugünkü/yarınki ipucu şart
        if not ((move or skip) and ((qual and not _hint(runtime, tr)) or _title_hits(runtime, tr))):
            return None
    if runtime.re.search(r"\b(?:ekle|yaz|not et)\b|\bnot(?:u|lar\w*)?\s+sil|\bnumarali\b|\b\d+\.?\s*notu?\b", tr):
        return None
    pool = None
    day = None
    if qual:
        day = (now if qual == 'today' else now + timedelta(days=1)).strftime('%Y-%m-%d')
        if not _hint(runtime, tr):
            pool = [e for e in runtime.profile.data['events'] if str(e['when'])[:10] == day]
            if not pool:
                return f"{'Bugün' if qual == 'today' else 'Yarın'} için bir hatırlatman görünmüyor."
    htr = _DAYPART.sub(" ", tr) if postpone else tr
    ev, ask = _edit_target(runtime, htr, delete=not (postpone or skip), pool=pool)
    if ev is None:
        return ask
    if skip:
        if not ev.get('repeat'):
            return f"{ev['title']} tek seferlik bir kayıt; atlamak yerine silmeyi ya da ertelemeyi söyleyebilirsin."
        if day and str(ev['when'])[:10] != day:
            return (f"{ev['title']} {'bugün' if qual == 'today' else 'yarın'} için görünmüyor; sıradaki tekrarı "
                    f"{runtime.whenmod.describe(ev['when'], now)}. Hiçbir şeyi değiştirmedim.")
        cur = datetime.strptime(str(ev['when'])[:16], '%Y-%m-%dT%H:%M')
        base = ev.get('base') or cur.strftime('%H:%M')
        nxt = runtime.whenmod.next_occurrence(ev['repeat'], datetime.combine(cur.date(), datetime.strptime(base, '%H:%M').time()),
                                              int(base[:2]), int(base[3:]))
        runtime.profile.reschedule_event(ev['id'], nxt.strftime('%Y-%m-%dT%H:%M'))
        return (f"{ev['title']}: {runtime.whenmod.describe(ev['when'], now)} tekrarını atladım. "
                f"Sıradaki: {runtime.whenmod.describe(nxt.strftime('%Y-%m-%dT%H:%M'), now)}.")
    if not postpone:
        runtime.profile.delete_event(ev['id'])
        extra = ' (tekrarlayan kaydın bütün tekrarlarını kaldırdım)' if ev.get('repeat') else ''
        return (f"Sildim: {ev['title']}, {runtime.whenmod.describe(ev['when'], now)}{extra}. Yalnız Jarvis kaydıdır; "
                f"Google Takvim'e dokunmadım. Yanlışsa aynı kaydı yeniden ekleyebilirsin.")
    verb = 'kaydırdım' if move else 'erteledim'
    when = str(ev['when'])
    if ev.get('repeat') and not qual and not move and _recently_fired(ev, now):
        snooze = _snooze_repeating(runtime, ev, tr, now)
        if snooze:
            return snooze
    allday = len(when) == 10
    if day and ev.get('repeat') and when[:10] != day:
        return (f"{ev['title']} {'bugün' if qual == 'today' else 'yarın'} için görünmüyor; sıradaki tekrarı "
                f"{runtime.whenmod.describe(when, now)}. Hiçbir şeyi değiştirmedim.")
    base = datetime.strptime(when[:16], '%Y-%m-%dT%H:%M') if not allday else datetime.strptime(when, '%Y-%m-%d')
    dm = runtime.re.search(_DAY_TO, tr)
    dpt = _daypart_time(tr, now)
    if dpt:
        if allday:
            return 'Bu tüm gün kaydı; "yarına" ya da "2 gün" gibi gün olarak ertele.'
        new, said = dpt[0], dpt[1] + ' saatine'
    elif runtime.re.search(r"\bhaftaya\b", tr):
        new, said = base + timedelta(days=7), 'bir hafta'
    elif runtime.re.search(r"\byarina\b|\byarin\b", tr):
        new, said = base + timedelta(days=1), 'bir gün'
        if not allday and new < now and not ev.get('repeat'):
            new = now.replace(hour=base.hour, minute=base.minute, second=0, microsecond=0) + timedelta(days=1)
    elif dm:
        ahead = (_DAYS_FOLD[dm.group(1)] - now.weekday()) % 7
        new = base.replace(year=now.year, month=now.month, day=now.day) + timedelta(days=ahead)
        if not allday and new <= now:
            new += timedelta(days=7)
        said = dm.group(0)
    else:
        mm = runtime.re.search(r"\b(\d+|bir|iki|uc|dort|bes|on|yirmi|otuz)\s*(dakika|dk|saat|gun)\w*", tr)
        if runtime.re.search(r"yarim saat", tr):
            n, unit = 30, 'dakika'
        elif runtime.re.search(r"ceyrek saat", tr):
            n, unit = 15, 'dakika'
        elif mm:
            n = int(mm.group(1)) if mm.group(1).isdigit() else _NUM[mm.group(1)]
            unit = {'dakika': 'dakika', 'dk': 'dakika', 'saat': 'saat', 'gun': 'gün'}[mm.group(2)]
        else:
            n, unit = 10, 'dakika'        # "ertele" tek başına: 10 dakika
        if not 1 <= n <= 1000:
            return 'Bu süreyi anlayamadım; "10 dakika" ya da "yarına" gibi söyle.'
        delta = {'dakika': timedelta(minutes=n), 'saat': timedelta(hours=n), 'gün': timedelta(days=n)}[unit]
        if allday and unit != 'gün':
            return 'Bu tüm gün kaydı; "yarına" ya da "2 gün" gibi gün olarak ertele.'
        new = (now if base <= now and unit != 'gün' else base) + delta
        said = f'{n} {unit}'
    if ev.get('repeat'):
        return _edit_repeating(runtime, ev, new, said, verb, now)
    out = new.strftime('%Y-%m-%d') if allday else new.strftime('%Y-%m-%dT%H:%M')
    runtime.profile.reschedule_event(ev['id'], out)
    return f"{ev['title']} kaydını {said} {verb}: {runtime.whenmod.describe(out, now)}."


# ------------------------------------------------------------------ eski notu arama / düzeltme / silme
_NOTE_DATE = re.compile(r"\b(?:bugunku|bugun|dunku|dun|gecen haftaki|gecen hafta|bu haftaki|bu hafta|gecen ayki|gecen ay|bu ayki|bu ay)\b")
_NOTE_FILLER = re.compile(r"\b(?:benim|bana|aldigim|yazdigim|kaydettigim|tuttugum|ile ilgili|hakkindaki|hakkinda|icinde|icindeki|"
                          r"olan|var mi|var|mi|mu|neydi|nelerdi|neler|nerede|ne|bir|su|bu|o|ara|bul|goster|oku|ya)\b")
_NOTE_EDIT = re.compile(r"^(?P<ref>[^:]*?)\s*\bnot\w*\s+(?:(?:su|bu)\s+)?(?:duzelt|degistir|guncelle)\s*[:,]?\s*(?P<new>.*)$")
_NOTE_DEL = re.compile(r"^(?P<ref>[^:]*?)\s*\bnot\w*\s+(?:sil|kaldir|iptal et)$")
_MONTHS = ('Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara')
_FOUND: dict = {}                     # kullanıcı -> (son bulunan notun kimliği, zaman): "o notu düzelt" için
# Core hands a typed window label to the notes domain; this maps it to the legacy date phrase.
_NOTE_WINDOW_WORDS = {
    'today': 'bugun',
    'yesterday': 'dun',
    'this_week': 'bu hafta',
    'last_week': 'gecen hafta',
    'this_month': 'bu ay',
    'last_month': 'gecen ay',
}


def _note_window(f: str, now):
    """Tarih sözü -> (başlangıç, bitiş, etiket); söz yoksa None."""
    from datetime import timedelta
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = day - timedelta(days=day.weekday())
    m = _NOTE_DATE.search(f)
    if not m:
        return None
    w = m.group(0)
    if w.startswith('bugun'):
        return day, day + timedelta(days=1), 'bugün'
    if w.startswith('dun'):
        return day - timedelta(days=1), day, 'dün'
    if w.startswith('bu hafta'):
        return monday, monday + timedelta(days=7), 'bu hafta'
    if w.startswith('gecen hafta'):
        return monday - timedelta(days=7), monday, 'geçen hafta'
    first = day.replace(day=1)
    if w.startswith('bu ay'):
        return first, (first + timedelta(days=32)).replace(day=1), 'bu ay'
    return (first - timedelta(days=1)).replace(day=1), first, 'geçen ay'


def _note_when(item) -> str:
    try:
        d = datetime.strptime(item.get('ts', '')[:10], '%Y-%m-%d')
        return f'{d.day} {_MONTHS[d.month - 1]}'
    except ValueError:
        return ''


def _note_words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", _fold(text))


def _note_hits(items, kws, window, fuzzy=False):
    """(numara, not) çiftleri: her anahtar sözcük nottaki bir sözcükle başlangıçta uyuşur (market ~ marketteki)."""
    import difflib
    out = []
    for i, item in enumerate(items, 1):
        if window:
            try:
                ts = datetime.strptime(item.get('ts', '')[:16], '%Y-%m-%d %H:%M')
            except ValueError:
                continue
            if not window[0] <= ts < window[1]:
                continue
        words = _note_words(item['text'] + ' ' + item.get('title', ''))
        def hit(k):
            for w in words:
                n = min(5, len(k), len(w))
                if n >= 3 and k[:n] == w[:n]:
                    return True
                if fuzzy and len(k) >= 4 and difflib.SequenceMatcher(None, k, w).ratio() >= 0.8:
                    return True
            return False
        if all(hit(k) for k in kws):
            out.append((i, item))
    return out


def _note_listing(hits, limit=8) -> str:
    parts = [f"{i}) {n['text']}" + (f' ({_note_when(n)})' if _note_when(n) else '') for i, n in hits[:limit]]
    more = f' … ve {len(hits) - limit} not daha' if len(hits) > limit else ''
    return '; '.join(parts) + more


def _note_ref(runtime, ref: str, f_rest: str):
    """Düzeltme/silme için hedef not: (not, mesaj). Tam biri bulunamazsa not None ve kullanıcıya söylenecek mesaj döner."""
    items = runtime.profile.data['items']
    ref = ref.strip(' .')
    if not items:
        return None, 'Not defterin boş.'
    if re.fullmatch(r"\d{1,3}", ref):
        idx = int(ref)
        return (items[idx - 1], '') if 1 <= idx <= len(items) else (None, 'Böyle bir numaralı not yok.')
    if ref in ('o', 'bu', 'su', 'bulundugum', 'buldugum', 'bulunan', 'az once buldugum'):
        found = _FOUND.get(runtime.profile.slug)
        if found and runtime.time.time() - found[1] <= 900:
            for n in items:
                if n['id'] == found[0]:
                    return n, ''
        return None, "Hangi notu kastettiğini anlayamadım. Önce “market notum” gibi ara ya da “2. notu düzelt: …” de."
    window = _note_window(ref, runtime.datetime.now())
    kws = _note_words(_NOTE_FILLER.sub(' ', _NOTE_DATE.sub(' ', ref)))
    if not kws and not window:
        return None, None
    hits = _note_hits(items, kws, window) or _note_hits(items, kws, window, fuzzy=True)
    if not hits:
        return None, f"“{' '.join(kws) or ref}” ile eşleşen bir not bulamadım ({len(items)} notun var)."
    if len(hits) > 1:
        return None, 'Hangisini kastettin? ' + _note_listing(hits) + ' · Numarayla söyle, örn. “2. notu düzelt: …” ya da “2. notu sil”.'
    return hits[0][1], ''


def _note_lookup(runtime, command: str, cmd_lower: str) -> str | None:
    """Notu numarayla ya da sözcükle düzeltir ("2. notu düzelt: …", "market notunu değiştir: …") ve siler.

    Arama/özetleme burada kalmadı: canonical Understanding işlemi, Core tip/alan doğrulaması ve
    ``notes_search``/``notes_summary`` domain yürütücüsü sahibidir. Model çağrısı yok; birden çok
    not uyuyorsa hiçbir şeye dokunmaz, numaralı liste verip sorar."""
    f0 = _fold(cmd_lower.strip())
    f = f0.strip(' .!?')
    if not re.search(r"\bnot\w*", f) or f.startswith(('not ', 'son not', 'not:')) or re.search(r"\bnot\s*(?:al|et|ekle|yaz)\w*|diye not", f):
        return None
    if re.search(r"\b(?:tum|butun|hepsini)\b", f):
        return None
    slug = runtime.profile.slug
    items = runtime.profile.data['items']
    m = _NOTE_EDIT.match(f)
    if m:
        note, msg = _note_ref(runtime, m.group('ref'), '')
        if note is None and msg is None:
            return None
        if note is None:
            return msg
        start = f.index(m.group('new')) if m.group('new') else len(f)
        new = runtime._plain(command.strip()[len(command.strip()) - (len(f0) - start):]) if m.group('new') else ''
        if not new:
            return f"Notun yeni metnini de söyle: “… notunu düzelt: yeni metin”. Şu an: {note['text']}"
        note['text'] = new
        runtime.profile.save()
        _FOUND[slug] = (note['id'], runtime.time.time())
        return f'Düzelttim: {new}'
    m = _NOTE_DEL.match(f)
    if m:
        note, msg = _note_ref(runtime, m.group('ref'), '')
        if note is None and msg is None:
            return None
        if note is None:
            return msg
        runtime.profile.delete_note_item(note['id'])
        _FOUND.pop(slug, None)
        return f"Notu sildim: {note['text']}"
    return None


def _note_window_by_label(label: str | None, now):
    phrase = _NOTE_WINDOW_WORDS.get(label or '')
    return _note_window(phrase, now) if phrase else None


def notes_search(runtime, query: str, window: str | None = None) -> str:
    """Core-validated notes search; the notes domain owner performs the scan and the answer."""
    items = runtime.profile.data['items']
    bounds = _note_window_by_label(window, runtime.datetime.now())
    kws = _note_words(query)
    label = bounds[2] if bounds else ''
    what = ' '.join(filter(None, [label, ' '.join(kws) or query]))
    if not items:
        return 'Not defterin boş.'
    hits = _note_hits(items, kws, bounds)
    fuzzy = False
    if not hits and kws:
        hits, fuzzy = _note_hits(items, kws, bounds, fuzzy=True), True
    if not hits:
        return f'“{what}” için bir not bulamadım ({len(items)} notun var).'
    if len(hits) == 1:
        _FOUND[runtime.profile.slug] = (hits[0][1]['id'], runtime.time.time())
    head = 'Bulduğum not' if len(hits) == 1 else f'Bulduğum {len(hits)} not'
    return f"{head}{' (yazımı benzeyen)' if fuzzy else ''}: {_note_listing(hits)}"


_SUMMARY_MAX_NOTES = 40
_SUMMARY_MAX_NOTE_CHARS = 1200


def notes_summary(runtime, note_id: str | None = None) -> str:
    """Core-validated notes summary; the notes domain owner picks the bounded notes and synthesizes."""
    items = runtime.profile.data['items']
    if note_id is not None:
        target = next((n for n in items if str(n.get('id')) == str(note_id)), None)
        if target is None:
            return 'Bu notu bulamadım.'
        rows = [target]
    else:
        rows = list(items)
    if not rows:
        return 'Not defterin boş; özetlenecek not yok.'
    lines = [f"{i}) {str(n.get('text') or '')[: _SUMMARY_MAX_NOTE_CHARS]}"
             for i, n in enumerate(rows[:_SUMMARY_MAX_NOTES], 1)]
    text = str(runtime.ask(
        "Aşağıdaki notları Türkçe, en fazla 6 madde halinde kısaca özetle. Notlarda olmayan bilgi ekleme, "
        "işlem yapma, dosya oluşturma.\n\n" + "\n".join(lines)
    ) or '').strip()
    return text or 'Notları özetleyemedim.'



_REPEAT_HELP = ("Bu tekrarı anlayamadım, yanlış kayıt açmamak için eklemedim. 'her gün 9'da', 'her pazartesi 10'da', "
                "'hafta içi her gün 8'de' ya da 'her ayın 1'inde' diyebilirsin.")

# Brain flow: Core-validated reminder arguments authorize CREATION, not raw text editing/deletion.
# Existing pending answers and explicit note-add syntax retain their owner, but the typed creation
# is consumed before legacy reminder edit/snooze and agenda branches.
_CORE_REMINDER: ContextVar["dict | None"] = ContextVar("jarvis_core_reminder", default=None)


@contextmanager
def core_reminder(args: dict):
    token = _CORE_REMINDER.set(dict(args))
    try:
        yield
    finally:
        _CORE_REMINDER.reset(token)


def _notes_snapshot_digest(runtime) -> str:
    """A stable owner-local snapshot; the pending confirmation never stores note bodies."""
    rows = [(row.get("id"), row.get("text"))
            for row in runtime.profile.data.get("items", []) if isinstance(row, dict)]
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clear_notes_confirmed(runtime, proposal: dict) -> str:
    """Bounded State-confirmation effect; no raw command selection at approval."""
    from modules import requests_state
    requests_state.check()
    if (not isinstance(proposal, dict) or proposal.get("owner") != runtime.profile.slug
            or not isinstance(proposal.get("digest"), str)
            or proposal["digest"] != _notes_snapshot_digest(runtime)):
        return "Not silme onayı geçersiz veya notların değişti; hiçbir not silinmedi."
    if not runtime.profile.data.get("items"):
        return "Not defterin zaten boş."
    requests_state.check()
    runtime.profile.clear_note_items()
    return "Tüm notlarını sildim."


def modify_reminder_confirmed(runtime, proposal: dict) -> str:
    """One owner-bound, exact-snapshot State confirmation of a Core operation."""
    from datetime import datetime, timedelta
    from modules import requests_state
    requests_state.check()
    if not isinstance(proposal, dict) or proposal.get("owner") != runtime.profile.slug:
        return "Hatırlatma onayı başka kullanıcıya ait; değiştirmedim."
    operation = proposal.get("operation")
    minutes = proposal.get("minutes")
    if operation not in {"postpone", "skip"}:
        return "Hatırlatma işlemi doğrulanamadı; değiştirmedim."
    if operation == "postpone" and (type(minutes) is not int or not 1 <= minutes <= 10080):
        return "Hatırlatma süresi doğrulanamadı; değiştirmedim."
    if type(proposal.get("event_id")) is not int or not isinstance(proposal.get("title"), str):
        return "Hatırlatma hedefi doğrulanamadı; değiştirmedim."
    events = runtime.profile.data.get("events", [])
    same_id = [event for event in events if isinstance(event, dict) and event.get("id") == proposal["event_id"]]
    from modules.turkish_text import lower
    same_title = [event for event in events if isinstance(event, dict)
                  and isinstance(event.get("title"), str)
                  and lower(event["title"]) == lower(proposal["title"])]
    if len(same_id) != 1 or len(same_title) != 1:
        return "Hatırlatma hedefi artık tek değil; hiçbir kayıt değiştirilmedi."
    ev = same_id[0]
    if any(ev.get(field) != proposal.get(field) for field in ("title", "when", "repeat", "base")):
        return "Hatırlatma onayından sonra kayıt değişmiş; işlem yapılmadı."
    now = runtime.datetime.now()
    when = str(ev["when"])
    allday = len(when) == 10
    try:
        if operation == "skip":
            if not ev.get("repeat") or allday:
                return "Bu hatırlatmanın sıradaki tekrarı güvenli biçimde atlanamıyor."
            current = datetime.strptime(when[:16], "%Y-%m-%dT%H:%M")
            base = ev.get("base") or current.strftime("%H:%M")
            clock = datetime.strptime(base, "%H:%M").time()
            following = runtime.whenmod.next_occurrence(
                ev["repeat"], datetime.combine(current.date(), clock),
                clock.hour, clock.minute)
            new_when = following.strftime("%Y-%m-%dT%H:%M")
            requests_state.check()
            runtime.profile.reschedule_event(ev["id"], new_when)
            return (f"{ev['title']}: sıradaki tekrarı atladım. "
                    f"Sıradaki: {runtime.whenmod.describe(new_when, now)}.")
        if allday and minutes % 1440:
            return "Bu tüm gün kaydı; yalnız gün olarak erteleyebilirsin."
        start = datetime.strptime(when, "%Y-%m-%d" if allday else "%Y-%m-%dT%H:%M")
        shifted = (now if not allday and start <= now and minutes < 1440 else start) + timedelta(minutes=minutes)
        requests_state.check()
        if ev.get("repeat"):
            return _edit_repeating(runtime, ev, shifted, f"{minutes} dakika", "erteledim", now)
        new_when = shifted.strftime("%Y-%m-%d" if allday else "%Y-%m-%dT%H:%M")
        runtime.profile.reschedule_event(ev["id"], new_when)
        return f"{ev['title']} kaydını erteledim: {runtime.whenmod.describe(new_when, now)}."
    except (ValueError, TypeError, KeyError):
        return "Hatırlatma tarihi veya tekrarı doğrulanamadı; hiçbir değişiklik yapılmadı."


def delete_reminder_confirmed(runtime, proposal: dict) -> str:
    """Execute only the previously Core-validated, owner-bound exact approval.

    No raw sentence is re-parsed here. The confirmation is invalidated by
    owner changes, duplicate titles, reschedule, or a changed repeat rule.
    """
    from modules import requests_state
    requests_state.check()
    if not isinstance(proposal, dict) or proposal.get("owner") != runtime.profile.slug:
        return "Hatırlatma onayının sahibi değişti; hiçbir kayıt silinmedi."
    expected = {k: proposal.get(k) for k in ("event_id", "title", "when", "repeat", "base")}
    if type(expected["event_id"]) is not int or type(expected["title"]) is not str:
        return "Hatırlatma onayı doğrulanamadı; hiçbir kayıt silinmedi."
    matches = [e for e in runtime.profile.data.get("events", [])
               if isinstance(e, dict) and e.get("id") == expected["event_id"]
               and e.get("title") == expected["title"]
               and e.get("when") == expected["when"]
               and e.get("repeat") == expected["repeat"]
               and e.get("base") == expected["base"]]
    from modules.turkish_text import lower
    same_title = [e for e in runtime.profile.data.get("events", [])
                  if isinstance(e, dict) and isinstance(e.get("title"), str)
                  and lower(e["title"]) == lower(expected["title"])]
    if len(matches) != 1 or len(same_title) != 1:
        return "Hatırlatma onayından sonra kayıt değişti veya hedef belirsiz; hiçbir kayıt silinmedi."
    requests_state.check()
    if not runtime.profile.delete_event(expected["event_id"]):
        return "Hatırlatma silme işlemini doğrulayamadım; silindi demiyorum."
    detail = " (tekrarlayan kaydın bütün tekrarları)" if expected["repeat"] else ""
    return (f"Sildim: {expected['title']}, "
            f"{runtime.whenmod.describe(expected['when'], runtime.datetime.now())}{detail}. "
            "Yalnız Jarvis kaydıdır; Google Takvim'e dokunmadım.")


def reminder_create(runtime, parsed: dict) -> str:
    """Execute a parsed/validated reminder creation through the existing conflict-confirm pipeline."""
    if parsed.get('repeat') == 'unknown':
        return _REPEAT_HELP
    title, when, repeat = parsed.get('title'), parsed.get('when'), parsed.get('repeat')
    if not title:
        return 'Neyi eklememi istersin?'
    if repeat:
        return _reminder_or_confirm(runtime, title, when, repeat)
    if when:
        return _reminder_or_confirm(runtime, title, when)
    runtime._session().pending_event_title = title
    return f"'{title}' için ne zaman? Örneğin 'yarın 10'da'."


def reminder_core(runtime, args: dict, command: str, cmd_lower: str) -> str:
    """Core ``reminder`` is a validated creation plan; raw words cannot mutate prior events."""
    return reminder_create(runtime, args)


_AGENDA_READ = re.compile('\\btakvim\\w*\\s+(?:aç|açar mısın|açsana|göster|getir)\\w*|\\btakvim\\w*\\s+(?:bak|kontrol)\\w*')
_AGENDA_WRITE = re.compile('\\b(ekle|yaz|sil|not et)\\b')
_AGENDA_OPEN = re.compile('\\b(aç|açar mısın|açsana|göster|getir)')


def agenda_read_request(cmd_lower: str, now) -> tuple[str, str] | None:
    """Tam-cümle takvim okuma grameri ("takvimime bak/kontrol et/aç") -> (gün, etiket) | None.

    Yazma sözcüğü geçen cümle okuma değildir. Tek sahibi burasıdır: hem ham cümleyi yürüten
    planner kolu hem de `command_manager.typo_read_recovery`nin salt-okuma kurtarması bu grameri
    çağırır; gramer kopyalanmaz. Tarayıcı açtan alt biçim `agenda_open_request`te kalır — düzeltilmiş
    bir yazım o etkiyi hiç seçemez."""
    if _AGENDA_READ.search(cmd_lower) is None or _AGENDA_WRITE.search(cmd_lower) is not None:
        return None
    return now.strftime('%Y-%m-%d'), 'Bugün'


def agenda_open_request(cmd_lower: str) -> bool:
    """Okuma gramerinin tarayıcı açan alt biçimi; etki yetkisi yalnız ham cümlede kalır."""
    return _AGENDA_OPEN.search(cmd_lower) is not None


def _planner_command(runtime, command: str, cmd_lower: str) -> str | None:
    """Not defteri ve takvim komutları (kullanıcıya özel)."""
    now = runtime.datetime.now()
    if runtime._session().pending_event_title is not None:
        from modules import brain_entry
        # Açık başlık sorusu yalnız canonical olarak kendi cevabı olan turu tüketir (State zaman
        # protokolü veya semantik ANSWER_TO_PENDING); bağımsız yeni istek soruyu ham metne çevirmez.
        if brain_entry.pending_answer_owned("pending_event_title"):
            title, runtime._session().pending_event_title = (runtime._session().pending_event_title, None)
            if isinstance(title, dict):       # çakışma sorusunun cevabı
                from modules.confirmation import decision
                approval = decision(cmd_lower, extra=('ekle', 'yine de ekle', 'ekle gitsin'))
                if approval is True:
                    return _save_reminder(runtime, *title['confirm'])
                if approval is False:
                    return 'Tamam, eklemedim.'
                title = None                  # başka bir komut geldi: soru düşer, normal akışa devam
            elif brain_entry.matched_protocol("session.pending_event_title.cancel") \
                    or cmd_lower in ('iptal', 'vazgeç', 'boşver'):
                return 'Tamam, eklemedim.'
            when, rest = runtime.whenmod.parse_when(command, now) if title else (None, '')
            if when:
                return _reminder_or_confirm(runtime, title, when)
    if runtime.re.fullmatch('(notlarım(ı (oku|göster|say))?|notlarımı (oku|göster|say)|notları (oku|göster|say)|notlar)', cmd_lower.strip(' .!?')):
        return runtime._notes_text()
    # A Core-validated reminder supplies the operation and title. Its quoted
    # title can contain a note-deletion phrase; a raw-text note edit/delete
    # must not reinterpret that title as authority to mutate notes.
    # Keep legitimate unplanned note commands and exact note-add syntax intact.
    core_reminder_active = _CORE_REMINDER.get() is not None
    if not core_reminder_active:
        # The old re.search accepted 'notları silme' (negative) and quoted
        # instructions inside unrelated messages. These destructive legacy
        # escape hatches must be full-utterance exact protocols, not semantic
        # substrings. The canonical model/Core note writer stays primary.
        exact = cmd_lower.strip(" .!?")
        if exact.startswith(("lütfen ", "lutfen ")):
            exact = exact.split(" ", 1)[1]
        m = runtime.re.fullmatch(
            r"\b(\d{1,3})\.?\s*(?:numaralı\s*)?notu?\s*sil\b"
            r"|\bnotu?\s*(\d{1,3})\s*(?:'?i\s*)?sil\b", exact)
        if m:
            idx = int(m.group(1) or m.group(2))
            items = runtime.profile.data["items"]
            if 1 <= idx <= len(items):
                gone = items[idx - 1]
                runtime.profile.delete_note_item(gone["id"])
                return f"Notu sildim: {gone['text']}"
            return "Böyle bir numaralı not yok."
        clear_words = {
            "notları sil", "notları temizle", "notları hepsini sil",
            "notlarımı sil", "notlarımı temizle",
            "tüm notları sil", "tum notlari sil", "bütün notları sil",
            "butun notlari sil", "notları tamamen sil",
        }
        if exact in clear_words:
            if runtime._session().pending_confirm:
                return "Önce açık onayı tamamla veya iptal et; yeni silme onayı başlatılmadı."
            if not runtime.profile.data.get("items"):
                return "Not defterin zaten boş."
            runtime._session().pending_confirm = {
                "action": "notes_clear",
                "owner": runtime.profile.slug,
                "digest": _notes_snapshot_digest(runtime),
            }
            return "Tüm notlarını silmemi onaylıyor musun? Evet veya hayır de."
    # The indexed/named note lookup also contains update/delete effects.
    looked = None if core_reminder_active else _note_lookup(runtime, command, cmd_lower)
    if looked is not None:
        return looked
    # Note corrections (including last-note delete) are also raw-text effects.
    fixed = None if core_reminder_active else runtime._note_fix(command, cmd_lower)
    if fixed is not None:
        return fixed
    text = runtime._note_text(command, cmd_lower)
    if text:
        runtime._add_note(text)
        return f'Not aldım: {text}'
    core = _CORE_REMINDER.get()
    if core is not None:
        # A validated CREATE never turns an embedded quote like 'hatırlatmayı sil'
        # or 'toplantıyı ertele' into a second raw-text event mutation.
        # Preserve exact note-add and pending-answer ownership above this point.
        return reminder_create(runtime, core)
    tr = runtime.whenmod._turkish(cmd_lower)       # ASCII yazım: "yarin 9da ilac hatirlat"
    edited = _edit_reminder(runtime, cmd_lower, now)
    if edited is not None:
        return edited
    if reminder_parse.is_creation_request(cmd_lower):
        return reminder_create(runtime, reminder_parse.parse(command, now))
    read = agenda_read_request(cmd_lower, now)
    if read is not None:
        day_txt = runtime._agenda_text(*read)
        if agenda_open_request(cmd_lower) and runtime.google_api._ready() is None:
            import webbrowser
            webbrowser.open('https://calendar.google.com')
            return "Google Takvim'i tarayıcıda açtım. " + day_txt
        return day_txt
    week = _week_range(_fold(cmd_lower))
    if week:
        return _week_plan(runtime, week)
    if _PLAN_ASK.search(_fold(cmd_lower)):
        return _day_plan(runtime, 1 if runtime.re.search('\\byar[ıi]n', cmd_lower) else 0)
    if runtime.re.search('\\b(bugün|yarın)\\b.*\\b(ne var|neler var|programım|takvimim|randevum)\\b|\\b(programım|takvimim|ajandam)\\b|\\bne işim var\\b', cmd_lower):
        if 'yarın' in cmd_lower:
            d = (now + __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d')
            return runtime._agenda_text(d, 'Yarın')
        return runtime._agenda_text(now.strftime('%Y-%m-%d'), 'Bugün')
    if runtime.re.search('\\b(yaklaşan|sıradaki|önümüzdeki)\\b.*\\b(etkinlik|randevu|hatırlatma|program)\\w*', cmd_lower):
        up = runtime.profile.upcoming(now, 5)
        if not up:
            return 'Yaklaşan bir kaydın yok.'
        return 'Yaklaşanlar: ' + '; '.join((f"{runtime.whenmod.describe(e['when'], now)} {e['title']}" for e in up)) + '.'
    return None

def _macro_key(runtime, text: str) -> str:
    return runtime.re.sub('\\s+', ' ', runtime.re.sub('[^\\w\\s]', ' ', runtime._tr_lower(text))).strip()

def _macro_run(runtime, cmd_lower: str) -> str | None:
    """Kısayolun her adımı KENDİ canonical kararıyla çalışır; ham adım eski zincire dönmez.

    `brain_entry.run_step` her adımda owner/istek kimliğini turn'den alır, Understanding'i outer
    cümleden ALMAZ: adım kendi prepare -> handoff kararını bir kez alır ve onu tek başına söyleyen
    kullanıcının geçtiği canonical kapıdan geçer (outer entry bağlıyken `runtime.handle(step)` yok).
    Guard'lar (iptal, kapanma, owner değişimi, onay/yanıt bekleme) sırayı korur."""
    macros = runtime.profile.data.get('macros') or {}
    if not macros or runtime._session()._in_macro:
        return None
    key = runtime._macro_key(cmd_lower)
    cands = {key, runtime._VERB_END.sub('', key).strip(), runtime.re.sub('\\s+(aç|başlat|çalıştır|etkinleştir)$', '', key)}
    cands |= {runtime.re.sub('(?:nu|nü|ni|nı|u|ü|i|ı)$', '', c) for c in list(cands)}
    hit = macros.get(key) or next((macros[c] for c in sorted(cands) if c in macros), None)
    if not hit:
        return None
    from modules.brain_entry import run_step
    from modules.command_manager import awaiting_input
    session, owner = runtime._session(), runtime.profile.slug
    session._in_macro = True
    failed, executed, answers = [], [], []
    try:
        for index, act in enumerate(hit['actions']):
            runtime.requests_state.check()
            if runtime.stop_event.is_set() or runtime.flags.get('closing'):
                return 'Jarvis kapanıyor; kısayolun kalan adımlarını çalıştırmadım.'
            reply, feedback = run_step(runtime, act)
            answers.append(str(reply or ''))
            executed.append(act)
            runtime.requests_state.check()
            if getattr(feedback, 'result_status', 'handled') != 'handled':
                return '\n'.join(x for x in answers if x) + '\nBu adım yanıt veya onay bekliyor; kısayolun kalan adımlarını çalıştırmadım.'
            if runtime.profile.slug != owner:
                return '\n'.join(x for x in answers if x) + '\nKullanıcı değişti; kısayolun kalan adımlarını çalıştırmadım.'
            if awaiting_input(session):
                return '\n'.join(x for x in answers if x) + '\nBu adım yanıt veya onay bekliyor; kısayolun kalan adımlarını çalıştırmadım.'
            if runtime.flags.get('closing') or runtime.stop_event.is_set():
                return '\n'.join(x for x in answers if x) + '\nJarvis kapanıyor; kısayolun kalan adımlarını çalıştırmadım.'
            if runtime.re.search('bulamadım|açamadım|anlamadım|başlatılamadı', str(reply or '')):
                failed.append(act)
            if index + 1 < len(hit['actions']):
                runtime.time.sleep(0.4)
    finally:
        session._in_macro = False
        session.speech_override = None  # Do not reuse an individual action's short reply.
    out = f"“{hit['title']}” kısayolunu çalıştırdım: " + ', '.join(executed) + '.'
    return out + (f" Şunlar olmadı: {', '.join(failed)}." if failed else '')

def _brief_facts(runtime) -> list[str]:
    """Günlük özet için gerçek veriler: hava, takvim, hatırlatmalar, mailler (yalnızca gönderen/konu), görevler."""
    now = runtime.datetime.now()
    facts = [f"Şu an: {now.strftime('%d.%m.%Y %H:%M')}, {runtime._DAYS[now.weekday()]}. Kullanıcının adı: {runtime.profile.name}."]
    try:
        wx = runtime.weather.report(runtime.profile.data['prefs'].get('city') or None)
        if wx:
            facts.append('Hava: ' + ' '.join(wx.split()))
    except Exception:
        _record_failure('main.py:_brief_facts')
        pass
    today = now.strftime('%Y-%m-%d')
    tomorrow = (now + runtime.timedelta(days=1)).strftime('%Y-%m-%d')
    for day, label in ((today, 'Bugün'), (tomorrow, 'Yarın')):
        evs = runtime.profile.events_on(day)
        facts.append(f'{label} Jarvis hatırlatmaları: ' + ('; '.join(((e['when'][11:16] + ' ' if len(e['when']) > 10 else '') + e['title'] for e in evs[:6])) if evs else 'yok'))
    try:
        if runtime.google_api.connected():
            facts.append('Google Takvim: ' + runtime.google_api.agenda(0, 'Bugün'))
            facts.append('Gmail: ' + runtime.google_api.unread_mail())
    except Exception:
        _record_failure('main.py:_brief_facts')
        pass
    try:
        from modules import handoff
        line = handoff.brief_line()
        if line:
            facts.append(line)
    except Exception:
        _record_failure('main.py:_brief_facts')
        pass
    try:
        from modules import outlook
        if outlook.installed():
            facts.append('İş maili (Outlook): ' + outlook.unread_mail())
            from modules import worktrack
            line = worktrack.brief_line()
            if line:
                facts.append(line)
    except Exception:
        _record_failure('main.py:_brief_facts')
        pass
    open_tasks = [t['text'] for t in runtime.profile.data.get('tasks', []) if not t['done']]
    facts.append(f'Açık görevler ({len(open_tasks)}): ' + ('; '.join(open_tasks[:8]) if open_tasks else 'yok'))
    goals = runtime.profile.data.get('goals') or []
    if goals:
        facts.append('Kullanıcının hedefi: ' + goals[-1])
    return facts

def _daily_briefing(runtime) -> str:
    """"Bugün neler oldu?" özeti: gerçek verileri toplar, yapay zeka doğal ve kısa bir konuşmaya çevirir."""
    facts = runtime._brief_facts()
    plain = ' '.join((f for f in facts[1:] if not f.endswith(': yok')))
    try:
        text = runtime.ask('\n'.join(facts), f'Sen {runtime.ASSISTANT_NAME} adlı kişisel asistansın. Aşağıdaki GERÇEK verilerden kullanıcıya sesli okunacak kısa bir günlük özet yaz: selamla (saate göre), önce en önemli/acil olanı söyle (yaklaşan toplantı, önemli mail), sonra kalanları toparla. En fazla 6 cümle. Veride olmayan hiçbir şeyi uydurma; boş kalemleri hiç anma. Mailleri tek tek okumak yerine kimden ve ne hakkında olduklarını grupla. Madde işareti, başlık ya da emoji kullanma; doğal, sıcak ve profesyonel Türkçe konuş.', 600).strip()
        if text:
            return text
    except Exception as exc:
        _record_failure('main.py:_daily_briefing')
    now = runtime.datetime.now()
    hello = f'Günaydın {runtime.profile.name}.' if now.hour < 12 else f'Merhaba {runtime.profile.name}.'
    return hello + ' ' + plain

_BRIEF_LOCK = threading.Lock()
_BRIEF_RUNNING: set = set()      # (kullanıcı, gün): bu süreçte hazırlanmakta olan özet


def _brief_done(owner, today: str) -> bool:
    """Bugünün özeti verildi mi? Bellekteki profil yanında diskteki kayda da bakar: yeniden başlatma
    örtüşmesinde önceki süreç yazmış olabilir (profil süreç içinde önbelleklidir, diskten yeniden okunmaz)."""
    if owner.data['prefs'].get('last_brief') == today:
        return True
    path = getattr(owner, 'path', None)
    try:
        disk = json.loads(path.read_text(encoding='utf-8')).get('prefs', {}).get('last_brief') if path else None
    except (OSError, ValueError, AttributeError):
        return False
    if disk == today:
        owner.data['prefs']['last_brief'] = today     # sonraki kayıt bu bilgiyi silmesin
        return True
    return False


def _morning_brief(runtime) -> None:
    """Prepare the PC owner's briefing without borrowing a phone guest's profile."""
    if runtime.stop_event.wait(8):
        return
    claim = None
    try:
        from types import SimpleNamespace
        owner = runtime.pc_profile()
        now = runtime.datetime.now()
        today = now.strftime('%Y-%m-%d')
        if not 5 <= now.hour < 12 or runtime.flags.get('sleep'):
            return
        if owner.data['prefs'].get('morning_brief') is False:
            return
        with _BRIEF_LOCK:                 # aynı gün aynı kullanıcıya ikinci özet hazırlanmasın
            if _brief_done(owner, today) or (owner.slug, today) in _BRIEF_RUNNING:
                return
            claim = (owner.slug, today)
            _BRIEF_RUNNING.add(claim)
        # A captured runtime view avoids holding the command lock during network calls.
        owned = SimpleNamespace(**vars(runtime))
        owned.profile = owner
        owned._brief_facts = lambda: _brief_facts(owned)
        owned._llm.set_user_context(owner.slug)
        text = _daily_briefing(owned)
        if now.weekday() == 4:
            try:
                from modules import outlook, worktrack
                if outlook.installed():
                    text += ' ' + worktrack.report('weekly')
            except Exception:
                _record_failure('main.py:_morning_brief')
        if runtime.stop_event.is_set() or runtime.pc_profile().slug != owner.slug or runtime.flags.get('sleep'):
            return
        with _BRIEF_LOCK:
            if _brief_done(owner, today):
                return
            owner.set_pref('last_brief', today)
        runtime._emit_for(owner, 'assistant', text)
        runtime.events.put(('say', text, owner.slug))
    except Exception:
        _record_failure('main.py:_morning_brief')
    finally:
        if claim:
            with _BRIEF_LOCK:
                _BRIEF_RUNNING.discard(claim)
