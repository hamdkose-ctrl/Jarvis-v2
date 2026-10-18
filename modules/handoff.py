"""Ev / iş devir listesi: "yarın işte şu çizime bakayım", "bunu evde yaparım".

Notlar Google hesabındaki "Jarvis" görev listesine [İŞ] / [EV] etiketiyle yazılır; böylece iki bilgisayar ve telefondaki
Google Görevler aynı listeyi görür. Jarvis yalnızca bu listeye dokunur. Bilgisayarın iş mi ev mi olduğu Ayarlar'dan
seçilir (Outlook kurulu olan kendiliğinden "iş" sayılır).
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import difflib
import re
from datetime import date, datetime, timedelta

from config import load_settings, save_settings

LIST_NAME = "Jarvis"
TAG = {"is": "[İŞ]", "ev": "[EV]"}
NAME = {"is": "iş", "ev": "ev"}
ENABLE_URL = "https://console.cloud.google.com/apis/library/tasks.googleapis.com"
_list_ids: dict = {}
_DAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]


# ------------------------------------------------------------------ bu bilgisayar
def place() -> str:
    """Bu bilgisayar 'is' mi 'ev' mi? Seçilmediyse Outlook kurulu olan iş sayılır."""
    p = load_settings().get("this_pc")
    if p in ("is", "ev"):
        return p
    try:
        from modules import outlook
        return "is" if outlook.installed() else "ev"
    except Exception:       # noqa: BLE001
        _record_failure('modules/handoff.py:place')
        return "ev"


def set_place(p: str) -> None:
    save_settings(this_pc=p if p in ("is", "ev") else None)


def other(p: str) -> str:
    return "ev" if p == "is" else "is"


# ------------------------------------------------------------------ Google Görevler
def _svc(interactive: bool = False):
    from modules import google_api
    return google_api.tasks_service(interactive)


def _explain(exc: Exception) -> str:
    t = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, PermissionError) or "invalid_grant" in t:
        return "Google Görevler izni yok ya da çalışmıyor. Menü › Yapay zekâ › Gmail ve Takvim bölümünde “Görevler iznini ver” düğmesine bas."
    if "accessNotConfigured" in t or "has not been used" in t or "disabled" in t.lower():
        return f"Google Cloud'da “Google Tasks API” kapalı. Şu adresten bir kez “Etkinleştir”e bas: {ENABLE_URL}"
    if "google_credentials" in t or "No such file" in t:
        return "Önce Menü › Yapay zekâ › Gmail ve Takvim bölümünden Google bağlantısını kur."
    return "Google Görevler'e ulaşılamadı: " + t[:160]


def _lid(svc) -> str:
    from modules import llm
    user = llm.current_user()
    if user in _list_ids:
        return _list_ids[user]
    for tl in svc.tasklists().list(maxResults=100).execute().get("items", []):
        if tl.get("title") == LIST_NAME:
            _list_ids[user] = tl["id"]
            return _list_ids[user]
    _list_ids[user] = svc.tasklists().insert(body={"title": LIST_NAME}).execute()["id"]
    return _list_ids[user]


def connect() -> tuple[bool, str]:
    """Ayarlar'daki 'Görevler iznini ver': tarayıcıda izin ister, listeyi hazırlar."""
    try:
        svc = _svc(interactive=True)
        _lid(svc)
        return True, "Görevler izni verildi ✓  “Yarın işte … bakayım” ya da “bunu evde yaparım” diyebilirsin."
    except Exception as e:  # noqa: BLE001
        _record_failure('modules/handoff.py:connect')
        return False, _explain(e)


def ready() -> bool:
    from modules import google_api
    return google_api.token_path(google_api.TASKS_TOKEN).exists()


def add(text: str, where: str, due: date | None = None) -> str:
    svc = _svc()
    body = {"title": f"{TAG[where]} {text}", "notes": f"{NAME[place()]} bilgisayarından Jarvis ekledi"}
    if due:
        body["due"] = due.strftime("%Y-%m-%dT00:00:00.000Z")
    from modules import requests_state
    tasklist = _lid(svc)
    requests_state.check()
    svc.tasks().insert(tasklist=tasklist, body=body).execute()
    return text


def pending(where: str | None = None, until: date | None = None) -> list[dict]:
    """Bitmemiş devir notları (isteğe bağlı: yalnız bir yer, ve son tarihi 'until'e kadar olanlar)."""
    svc = _svc()
    items = svc.tasks().list(tasklist=_lid(svc), showCompleted=False, maxResults=100).execute().get("items", [])
    out = []
    for it in items:
        title = it.get("title") or ""
        w = "is" if title.startswith(TAG["is"]) else "ev" if title.startswith(TAG["ev"]) else None
        if where and w != where:
            continue
        d = (it.get("due") or "")[:10]
        if until and d and d > until.isoformat():
            continue
        out.append({"id": it["id"], "where": w, "text": re.sub(r"^\[(?:İŞ|EV)\]\s*", "", title), "due": d})
    return out


def complete(query: str) -> str | None:
    """'çizim işi tamam' -> en çok benzeyen bekleyen notu tamamlar. Bulamazsa None."""
    from modules.turkish_text import lower
    q = lower(query)
    best, hit = 0.0, None
    for it in pending():
        t = lower(it["text"])
        r = max(difflib.SequenceMatcher(None, q, t).ratio(),
                sum(1 for w in q.split() if len(w) > 2 and w[:5] in t) / max(1, len([w for w in q.split() if len(w) > 2])))
        if r > best:
            best, hit = r, it
    if not hit or best < 0.5:
        return None
    svc = _svc()
    svc.tasks().patch(tasklist=_lid(svc), task=hit["id"], body={"status": "completed"}).execute()
    return hit["text"]


# ------------------------------------------------------------------ konuşmadan anlama
_WHERE_IS = r"\b(?:işte|iş yerinde|ofiste|şantiyede|sahada|işe gidince|işe vardığımda|iş bilgisayarında|iş için not)\b"
_WHERE_EV = r"\b(?:evde|eve gidince|eve varınca|eve geçince|ev bilgisayarında|ev için not|akşam evde)\b"
_SUFFIX = r"(?:yacağım|yeceğim|yayım|yeyim|acağım|eceğim|ayım|eyim|iyim|ıyım|uyum|üyüm|arım|erim|ırım|irim|urum|ürüm|alım|elim)"
_VERB = r"\b(?!bilgisayar)\w{2,}?" + _SUFFIX + r"\b"


def _due(cl: str) -> date:
    today = date.today()
    if re.search(r"\byarın\b", cl):
        return today + timedelta(days=1)
    for i, d in enumerate(_DAYS):
        if re.search(rf"\b{d}\w*\b", cl):
            ahead = (i - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return today


def _strip(text: str) -> str:
    t = re.sub(r"(?i)\b(?:yarın|bugün|akşam|sabah|öğleden sonra|haftaya|" + "|".join(_DAYS) + r")\w*\b", " ", text)
    t = re.sub(r"(?i)" + _WHERE_IS + "|" + _WHERE_EV, " ", t)
    t = re.sub(r"(?i)\b(?:diye\s+)?(?:not\s+(?:al|et|düş)|hatırlat)\w*\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.:;!-")
    if ":" in t:                                      # "bunu evde yaparım: kombi faturasını öde" -> iki noktadan sonrası
        head, tail = t.split(":", 1)
        if len(tail.split()) >= 2:
            t = tail
    t = re.sub(r"(?i)^\s*(?:jarvis\s*,?\s*)?(?:bunu|şunu|şu|bir|da|de|ben)\s+", "", t)
    if len(t.split()) < 2:                            # yalnız fiil kaldıysa ("yaparım") anlamı yok
        return ""
    t = t.strip(" ,.:;!-")
    return t[:1].upper() + t[1:]


def parse(command: str, cl: str) -> tuple[str, str, date] | None:
    """Devir isteği mi? (metin, yer, tarih) ya da None."""
    is_ = re.search(_WHERE_IS, cl)
    ev_ = re.search(_WHERE_EV, cl)
    if not (is_ or ev_) or (is_ and ev_):
        return None
    if not (re.search(_VERB, cl) or re.search(r"\b(?:iş|ev) için not\b|\bnot\b", cl)):
        return None
    if re.search(r"\b(?:neler|ne var|bekleyen|listele|göster)\b", cl):
        return None
    text = _strip(command)
    if len(text) < 3:
        return None
    return text, ("is" if is_ else "ev"), _due(cl)


def _fmt(items: list[dict]) -> str:
    return "; ".join(f"{i}) {it['text']}" + (f" ({it['due'][8:10]}.{it['due'][5:7]})" if it["due"] else "")
                     for i, it in enumerate(items, 1))


def handle(command: str, cmd_lower: str) -> str | None:
    cl = cmd_lower.strip(" .!?")
    # "bu bilgisayar iş bilgisayarı" / "burası ev"
    m = re.search(r"\b(?:bu bilgisayar|burası)\s+(?:benim\s+)?(iş|ev)\b", cl)
    if m:
        set_place("is" if m.group(1) == "iş" else "ev")
        return f"Tamam, bu bilgisayarı {m.group(1)} bilgisayarı olarak işaretledim."
    # listeleme
    m = re.search(r"\b(?:(işte|iş için|işe|evde|ev için|eve)\s+(?:neler var|ne var|bekleyen\w*|yapılacak\w*|ne yapacağım)|"
                  r"(?:devir listesi|devir notları)\w*)", cl)
    if m:
        where = None
        if m.group(1):
            where = "is" if m.group(1).startswith("iş") else "ev"
        try:
            items = pending(where)
        except Exception as e:  # noqa: BLE001
            _record_failure('modules/handoff.py:handle')
            return _explain(e)
        label = {"is": "İş için", "ev": "Ev için", None: "Devir listesinde"}[where]
        return f"{label} {len(items)} not var: {_fmt(items)}." if items else f"{label} bekleyen not yok."
    # tamamlama: "çizim işi tamam", "nevzat bey işini hallettim"
    m = re.match(r"^(.{3,}?)\s+(?:işi\s+|işini\s+)?(?:tamam(?:landı)?|bitti|hallettim|hallettik|yaptım|tamamladım)$", cl)
    if m and len(m.group(1).split()) >= 1 and ready():
        try:
            done = complete(m.group(1))
        except Exception as e:  # noqa: BLE001
            _record_failure('modules/handoff.py:handle')
            return _explain(e)
        if done:
            return f"Listeden düşürdüm: {done}"
        return None
    # ekleme
    p = parse(command, cl)
    if p:
        text, where, due = p
        try:
            add(text, where, due)
        except Exception as e:  # noqa: BLE001
            _record_failure('modules/handoff.py:handle')
            return _explain(e)
        when = "bugün" if due == date.today() else "yarın" if due == date.today() + timedelta(days=1) \
            else f"{due.strftime('%d.%m')} {_DAYS[due.weekday()]}"
        return f"{NAME[where].capitalize()} listesine ekledim ({when}): {text}"
    return None


# ------------------------------------------------------------------ açılışta / sabah özetinde
def brief_status() -> tuple[str | None, str | None]:
    """(devir notu satırı, sorun). Görevler izni hiç verilmediyse ikisi de None; okunamazsa sorun kullanıcıya söylenecek cümledir."""
    if not ready():
        return None, None
    try:
        here = place()
        items = pending(here, until=date.today())
    except Exception as exc:       # noqa: BLE001
        _record_failure('modules/handoff.py:brief_status')
        if isinstance(exc, PermissionError) or any(k in f"{type(exc).__name__}: {exc}" for k in ("invalid_grant", "accessNotConfigured")):
            return None, _explain(exc)
        return None, "Devir notlarına bakamadım (Google Görevler)."
    if not items:
        return None, None
    return f"{'İş' if here == 'is' else 'Ev'} için bekleyen {len(items)} devir notu var: {_fmt(items)}.", None


def brief_line() -> str | None:
    """Bu bilgisayarın yeri için bugüne kadar bekleyen notlar (özet ve açılış duyurusu için); hata sessiz kalır."""
    return brief_status()[0]


def startup_notice() -> str | None:
    """Günde bir kez, bu bilgisayar açılınca söylenecek devir notları."""
    today = date.today().isoformat()
    key = f"handoff_seen_{place()}"
    if load_settings().get(key) == today:
        return None
    line = brief_line()
    if line:
        save_settings(**{key: today})
    return line


def due(text: str):
    """Public due-date parser used by voice and command handlers."""
    return _due(text)


def explain_error(exc: Exception) -> str:
    """Public, user-readable Google Tasks failure explanation."""
    return _explain(exc)
