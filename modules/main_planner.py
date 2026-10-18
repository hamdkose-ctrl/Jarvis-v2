"""Focused runtime actions with explicitly injected dependencies."""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import json
import re
import threading

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
    if runtime.re.fullmatch('son not(?:u|umu)?\\s+(?:sil|kaldır|iptal et)\\w*', cl):
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
_PLAN_ASK = re.compile(r"\b(?:bugünün|yarının|günün|günümün)\s+plan\w*|\bgünümü\s+planla\w*|"
                       r"^(?:bugün(?:kü)?\s+|yarın(?:ki)?\s+|günlük\s+)?plan[ıi]m(?:[ıi]\s+(?:söyle|göster|oku)\w*|\s+ne(?:dir)?)?\s*[?.!]*$|"
                       r"\b(?:bugün|yarın)\s+ne(?:ler)?\s+(?:yapmal[ıi]y[ıi]m|yapaca[ğg][ıi]m|yapmam\s+laz[ıi]m)")


def _ago(minutes: int) -> str:
    h, m = divmod(max(minutes, 0), 60)
    return ' '.join(x for x in (f'{h} saat' if h else '', f'{m} dakika' if m or not h else '') if x)


def _day_plan(runtime, offset: int = 0) -> str:
    """Modelsiz günlük plan: takvim (Jarvis + Google), sıradaki iş, gecikmiş/bugünkü görevler, okunmamış mail sayısı.

    Model çağrılmaz (kota harcamaz); Google yalnız okunur. Okunamayan kaynak cevabın içinde açıkça söylenir."""
    from datetime import timedelta
    now = runtime.datetime.now()
    day = (now + timedelta(days=offset)).date()
    label = 'Bugünün' if offset == 0 else 'Yarının'
    head = f'{label} planı ({day.day} {_MONTHS_TR[day.month - 1]} {_DAYS_TR[day.weekday()]}).'
    items, problems = [], []
    for e in runtime.profile.events_on(day.strftime('%Y-%m-%d')):
        hhmm = e['when'][11:16] if len(e['when']) > 10 else ''
        items.append((hhmm, e['title']))
    try:
        if runtime.google_api.connected():
            for start, name in runtime.google_api.day_events(offset):
                items.append((start.astimezone().strftime('%H:%M') if start else '', name))
    except Exception:
        _record_failure('main.py:_day_plan')
        problems.append("Google Takvim'e bakamadım")
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
    late, today, other = [], [], []
    for t in runtime.profile.data.get('tasks', []):
        if t.get('done'):
            continue
        d = str(t.get('when') or '')[:10]
        if d and d < day.isoformat():
            late.append(t['text'])
        elif d == day.isoformat():
            today.append(t['text'])
        else:
            other.append(t['text'])
    task = []
    if late:
        task.append(f"{len(late)} gecikmiş ({', '.join(late[:3])})")
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
        except Exception:
            _record_failure('main.py:_day_plan')
            problems.append("Gmail'e bakamadım")
        try:
            from modules import handoff
            line = handoff.brief_line()
            if line:
                parts.append(line)
        except Exception:
            _record_failure('main.py:_day_plan')
    if problems:
        parts.append(' ve '.join(problems) + '.')
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
    for e in runtime.profile.data.get('events', []):
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

_FOLD = str.maketrans('çğıöşüâî', 'cgiosuai')


def _fold(text: str) -> str:
    """Küçük harf + Türkçe harfsiz (ASCII) biçim: "Hatırlatmasını" ve "hatirlatmasini" aynı olur."""
    return text.replace('İ', 'i').replace('I', 'ı').lower().translate(_FOLD)


_EDIT_ASK = re.compile(r"\b(?:sil|kaldir|iptal|ertele|otele)\w*")
_EDIT_TOPIC = re.compile(r"\b(?:hatirlat|etkinli|randevu|takvim)\w*")
_NUM = {"bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "on": 10, "yirmi": 20, "otuz": 30}
_EDIT_NOISE = (r"hatirlat\w*|etkinli\w*|randevu\w*|takvim\w*|sil\w*|kaldir\w*|iptal\w*|et|ertele\w*|otele\w*|bana|su|bu|"
               r"son|ekledigim|ekledi\w*|lutfen|ve|\d+|dakika\w*|dk|saat\w*|gun\w*|yarin\w*|haftaya|bir|iki|uc|bes|on|"
               r"yarim|ceyrek|dort|yirmi|otuz")


def _edit_target(runtime, tr: str, delete: bool):
    """(kayıt, mesaj): komuttaki başlık ipucuna göre tek kayıt; belirsizse kayıt None ve soru mesajı."""
    events = list(runtime.profile.data['events'])
    if not events:
        return None, 'Kayıtlı bir hatırlatman yok.'
    hint = runtime.re.sub(r"\b(?:" + _EDIT_NOISE + r")\b", " ", tr)
    hint = runtime.re.sub(r"\s+", " ", hint).strip(" ,.:-'’")
    if hint:
        words = [w[:5] for w in hint.split()]
        hits = [e for e in events if all(w in _fold(e['title']) for w in words)]
        if not hits:
            return None, f"'{hint}' adında bir kaydın yok."
    elif runtime.re.search(r"\bson\b", tr) and delete:
        hits = [max(events, key=lambda e: e['id'])]
    elif not delete:
        done = sorted((e for e in events if e.get('notified') and not e.get('repeat')), key=lambda e: e['when'], reverse=True)
        hits = done[:1] or (events if len(events) == 1 else [])
    else:
        hits = events if len(events) == 1 else []
    if len(hits) == 1:
        return hits[0], ''
    pool = hits or events
    shown = '; '.join(f"{runtime.whenmod.describe(e['when'])} {e['title']}" for e in sorted(pool, key=lambda e: e['when'])[:5])
    return None, f"Hangisini kastettin? Kayıtların: {shown}. Başlığını söyleyerek tekrar dene."


def _edit_reminder(runtime, text: str, now) -> str | None:
    """Hatırlatma silme ve erteleme: "ilaç hatırlatmasını sil", "hatırlatmayı 10 dakika ertele", "toplantıyı yarına ertele"."""
    from datetime import datetime, timedelta
    tr = _fold(text)
    if not _EDIT_ASK.search(tr):
        return None
    postpone = bool(runtime.re.search(r"\b(?:ertele|otele)\w*", tr))
    if not postpone and not _EDIT_TOPIC.search(tr):
        return None
    if runtime.re.search(r"\b(?:ekle|yaz|not et)\b|\bnot(?:u|lar\w*)?\s+sil|\bnumarali\b|\b\d+\.?\s*notu?\b", tr):
        return None
    ev, ask = _edit_target(runtime, tr, delete=not postpone)
    if ev is None:
        return ask
    if not postpone:
        runtime.profile.delete_event(ev['id'])
        extra = ' (tekrarlayan kaydın bütün tekrarlarını kaldırdım)' if ev.get('repeat') else ''
        return (f"Sildim: {ev['title']}, {runtime.whenmod.describe(ev['when'])}{extra}. Yalnız Jarvis kaydıdır; "
                f"Google Takvim'e dokunmadım. Yanlışsa aynı kaydı yeniden ekleyebilirsin.")
    if ev.get('repeat'):
        return 'Tekrarlayan kaydı ertelemiyorum; istersen silip yeni saatle tekrar ekle.'
    when = str(ev['when'])
    allday = len(when) == 10
    base = datetime.strptime(when[:16], '%Y-%m-%dT%H:%M') if not allday else datetime.strptime(when, '%Y-%m-%d')
    if runtime.re.search(r"\bhaftaya\b", tr):
        new, said = base + timedelta(days=7), 'bir hafta'
    elif runtime.re.search(r"\byarina\b|\byarin\b", tr):
        new, said = base + timedelta(days=1), 'bir gün'
        if not allday and new < now:
            new = now.replace(hour=base.hour, minute=base.minute, second=0, microsecond=0) + timedelta(days=1)
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
    out = new.strftime('%Y-%m-%d') if allday else new.strftime('%Y-%m-%dT%H:%M')
    runtime.profile.reschedule_event(ev['id'], out)
    return f"{ev['title']} kaydını {said} erteledim: {runtime.whenmod.describe(out)}."


_REPEAT_HELP = ("Bu tekrarı anlayamadım, yanlış kayıt açmamak için eklemedim. 'her gün 9'da', 'her pazartesi 10'da', "
                "'hafta içi her gün 8'de' ya da 'her ayın 1'inde' diyebilirsin.")

def _planner_command(runtime, command: str, cmd_lower: str) -> str | None:
    """Not defteri ve takvim komutları (kullanıcıya özel)."""
    now = runtime.datetime.now()
    if runtime._session().pending_event_title is not None:
        title, runtime._session().pending_event_title = (runtime._session().pending_event_title, None)
        if isinstance(title, dict):       # çakışma sorusunun cevabı
            from modules.confirmation import decision
            approval = decision(cmd_lower, extra=('ekle', 'yine de ekle', 'ekle gitsin'))
            if approval is True:
                return _save_reminder(runtime, *title['confirm'])
            if approval is False:
                return 'Tamam, eklemedim.'
            title = None                  # başka bir komut geldi: soru düşer, normal akışa devam
        elif cmd_lower in ('iptal', 'vazgeç', 'boşver'):
            return 'Tamam, eklemedim.'
        when, rest = runtime.whenmod.parse_when(command, now) if title else (None, '')
        if when:
            return _reminder_or_confirm(runtime, title, when)
    if runtime.re.fullmatch('(notlarım(ı (oku|göster|say))?|notlarımı (oku|göster|say)|notları (oku|göster|say)|notlar)', cmd_lower.strip(' .!?')):
        return runtime._notes_text()
    m = runtime.re.search("\\b(\\d{1,3})\\.?\\s*(?:numaralı\\s*)?notu?\\s*sil\\b|\\bnotu?\\s*(\\d{1,3})\\s*(?:'?i\\s*)?sil\\b", cmd_lower)
    if m:
        idx = int(m.group(1) or m.group(2))
        items = runtime.profile.data['items']
        if 1 <= idx <= len(items):
            gone = items[idx - 1]
            runtime.profile.delete_note_item(gone['id'])
            return f"Notu sildim: {gone['text']}"
        return 'Böyle bir numaralı not yok.'
    if runtime.re.search('notları?\\s+(temizle|sil|hepsini sil)|tüm notları sil', cmd_lower):
        runtime.profile.clear_note_items()
        return 'Tüm notlarını sildim.'
    fixed = runtime._note_fix(command, cmd_lower)
    if fixed is not None:
        return fixed
    text = runtime._note_text(command, cmd_lower)
    if text:
        runtime._add_note(text)
        return f'Not aldım: {text}'
    tr = runtime.whenmod._turkish(cmd_lower)       # ASCII yazım: "yarin 9da ilac hatirlat"
    edited = _edit_reminder(runtime, cmd_lower, now)
    if edited is not None:
        return edited
    m = runtime.re.search('\\btakvime\\s+(?:ekle|yaz|not et)\\w*\\s*$', tr) or runtime.re.match('^(?:takvime ekle|takvime not et|takvime yaz|hatırlat|bana hatırlat|bana .*hatırlat|randevu ekle|etkinlik ekle)\\b', tr) or (runtime.re.search('\\bhatırlat\\w*\\b', tr) and runtime.re.search("\\b(yarın|bugün|pazartesi|salı|çarşamba|perşembe|cuma|cumartesi|pazar|saat|gün sonra|saat sonra|dakika sonra|her\\s|hergün|hafta\\s*içi|\\d{1,2}[:.]\\d{2}|\\d{1,2}['’]?(?:da|de|ta|te)\\b)", tr))
    if m:
        body = runtime.re.sub('^(?:bana\\s+)?(?:takvime (?:ekle|not et|yaz)|hat[ıi]rlat\\w*|randevu ekle|etkinlik ekle)\\s*[:,]?\\s*', '', command, flags=runtime.re.I)
        body = runtime.re.sub('\\b(?:diye\\s+)?hat[ıi]rlat\\w*\\b|\\b(?:için\\s+)?takvime\\s+(?:ekle|yaz|not et)\\w*', '', body, flags=runtime.re.I)
        repeat, body = runtime.whenmod.parse_repeat(body)
        if repeat == 'unknown':
            return _REPEAT_HELP
        when, title = runtime.whenmod.parse_when(body, now)
        title = runtime.re.sub('^(?:günü|gün|günleri)\\s+', '', runtime._plain(title))
        if not title:
            return 'Neyi eklememi istersin?'
        if repeat:
            hhmm = when[11:16] if when and len(when) > 10 else '09:00'   # saat yoksa tüm gün kaydı gibi 09:00
            first = runtime.whenmod.next_occurrence(repeat, now, int(hhmm[:2]), int(hhmm[3:]))
            return _reminder_or_confirm(runtime, title, first.strftime('%Y-%m-%dT%H:%M'), repeat)
        if when:
            return _reminder_or_confirm(runtime, title, when)
        runtime._session().pending_event_title = title
        return f"'{title}' için ne zaman? Örneğin 'yarın 10'da'."
    if runtime.re.search('\\btakvim\\w*\\s+(?:aç|açar mısın|açsana|göster|getir)\\w*|\\btakvim\\w*\\s+(?:bak|kontrol)\\w*', cmd_lower) and (not runtime.re.search('\\b(ekle|yaz|sil|not et)\\b', cmd_lower)):
        day_txt = runtime._agenda_text(now.strftime('%Y-%m-%d'), 'Bugün')
        if runtime.re.search('\\b(aç|açar mısın|açsana|göster|getir)', cmd_lower) and runtime.google_api._ready() is None:
            import webbrowser
            webbrowser.open('https://calendar.google.com')
            return "Google Takvim'i tarayıcıda açtım. " + day_txt
        return day_txt
    if _PLAN_ASK.search(runtime.whenmod._turkish(cmd_lower)):
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

def _macro_teach(runtime, command: str, cmd_lower: str) -> str | None:
    m = runtime.re.match('^[\'\\"“‘]?(.+?)[\'\\"”’]?\\s+(?:dersem|dediğimde|dediğim zaman|desem)\\s*,?\\s+(.+)$', cmd_lower)
    if not m:
        return None
    trigger, actions = (m.group(1).strip(), m.group(2).strip())
    if not trigger or len(trigger.split()) > 5:
        return None
    pieces = [p for p in runtime._MACRO_SPLIT.split(actions) if p]
    verb = next((vm.group(1) for p in reversed(pieces) if (vm := runtime._VERB_END.search(p))), 'aç')
    cmds, unknown = ([], [])
    for p in pieces:
        base = runtime._VERB_END.sub('', p).strip()
        app = runtime.system_control.find_app(base)
        if app:
            cmds.append(f'{app} {verb}')
        elif runtime._NONAPP.search(p):
            cmds.append(p)
        else:
            unknown.append(base)
    if not cmds and (not runtime._VERB_END.search(actions)):
        return None
    if not cmds:
        return 'Bu kısayol için tanıdığım bir uygulama ya da komut bulamadım' + (f" ({', '.join(unknown)})." if unknown else '.') + ' Uygulama adını Başlat menüsündeki gibi söyler misin?'
    runtime.profile.data.setdefault('macros', {})[runtime._macro_key(trigger)] = {'title': trigger, 'actions': cmds}
    runtime.profile.save()
    out = f'Kısayolu kaydettim: “{trigger}” dediğinde şunları yapacağım: ' + ', '.join(cmds) + '.'
    if unknown:
        out += f" Şunları tanımadığım için eklemedim: {', '.join(unknown)}."
    return out

def _macro_run(runtime, cmd_lower: str) -> str | None:
    macros = runtime.profile.data.get('macros') or {}
    if not macros or runtime._session()._in_macro:
        return None
    key = runtime._macro_key(cmd_lower)
    cands = {key, runtime._VERB_END.sub('', key).strip(), runtime.re.sub('\\s+(aç|başlat|çalıştır|etkinleştir)$', '', key)}
    cands |= {runtime.re.sub('(?:nu|nü|ni|nı|u|ü|i|ı)$', '', c) for c in list(cands)}
    hit = macros.get(key) or next((macros[c] for c in sorted(cands) if c in macros), None)
    if not hit:
        return None
    from modules.command_manager import awaiting_input
    session, owner = runtime._session(), runtime.profile.slug
    session._in_macro = True
    failed, executed = [], []
    try:
        for index, act in enumerate(hit['actions']):
            runtime.requests_state.check()
            if runtime.stop_event.is_set() or runtime.flags.get('closing'):
                return 'Jarvis kapanıyor; kısayolun kalan adımlarını çalıştırmadım.'
            reply = runtime.handle(act)
            executed.append(act)
            runtime.requests_state.check()
            if runtime.profile.slug != owner:
                return str(reply or '') + '\nKullanıcı değişti; kısayolun kalan adımlarını çalıştırmadım.'
            if awaiting_input(session):
                return str(reply or '') + '\nBu adım yanıt veya onay bekliyor; kısayolun kalan adımlarını çalıştırmadım.'
            if runtime.flags.get('closing') or runtime.stop_event.is_set():
                return str(reply or '') + '\nJarvis kapanıyor; kısayolun kalan adımlarını çalıştırmadım.'
            if runtime.re.search('bulamadım|açamadım|anlamadım|başlatılamadı', reply or ''):
                failed.append(act)
            if index + 1 < len(hit['actions']):
                runtime.time.sleep(0.4)
    finally:
        session._in_macro = False
        session.speech_override = None  # Do not reuse an individual action's short reply.
    out = f"“{hit['title']}” kısayolunu çalıştırdım: " + ', '.join(executed) + '.'
    return out + (f" Şunlar olmadı: {', '.join(failed)}." if failed else '')

def _macro_manage(runtime, cmd_lower: str) -> str | None:
    macros = runtime.profile.data.get('macros') or {}
    if runtime.re.search('kısayol\\w*\\s+(listele|göster|neler)|kısayollarım', cmd_lower):
        if not macros:
            return 'Kayıtlı kısayolun yok. Örnek: “çalışma modu dersem spotify, chrome ve vs code aç”.'
        return 'Kısayolların: ' + '; '.join((f"{v['title']} → {', '.join(v['actions'])}" for v in macros.values())) + '.'
    m = runtime.re.match('^[\'\\"“‘]?(.+?)[\'\\"”’]?\\s+kısayol\\w*\\s+(?:sil|unut|kaldır)$', cmd_lower)
    if m:
        key = runtime._macro_key(m.group(1))
        if key in macros:
            title = macros.pop(key)['title']
            runtime.profile.save()
            return f'“{title}” kısayolunu sildim.'
        return 'Böyle bir kısayolun yok.'
    return None

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
