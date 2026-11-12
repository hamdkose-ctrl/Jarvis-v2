"""Görev listesi (yapılacaklar): profil verisinde 'tasks' olarak durur. Sesle de yönetilir."""
from __future__ import annotations

import re
from datetime import datetime
from functools import wraps
from modules.personalization import _LOCK
from modules.turkish_text import lower


def _tasks(profile) -> list[dict]:
    return profile.data.setdefault("tasks", [])


def add(profile, text: str, when: str = "") -> dict:
    if not text.strip():
        raise ValueError("Görev açıklaması gerekli.")
    if when:
        datetime.fromisoformat(when)
    else:
        from modules.when import parse_when
        parsed, title = parse_when(text, datetime.now())
        if parsed:
            when, text = parsed, title or text
    t = {"id": profile._new_id(), "text": text.strip(), "done": False,
         "ts": datetime.now().strftime("%Y-%m-%d %H:%M"), "when": when}
    _tasks(profile).append(t)
    profile.save()
    return t


def toggle(profile, tid: int) -> None:
    for t in _tasks(profile):
        if t["id"] == tid:
            t["done"] = not t["done"]
            t["done_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M") if t["done"] else ""
            profile.save()
            return
    raise ValueError('Bu kullanıcıda seçilen görev bulunamadı.')


def complete_exact(profile, text: str) -> str | None:
    """Complete one exact open task in the domain's existing profile lock.

    Core selects the operation and grounded title. The worker never chooses
    intent from raw text; it atomically checks one open exact title and sets
    only False -> True, so concurrent/repeated calls cannot toggle it back.
    """
    from modules import requests_state
    requests_state.check()
    if not isinstance(text, str) or not text.strip():
        return None
    matches = [task for task in _tasks(profile)
               if isinstance(task, dict) and not task.get("done")
               and isinstance(task.get("text"), str)
               and lower(task["text"]) == lower(text.strip())]
    if len(matches) != 1:
        return None
    selected = matches[0]
    old = (selected.get("done", False), selected.get("done_ts", ""))
    selected["done"] = True
    selected["done_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        requests_state.check()
        profile.save()
    except BaseException:
        selected["done"], selected["done_ts"] = old
        raise
    return selected["text"]


def delete(profile, tid: int) -> None:
    if not any(t['id'] == tid for t in _tasks(profile)):
        raise ValueError('Bu kullanıcıda seçilen görev bulunamadı.')
    profile.data["tasks"] = [t for t in _tasks(profile) if t["id"] != tid]
    profile.save()


def clear_done(profile) -> int:
    before = len(_tasks(profile))
    profile.data["tasks"] = [t for t in _tasks(profile) if not t["done"]]
    profile.save()
    return before - len(profile.data["tasks"])


def counts(profile) -> tuple[int, int]:
    ts = _tasks(profile)
    return sum(1 for t in ts if t["done"]), len(ts)


_LIST_REQUEST = re.compile(
    r"^(?:görevlerim|yapılacaklar(?:ım)?|görev listem)(?:\s+neler|\s+ne)?$|görevlerimi (?:oku|say|listele)")


def list_request(cmd_lower: str) -> bool:
    """Tam-cümle görev listesi okuma grameri; tek sahibi burasıdır (yazma kollari hiç görmez)."""
    return _LIST_REQUEST.search(cmd_lower) is not None


def list_text(profile) -> str:
    """Salt-okunan görev listesi cevabı: profil verisini değiştirmez."""
    open_ = [x for x in _tasks(profile) if not x["done"]]
    if not open_:
        return "Açık görevin yok."
    return f"{len(open_)} açık görevin var: " + "; ".join(x["text"] for x in open_[:8]) + "."


def handle(cmd_lower: str, profile) -> str | None:
    t = cmd_lower.strip()
    m = re.match(r"^(?:yeni\s+görev\s*[:,]\s*|(?:yeni\s+)?görev\s+(?:ekle|oluştur|yaz)\s*[:,]?\s*)(.+)$", t) \
        or re.match(r"^(.+?)\s+(?:görevi|görev olarak)\s+ekle$", t) \
        or re.match(r"^(?:görevlerime|yapılacaklara)\s+(.+?)\s+ekle$", t)
    if m:
        task = add(profile, m.group(1))
        return f"Görev ekledim: {task['text']}."
    if list_request(t):
        return list_text(profile)
    m = re.match(r"^(.+?)\s+görevini\s+(?:bitir|tamamla|bitti|yaptım|işaretle)\w*$", t) \
        or re.match(r"^görev\w*\s+(.+?)\s+(?:bitti|tamamlandı)$", t)
    if m:
        key = m.group(1).strip()
        for x in _tasks(profile):
            if not x["done"] and lower(key) in lower(x["text"]):
                toggle(profile, x["id"])
                return f"“{x['text']}” görevini tamamlandı olarak işaretledim."
        return f"“{key}” içeren açık bir görev bulamadım."
    if re.search(r"tamamlanan görevleri (?:temizle|sil)", t):
        return f"{clear_done(profile)} tamamlanmış görevi sildim."
    return None


def _locked(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return wrapped


add = _locked(add)
toggle = _locked(toggle)
complete_exact = _locked(complete_exact)
delete = _locked(delete)
clear_done = _locked(clear_done)
counts = _locked(counts)
handle = _locked(handle)
