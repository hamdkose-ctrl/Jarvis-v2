"""Görev listesi (yapılacaklar): profil verisinde 'tasks' olarak durur. Sesle de yönetilir."""
from __future__ import annotations

import re
import hashlib
import json
import time
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
    rows = _tasks(profile)
    rows.append(t)
    try:
        profile.save()
    except BaseException:
        rows.remove(t)
        raise
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


def completed_digest(profile) -> str:
    rows = [dict(task) for task in _tasks(profile) if task.get("done")]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def clear_done_preview(profile, session) -> str:
    if session.pending_confirm or session.pending_action:
        return "Önce açık onayı tamamla veya iptal et; görev silme onayı başlatılmadı."
    count = sum(bool(task.get("done")) for task in _tasks(profile))
    if not count:
        return "Temizlenecek tamamlanmış görevin yok."
    session.pending_confirm = {"action": "tasks_clear_done", "owner": profile.slug,
                               "digest": completed_digest(profile), "expires": time.time() + 90}
    return f"{count} tamamlanmış görevi silmemi onaylıyor musun? Açık görevlerin korunacak."


def clear_done_confirmed(profile, proposal) -> str:
    from modules import requests_state
    requests_state.check()
    if (not isinstance(proposal, dict) or proposal.get("owner") != profile.slug
            or type(proposal.get("expires")) not in (int, float)
            or not time.time() <= proposal["expires"] <= time.time() + 90
            or proposal.get("digest") != completed_digest(profile)):
        return "Görev silme onayı geçersiz, süresi dolmuş veya tamamlanan görevler değişmiş; silmedim."
    before = list(_tasks(profile))
    try:
        requests_state.check()
        count = clear_done(profile)
    except BaseException:
        profile.data["tasks"] = before
        raise
    return f"{count} tamamlanmış görevi sildim."


def counts(profile) -> tuple[int, int]:
    ts = _tasks(profile)
    return sum(1 for t in ts if t["done"]), len(ts)


def list_text(profile) -> str:
    """Salt-okunan görev listesi cevabı: profil verisini değiştirmez."""
    open_ = [x for x in _tasks(profile) if not x["done"]]
    if not open_:
        return "Açık görevin yok."
    return f"{len(open_)} açık görevin var: " + "; ".join(x["text"] for x in open_[:8]) + "."


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
completed_digest = _locked(completed_digest)
clear_done_preview = _locked(clear_done_preview)
clear_done_confirmed = _locked(clear_done_confirmed)
counts = _locked(counts)
