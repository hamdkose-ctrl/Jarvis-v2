"""İş takibi: Outlook'taki iş maillerinden proje durumu, cevap bekleyenler, tarihli işler ve haftalık özet.

Gizlilik (kullanıcının seçimi "A"): mail İÇERİĞİ hiç okunmaz. Yalnızca "zarf" bilgileri kullanılır:
gönderen, konu, tarih, doğrudan mı / bilgide (CC) mi, ek dosya adları, cevaplanmış mı, önem işareti.
Ayarlardaki work_ai = "local" yapılırsa (ileride, güçlü bir bilgisayarda) içerik yalnızca bilgisayardaki
yerel yapay zekaya (Ollama) okutulur; buluta hiçbir zaman gönderilmez.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import re
import time
from collections import Counter
from datetime import datetime, timedelta

from config import load_settings, save_settings

_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd|ynt|ilt|yanıt|ileti|aw|wg)\s*:\s*|\[external\]\s*)+", re.I)
_INLINE = re.compile(r"^image\d+\.(?:png|jpe?g|gif|bmp)$|^outlook-.*\.(?:png|jpe?g)$", re.I)
_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?:\s*(?:saat\s*)?(\d{1,2})[:.](\d{2}))?\b")
_STOP = {"RE", "FW", "FWD", "YNT", "ILT", "HK", "HAKKINDA", "EXTERNAL", "İLE", "VE", "VEYA", "BİLGİ", "TALEP",
         "TR", "EN", "PDF", "THE", "AND", "FOR", "OF", "TO", "IN", "ON", "DEAR", "SAYIN", "MERHABA"}

_cache: dict = {"t": 0.0, "days": 0, "items": []}


def settings() -> dict:
    s = load_settings()
    return {"projects": list(s.get("work_projects") or []), "vip": list(s.get("work_vip") or []),
            "ai": s.get("work_ai") or "meta"}


def add_project(name: str) -> str:
    name = name.strip(" .,'’").upper()
    if not name:
        return "Proje adını anlayamadım."
    p = settings()["projects"]
    if name not in p:
        p.append(name)
        save_settings(work_projects=p)
    return f"{name} projeni takip listesine ekledim."


def add_vip(name: str) -> str:
    name = " ".join(w.capitalize() for w in name.strip(" .,'’").split())
    if not name:
        return "Kişinin adını anlayamadım."
    v = settings()["vip"]
    if name.lower() not in [x.lower() for x in v]:
        v.append(name)
        save_settings(work_vip=v)
    return f"{name} artık önemli kişilerinde; ondan gelen mailleri öne alacağım."


def clean_subject(s: str) -> str:
    return _PREFIX.sub("", s or "").strip() or "(konusuz)"


# ------------------------------------------------------------------ Outlook'tan zarf bilgileri
def collect(days: int = 14, limit: int = 400) -> list[dict]:
    """Son `days` günün gelen kutusu: içerik okunmadan, yalnızca zarf bilgileri. 2 dakika önbellekli."""
    if _cache["items"] and _cache["days"] >= days and time.time() - _cache["t"] < 120:
        cut = datetime.now() - timedelta(days=days)
        return [x for x in _cache["items"] if x["when"] >= cut]
    from modules import outlook
    if not outlook.installed():
        raise RuntimeError("Bu bilgisayarda Outlook kurulu değil; iş takibi iş bilgisayarında çalışır.")
    if not outlook.running():
        outlook._launch()
    inbox = None
    for _ in range(10):
        try:
            inbox = outlook._inbox()
            break
        except Exception:       # noqa: BLE001
            _record_failure('modules/worktrack.py:collect')
            time.sleep(2)
    if inbox is None:
        raise RuntimeError("Outlook'a bağlanamadım; Outlook'u açıp tekrar dene.")
    try:
        me = str(inbox.Application.Session.CurrentUser.Name or "").strip().lower()
    except Exception:           # noqa: BLE001
        _record_failure('modules/worktrack.py:collect')
        me = ""
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)
    cut = datetime.now() - timedelta(days=days)
    out: list[dict] = []
    n = min(int(items.Count), limit)
    for i in range(1, n + 1):
        try:
            it = items.Item(i)
            if int(getattr(it, "Class", 43)) != 43:          # 43 = mail; toplantı davetleri vb. ayrı
                continue
            when = it.ReceivedTime
            when = datetime(when.year, when.month, when.day, when.hour, when.minute)
            if when < cut:
                break
            to = str(it.To or "")
            cc = str(it.CC or "")
            direct = bool(me) and me in to.lower()
            atts = []
            try:
                for k in range(1, int(it.Attachments.Count) + 1):
                    fn = str(it.Attachments.Item(k).FileName or "")
                    if fn and not _INLINE.match(fn):
                        atts.append(fn)
            except Exception:   # noqa: BLE001
                _record_failure('modules/worktrack.py:collect')
                pass
            replied = False
            try:
                verb = it.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x10810003")
                replied = int(verb) in (102, 103, 104)
            except Exception:   # noqa: BLE001
                _record_failure('modules/worktrack.py:collect')
                pass
            raw = str(it.Subject or "")
            out.append({"sender": str(it.SenderName or "").strip() or "Bilinmeyen", "subject": clean_subject(raw),
                        "raw_subject": raw, "when": when, "unread": bool(it.UnRead), "direct": direct,
                        "cc_only": bool(me) and not direct and me in cc.lower(), "attachments": atts[:4],
                        "replied": replied, "external": "[external]" in raw.lower(),
                        "important": int(getattr(it, "Importance", 1)) == 2, "_entry": str(it.EntryID)})
        except Exception:       # noqa: BLE001 - tek bir bozuk öğe listeyi durdurmasın
            _record_failure('modules/worktrack.py:collect')
            continue
    _cache.update(t=time.time(), days=days, items=out)
    return out


# ------------------------------------------------------------------ çözümleme
def project_of(subject: str, projects: list[str]) -> str | None:
    up = subject.upper()
    for p in projects:
        if re.search(rf"(?<![A-Z0-9ÇĞİÖŞÜ]){re.escape(p.upper())}(?![A-Z0-9ÇĞİÖŞÜ])", up):
            return p
    return None


def auto_projects(items: list[dict], top: int = 6) -> list[str]:
    """Proje listesi boşsa: konu satırlarında sık geçen büyük harfli kısaltmalar (PKF, SER, IKPE…)."""
    c: Counter = Counter()
    for x in items:
        for w in set(re.findall(r"\b[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9]{1,9}\b", x["subject"])):
            if w not in _STOP and not w.isdigit():
                c[w] += 1
    return [w for w, k in c.most_common(top) if k >= 2]


def dated(items: list[dict], now: datetime | None = None) -> list[dict]:
    """Konu satırında geçen ve bugünden sonraki tarihler (keşif, toplantı, teslim…)."""
    now = now or datetime.now()
    out, seen = [], set()
    for x in items:
        for m in _DATE.finditer(x["subject"]):
            d, mo, y, hh, mm = m.groups()
            try:
                year = int(y) + (2000 if y and len(y) == 2 else 0) if y else now.year
                dt = datetime(year, int(mo), int(d), int(hh or 0), int(mm or 0))
            except ValueError:
                continue
            if not y and dt < now - timedelta(days=30):
                dt = dt.replace(year=now.year + 1)
            if now - timedelta(hours=12) <= dt <= now + timedelta(days=60):
                key = (x["subject"], dt)
                if key not in seen:
                    seen.add(key)
                    out.append({"when": dt, "has_time": bool(hh), "subject": x["subject"], "sender": x["sender"]})
    return sorted(out, key=lambda e: e["when"])


def is_vip(sender: str, vip: list[str]) -> bool:
    s = sender.lower()
    return any(v.lower() in s for v in vip)


def needs_reply(items: list[dict]) -> list[dict]:
    """Doğrudan sana yazılmış ve henüz cevaplamadığın mailler (aynı konunun en yenisi)."""
    seen, out = set(), []
    for x in items:
        if x["direct"] and not x["replied"] and x["subject"] not in seen:
            seen.add(x["subject"])
            out.append(x)
    return out


def _fmt_when(dt: datetime, has_time: bool = True) -> str:
    days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    base = f"{dt.day:02d}.{dt.month:02d} {days[dt.weekday()]}"
    return base + (f" {dt.hour:02d}:{dt.minute:02d}" if has_time else "")


def facts(days: int = 7, project: str | None = None) -> dict:
    """Yapay zekaya ve ekrana verilecek özet veriler (içerik yok, yalnızca zarf)."""
    st = settings()
    items = collect(max(days, 14))
    cut = datetime.now() - timedelta(days=days)
    recent = [x for x in items if x["when"] >= cut]
    projects = st["projects"] or auto_projects(items)
    if project:
        recent = [x for x in recent if project.upper() in x["subject"].upper()]
    by_proj: dict[str, list[dict]] = {}
    for x in recent:
        by_proj.setdefault(project_of(x["subject"], projects) or "Diğer", []).append(x)
    return {"days": days, "projects": projects, "by_project": by_proj, "recent": recent,
            "needs_reply": needs_reply(recent), "dated": dated(items),
            "vip": [x for x in recent if is_vip(x["sender"], st["vip"])],
            "cc_only": sum(1 for x in recent if x["cc_only"]),
            "with_files": [x for x in recent if x["attachments"]],
            "external": [x for x in recent if x["external"]]}


def _line(x: dict) -> str:
    flags = []
    if x["unread"]:
        flags.append("okunmadı")
    if x["direct"]:
        flags.append("doğrudan sana")
    elif x["cc_only"]:
        flags.append("bilgide")
    if x["replied"]:
        flags.append("cevaplandı")
    if x["important"]:
        flags.append("önemli")
    if x["external"]:
        flags.append("yabancı yüklenici, İngilizce")
    if x["attachments"]:
        flags.append("ek: " + ", ".join(x["attachments"][:2]))
    return f"- {x['when'].strftime('%d.%m %H:%M')} | {x['sender']} | {x['subject']} | {'; '.join(flags)}"


def prompt_data(f: dict, max_lines: int = 60) -> str:
    """Yapay zekaya gidecek metin: yalnızca gönderen, konu, tarih ve işaretler."""
    rows = [f"Son {f['days']} gün. Takip edilen projeler: {', '.join(f['projects']) or 'belirlenmedi'}."]
    for p, xs in sorted(f["by_project"].items(), key=lambda kv: (kv[0] == "Diğer", -len(kv[1]))):
        rows.append(f"\nPROJE {p} ({len(xs)} mail):")
        rows += [_line(x) for x in xs[:12]]
    rows.append(f"\nCEVAP BEKLEYEN (doğrudan sana, cevaplamadın): {len(f['needs_reply'])}")
    rows += [_line(x) for x in f["needs_reply"][:10]]
    rows.append("\nKONUDAKİ TARİHLER: " + ("; ".join(f"{_fmt_when(d['when'], d['has_time'])} – {d['subject']}"
                                                   for d in f["dated"][:8]) or "yok"))
    if f["vip"]:
        rows.append("\nÖNEMLİ KİŞİLERDEN: " + "; ".join(f"{x['sender']}: {x['subject']}" for x in f["vip"][:6]))
    rows.append(f"\nSadece bilgide (CC) olduğu mail sayısı: {f['cc_only']}")
    return "\n".join(rows[:max_lines + 20])


def _ai(text: str, system: str, max_tokens: int = 700) -> str:
    from modules import llm
    if settings()["ai"] == "local":
        return llm._ollama([{"role": "user", "content": text}], system, max_tokens)
    return llm.ask(text, system, max_tokens)


_SYS = ("Sen kullanıcının kişisel asistanı {name}'sin. Kullanıcı raylı sistemlerde sinyalizasyon teknikeri; hem sahada "
        "hem ofiste çalışıyor. Aşağıdaki iş maili ÖZETLERİNDEN (yalnızca gönderen, konu, tarih ve işaretler; içerik yok) "
        "{task} Veride olmayan hiçbir şeyi uydurma; içerik görmediğini unutma, konudan çıkarım yaparken 'konuya göre' de. "
        "İngilizce konuları Türkçe anlat. Sesli okunacak: madde işareti, başlık, emoji kullanma; kısa, net, doğal Türkçe.")


def report(kind: str = "status", project: str | None = None) -> str:
    try:
        f = facts(7 if kind != "weekly" else 7, project)
    except Exception as e:      # noqa: BLE001
        _record_failure('modules/worktrack.py:report')
        return str(e) if isinstance(e, RuntimeError) else f"İş maillerine bakamadım: {type(e).__name__}"
    if not f["recent"]:
        return (f"Son bir haftada {project} ile ilgili mail görmedim." if project else "Son bir haftada iş maili görmedim.")
    task = {
        "status": "proje proje durumu en fazla 6 cümlede anlat: hangi projede ne hareket var, ne açıkta görünüyor.",
        "reply": "cevap bekleyen mailleri önem sırasına koyarak say; en fazla 6 cümle.",
        "dated": "yaklaşan tarihli işleri (keşif, toplantı, teslim) sırayla söyle; en fazla 5 cümle.",
        "priority": "şu an en öncelikli 3 işi seç ve nedenini kısaca söyle (yakın tarih, önemli kişi, cevap bekleyen).",
        "weekly": "bu haftanın özetini yap: hangi projelerde neler döndü, ne açıkta kaldı, gelecek hafta ne var. En fazla 7 cümle.",
    }.get(kind, "durumu kısaca anlat.")
    if project:
        task = f"yalnızca {project} projesi için " + task
    try:
        try:
            from config import ASSISTANT_NAME as name
        except ImportError:
            name = "Jarvis"
        return _ai(prompt_data(f), _SYS.format(task=task, name=name)).strip() or _plain(f, kind)
    except Exception:           # noqa: BLE001 - yapay zeka yoksa düz liste
        _record_failure('modules/worktrack.py:report')
        if settings()["ai"] == "local":     # iş maili buluta gitmez: Ollama yoksa düz liste + açık uyarı
            from modules import ollama_hint
            return ollama_hint.need("Yapay zekâ özeti") + "\n" + _plain(f, kind)
        return _plain(f, kind)


def _plain(f: dict, kind: str) -> str:
    if kind == "dated":
        d = f["dated"][:5]
        return ("Yaklaşan tarihli işler: " + "; ".join(f"{_fmt_when(x['when'], x['has_time'])} {x['subject']}" for x in d) + "."
                if d else "Konu satırlarında yaklaşan bir tarih görmedim.")
    if kind == "reply":
        r = f["needs_reply"][:6]
        return (f"Cevap bekleyen {len(f['needs_reply'])} mail var: " + "; ".join(f"{x['sender']}: {x['subject']}" for x in r) + "."
                if r else "Doğrudan sana gelip cevaplamadığın mail yok.")
    parts = [f"{p}: {len(xs)} mail" for p, xs in f["by_project"].items()]
    return (f"Son {f['days']} günde " + ", ".join(parts) + f". Cevap bekleyen {len(f['needs_reply'])} mail var.")


def brief_line() -> str | None:
    """Günlük özet için tek satırlık iş durumu (içerik yok)."""
    try:
        f = facts(1)
    except Exception:           # noqa: BLE001
        _record_failure('modules/worktrack.py:brief_line')
        return None
    d = [x for x in f["dated"] if x["when"].date() <= (datetime.now() + timedelta(days=2)).date()]
    parts = [f"son 24 saatte {len(f['recent'])} iş maili geldi (okunmuş olanlar dahil; "
             f"{sum(1 for x in f['recent'] if x['direct'])} doğrudan sana, {f['cc_only']} bilgide)",
             f"son 7 günde cevap bekleyen {len(needs_reply(collect(7)))}"]
    if d:
        parts.append("yaklaşan: " + "; ".join(f"{_fmt_when(x['when'], x['has_time'])} {x['subject']}" for x in d[:3]))
    if f["vip"]:
        parts.append("önemli kişilerden: " + "; ".join(f"{x['sender']} – {x['subject']}" for x in f["vip"][:3]))
    return "İş takibi: " + ", ".join(parts) + "."


def add_dated_reminders(profile) -> str:
    """Konu satırlarındaki yaklaşan tarihleri Jarvis hatırlatmalarına ekler (aynısı varsa eklemez)."""
    try:
        items = dated(collect(14))
    except Exception as e:      # noqa: BLE001
        _record_failure('modules/worktrack.py:add_dated_reminders')
        return str(e)
    have = {(e["title"], e["when"]) for e in profile.data.get("events", [])}
    added = 0
    for d in items:
        if d["when"] < datetime.now():
            continue
        when = d["when"].strftime("%Y-%m-%dT%H:%M") if d["has_time"] else d["when"].strftime("%Y-%m-%d")
        title = d["subject"][:80]
        if (title, when) not in have:
            profile._add_event(title, when)
            added += 1
    return (f"{added} tarihli işi hatırlatmalarına ekledim; Takvim sayfasında görebilirsin." if added
            else "Eklenecek yeni tarihli iş bulamadım.")


# ------------------------------------------------------------------ sesli/yazılı komutlar
def _gmail_reply(t: str) -> bool:
    """Cevap takibi Gmail'e mi gitsin? Açıkça Gmail dendiyse, "cevap gelmeyen/beklediğim" (benim gönderdiğim; Outlook
    takibinde yok) sorulduysa ya da bu bilgisayarda Outlook yokken iş maili denmediyse. Eskiden Outlook'suz evde
    "cevap bekleyen maillerim" yalnız "Outlook kurulu değil" diyordu."""
    from modules import google_api, outlook
    if "gmail" in t or google_api._AWAIT_THEIRS.search(t):
        return True
    if re.search(r"\biş\b|\biş mail|outlook", t):
        return False
    return not outlook.installed() and google_api.connected()


def google_api_important(t: str) -> bool:
    """"önemli/öncelikli maillerim" gibi söz: Gmail'in önemli listesi (google_api.important_text) için."""
    from modules import google_api
    return bool(google_api._IMPORTANT.search(t))


def handle(cmd_lower: str, profile=None) -> str | None:
    t = cmd_lower
    m = re.search(r"(?:proje(?:ler)?im[ei]?|takip listem[ei]?)\s+(.+?)\s*(?:'?[iıuü]?\s*)?ekle", t)
    if m:
        return add_project(m.group(1))
    m = re.search(r"önemli kişi(?:ler)?(?:im)?[ei]?\s+(.+?)\s*(?:'?[yi]?[iıuü]?\s*)?ekle", t)
    if m:
        return add_vip(m.group(1))
    if re.search(r"(?:tarihli işleri|tarihleri|bunları)\s+(?:hatırlat|hatırlatma\w*\s+ekle|takvime ekle)", t) and profile:
        return add_dated_reminders(profile)
    if re.search(r"haftalık (?:iş )?özet|bu hafta (?:neler oldu|ne oldu|neler döndü)", t):
        return report("weekly")
    if re.search(r"cevap\w* bekle|cevaplamadı\w*|yanıtlamadı\w*|dönmediğim|dönüş bekle", t) and not _gmail_reply(t):
        return report("reply")
    if re.search(r"öncelik\w*|önce ne yapmalı|ilk ne yapayım|acil (?:iş|ne)", t) and re.search(r"iş|ne|hangi", t) \
            and not google_api_important(t):
        return report("priority")
    if re.search(r"yaklaşan (?:iş|keşif|toplantı)|tarihli iş|keşif ne zaman|keşifler", t):
        return report("dated")
    m = re.search(r"\b([a-zçğıöşü0-9]{2,12})\s*(?:'?\w{0,3})?\s+(?:projesi\w*\s+)?ne durumda", t)
    if m and m.group(1) not in ("iş", "işler", "projeler", "durum", "her", "şey", "ne", "bu"):
        return report("status", m.group(1).upper())
    if re.search(r"iş(?:ler)?(?:im)? (?:ne )?durum|projeler(?:im)? ne durumda|iş takib|işte neler var|işler nasıl", t):
        return report("status")
    return None
