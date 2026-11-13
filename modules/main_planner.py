"""Focused runtime actions with explicitly injected dependencies."""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import json
import hashlib
import re
import threading
from datetime import datetime

from modules import reminder_parse

def _plain(runtime, text: str) -> str:
    return runtime.re.sub('\\s+', ' ', text).strip(' .,:;!-')

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


def _edit_repeating(runtime, ev: dict, new_when, said: str, verb: str, now) -> str:
    """Tekrarlayan kaydın yalnız sıradaki oluşumunu kaydırır; kural ve sonraki oluşumların saati değişmez."""
    from datetime import datetime
    cur = datetime.strptime(str(ev['when'])[:16], '%Y-%m-%dT%H:%M')
    base = ev.get('base') or cur.strftime('%H:%M')
    out = new_when.strftime('%Y-%m-%dT%H:%M')
    if not runtime.profile.reschedule_event(ev['id'], out, base=None if out[11:16] == base else base):
        return "Hatırlatmanın yeni zamanını kaydedemedim; erteledim demiyorum."
    _drop_queued_reminder_speech(runtime, ev)
    after = datetime.combine(cur.date(), datetime.strptime(base, '%H:%M').time())
    following = runtime.whenmod.next_occurrence(ev['repeat'], after, int(base[:2]), int(base[3:]))
    msg = f"{ev['title']} kaydının sıradaki tekrarını {said} {verb}: {runtime.whenmod.describe(out, now)}."
    if out[11:16] != base:
        msg += f" Sonraki tekrarlar eski saatinde ({base}) kalır."
    if new_when.date() > following.date():
        msg += ' Aradaki tekrarlar bu sefer çalmaz.'
    return msg


# ------------------------------------------------------------------ eski notu arama / düzeltme / silme
_NOTE_DATE = re.compile(r"\b(?:bugunku|bugun|dunku|dun|gecen haftaki|gecen hafta|bu haftaki|bu hafta|gecen ayki|gecen ay|bu ayki|bu ay)\b")
_MONTHS = ('Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara')
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
def note_snapshot_digest(note) -> str | None:
    """Hash only a known note's identity and persisted fields, never model text.

    A model-resolved note edit/delete is a proposal about the observed version
    of one record; it must not overwrite a newer version of that same ID.
    """
    if not isinstance(note, dict) or not isinstance(note.get("text"), str):
        return None
    ident = note.get("id")
    if isinstance(ident, bool) or not isinstance(ident, (str, int)):
        return None
    fields = (str(ident), note["text"], note.get("title"),
              note.get("ts"), note.get("photo"))
    if any(value is not None and not isinstance(value, str) for value in fields):
        return None
    raw = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    if operation not in {"postpone", "skip", "snooze", "move"}:
        return "Hatırlatma işlemi doğrulanamadı; değiştirmedim."
    if operation in {"postpone", "snooze"} and (type(minutes) is not int
            or not 1 <= minutes <= (1440 if operation == "snooze" else 10080)):
        return "Hatırlatma süresi doğrulanamadı; değiştirmedim."
    if operation == "move" and (type(proposal.get("weekday")) is not int
                                or not 0 <= proposal["weekday"] <= 6):
        return "Hatırlatma günü doğrulanamadı; değiştirmedim."
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
    if operation == "move":
        # A weekday is a closed Core enum, not a path/ID or free-language
        # rewrite. Resolve the first future matching day from the current
        # owner's clock; the existing repeat worker retains the base rule.
        from datetime import date
        days = (proposal["weekday"] - now.weekday()) % 7 or 7
        new_date = (now + timedelta(days=days)).date()
        clock = when[10:16] if len(when) == 16 else ""
        new_when = new_date.strftime("%Y-%m-%d") + clock
        try:
            if ev.get("repeat"):
                if not clock:
                    return "Tüm gün tekrarını güvenle kaydıramadım."
                new_start = datetime.strptime(new_when, "%Y-%m-%dT%H:%M")
                requests_state.check()
                return _edit_repeating(runtime, ev, new_start,
                                       "seçilen güne", "kaydırdım", now)
            requests_state.check()
            if not runtime.profile.reschedule_event(ev["id"], new_when):
                return "Hatırlatmayı kaydedemedim; kaydırdım demiyorum."
            return f"{ev['title']} kaydını kaydırdım: {runtime.whenmod.describe(new_when, now)}."
        except (ValueError, TypeError):
            return "Hatırlatma günü geçersiz; hiçbir kayıt değiştirilmedi."
    if operation == "snooze":
        # Validate the exact fired/notified/snooze state captured at approval,
        # not merely the title/when snapshot. A second notification or snooze
        # makes this approval stale, so it cannot mutate the newer occurrence.
        if (any(ev.get(field) != proposal.get(field)
                for field in ("fired", "snooze"))
                or ev.get("notified", False) != proposal.get("notified", False)):
            return "Hatırlatma onayından sonra çalma durumu değişmiş; ertelemedim."
        fired = (ev.get("fired") if ev.get("repeat") else
                 ev.get("when") if ev.get("notified") else None)
        try:
            fired_at = datetime.strptime(str(fired)[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            return "Bu hatırlatma yakın zamanda çalmamış; ertelemedim."
        if not timedelta(0) <= now - fired_at <= timedelta(hours=6):
            return "Bu hatırlatma yakın zamanda çalmamış; ertelemedim."
        new_when = (now + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")
        requests_state.check()
        if ev.get("repeat"):
            accepted = runtime.profile.snooze_event(ev["id"], new_when)
        else:
            accepted = runtime.profile.reschedule_event(ev["id"], new_when)
        if not accepted:
            return "Hatırlatmayı yeniden planlayamadım; erteledim demiyorum."
        return (f"{ev['title']} hatırlatmasını {minutes} dakika sonra yeniden "
                f"hatırlatacağım ({new_when[11:16]}).")

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
            if not runtime.profile.reschedule_event(ev["id"], new_when):
                return "Hatırlatmanın sıradaki tekrarını değiştiremedim; atladım demiyorum."
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
        if not runtime.profile.reschedule_event(ev["id"], new_when):
            return "Hatırlatmanın yeni zamanını kaydedemedim; erteledim demiyorum."
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


def continue_pending_event_title(runtime, command: str, cmd_lower: str) -> str | None:
    """Consume only the current owner's canonical reminder-date or confirmation answer.

    Do not erase a pending question just because the user supplied an
    incomplete date or an unrecognized yes/no. The model/State gate owns the
    conversational decision; this worker only validates the bound answer.
    """
    from modules import brain_entry, requests_state
    if not brain_entry.pending_answer_owned("pending_event_title"):
        return None
    session = runtime._session()
    pending = session.pending_event_title
    if pending is None:
        return None
    if (brain_entry.matched_protocol("session.pending_event_title.cancel")
            or cmd_lower.strip() in ("iptal", "vazgeç", "boşver")):
        session.pending_event_title = None
        return "Tamam, eklemedim."
    if isinstance(pending, dict):
        from modules.confirmation import decision
        approval = decision(cmd_lower, extra=("ekle", "yine de ekle", "ekle gitsin"))
        if approval is None:
            return "Çakışan hatırlatmayı yine de eklememi onaylıyor musun? Evet veya hayır de."
        session.pending_event_title = None
        if not approval:
            return "Tamam, eklemedim."
        confirmed = pending.get("confirm")
        if not (isinstance(confirmed, (tuple, list)) and len(confirmed) == 3
                and isinstance(confirmed[0], str) and confirmed[0].strip()
                and isinstance(confirmed[1], str) and confirmed[1].strip()
                and (confirmed[2] is None or isinstance(confirmed[2], str))):
            return "Hatırlatma onayının hedefi geçersiz; kayıt eklemedim."
        requests_state.check()
        return _save_reminder(runtime, *confirmed)
    if not isinstance(pending, str) or not pending.strip():
        session.pending_event_title = None
        return "Hatırlatma başlığı doğrulanamadı; kayıt eklemedim."
    when, _rest = runtime.whenmod.parse_when(command, runtime.datetime.now())
    if not when:
        return f"'{pending}' için tarih ve saati anlayamadım. Örneğin 'yarın 10'da' de."
    requests_state.check()
    session.pending_event_title = None
    return _reminder_or_confirm(runtime, pending, when)


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
        # The day's brief is one result: naming it keeps the scheduled and opening
        # paths from announcing the same briefing twice out loud.
        runtime.events.put(('say', text, owner.slug, {'kind': 'notice', 'event_id': f'brief:{today}'}))
    except Exception:
        _record_failure('main.py:_morning_brief')
    finally:
        if claim:
            with _BRIEF_LOCK:
                _BRIEF_RUNNING.discard(claim)
