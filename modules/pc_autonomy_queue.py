"""Otonomi kuyruğu: Jarvis'in kendi kendine alacağı işler (sınırlı).

Kullanıcı politikası: "kendi kendine iş uydurmasın, ama verdiğim işleri kendisi
zamanında yapsın". Bu modül yalnız **önceden verilmiş** işleri zamanı gelince
çalıştırır; yeni iş uydurmaz.

Kurallar:
- Her iş için **günlük bütçe** (varsayılan 20 adım) ve **çalışma bütçesi** (6 adım).
- **Ana anahtar kapalıysa hiç çalışmaz** (`autonomy_enabled` ayarı yoksa kapalı sayılır).
- Riskli adım → durur, `paused` olarak işaretlenir, bir dahaki turda tekrar denenmez;
  kullanıcı onaylayınca devam eder.
- Her çalışma rapor üretir (`pc_autonomy`).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from modules import pc_autonomy
from modules.diagnostics import record_failure as _record_failure

QUEUE_FILE = Path.home() / ".jarvis" / "autonomy" / "queue.json"
DAILY_STEP_BUDGET = 20
DISABLED = "Otonomi kapalı; kuyruktaki işleri çalıştırmadım."
QUEUED = "“{goal}” kuyruğa eklendi."
NOTHING = "Sırası gelen iş yok."


def _load() -> dict:
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Kuyruk dosyası henüz yok: bu bir HATA değil, ilk çalıştırma. Sessizce boş
        # kuyruk döner (tanı kaydı yazmak log'u kirletiyordu).
        return {"enabled": False, "spent_today": 0, "day": time.strftime("%Y-%m-%d"), "goals": []}
    except Exception:
        # Bozuk/okunamayan dosya: kapalı ve boş kuyruk — otonomi kendiliğinden açılmaz.
        _record_failure("modules/pc_autonomy_queue.py:_load")
        return {"enabled": False, "spent_today": 0, "day": time.strftime("%Y-%m-%d"), "goals": []}


def _save(state: dict) -> None:
    try:
        QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        _record_failure("modules/pc_autonomy_queue.py:_save")


def enabled() -> bool:
    return bool(_load().get("enabled"))


def set_enabled(flag: bool) -> dict:
    state = _load()
    state["enabled"] = bool(flag)
    _save(state)
    return {"status": "ok", "text": "Otonomi açıldı." if flag else "Otonomi kapatıldı."}


def enqueue(goal: str, *, when: float | None = None) -> dict:
    """İşi kuyruğa ekler; `when` verilmezse hemen sıraya girer."""
    text = str(goal or "").strip()
    if not text:
        return {"status": "empty", "text": "Hangi işi kuyruğa ekleyeceğimi söylemedin."}
    state = _load()
    state.setdefault("goals", []).append({"goal": text, "due": when or time.time(), "status": "waiting"})
    _save(state)
    return {"status": "queued", "text": QUEUED.format(goal=text[:60])}


def pending() -> list[dict]:
    return [g for g in _load().get("goals", []) if g.get("status") in ("waiting", "paused")]


def _roll_day(state: dict) -> dict:
    today = time.strftime("%Y-%m-%d")
    if state.get("day") != today:
        state["day"] = today
        state["spent_today"] = 0
    return state


def run_due(*, abort=None, now: float | None = None) -> dict:
    """Sırası gelen ilk işi çalıştırır (günlük bütçe içinde)."""
    if not enabled():
        return {"status": "disabled", "text": DISABLED}
    state = _roll_day(_load())
    if state.get("spent_today", 0) >= DAILY_STEP_BUDGET:
        return {"status": "budget", "text": f"Günlük otonomi bütçesi ({DAILY_STEP_BUDGET} adım) doldu."}
    moment = now or time.time()
    goal = next((g for g in state.get("goals", [])
                 if g.get("status") == "waiting" and float(g.get("due") or 0) <= moment), None)
    if goal is None:
        return {"status": "idle", "text": NOTHING}
    result = pc_autonomy.execute(goal["goal"], abort=abort)
    goal["status"] = {"done": "done", "paused": "paused"}.get(result["status"], "failed")
    goal["last"] = {"status": result["status"], "text": result.get("text", "")[:200],
                    "report": result.get("report", "")}
    state["spent_today"] = int(state.get("spent_today", 0)) + len(result.get("steps") or [])
    _save(state)
    return {"status": goal["status"], "text": result.get("text", ""), "report": result.get("report", "")}


def summary() -> str:
    state = _load()
    rows = state.get("goals", [])
    waiting = sum(1 for g in rows if g.get("status") == "waiting")
    paused = sum(1 for g in rows if g.get("status") == "paused")
    return (f"Otonomi {'açık' if state.get('enabled') else 'kapalı'}; {waiting} bekleyen, "
            f"{paused} onay bekleyen iş; bugün {state.get('spent_today', 0)}/{DAILY_STEP_BUDGET} adım.")


# --- Periyodik döngü (otonomi saati) --------------------------------------
TICK_SECONDS = 120.0


def foreground_window() -> str:
    """Öndeki pencerenin başlığı. Canlı kusur (25 Kasım): `find_window("")` boş sorguyla
    "pencere yok" döndüğü için uyanıklık hiç aday üretmiyordu."""
    try:
        import win32gui
        handle = win32gui.GetForegroundWindow()
        title = str(win32gui.GetWindowText(handle) or "")
        if title:
            return title
        # Başlıksız ön pencere (görev çubuğu/Shell_Flyout gibi): kök sahibine çık.
        GA_ROOT = 2
        root = win32gui.GetAncestor(handle, GA_ROOT)
        title = str(win32gui.GetWindowText(root) or "") if root else ""
        if title:
            return title
        owner = win32gui.GetWindow(handle, 4)      # GW_OWNER
        return str(win32gui.GetWindowText(owner) or "") if owner else ""
    except Exception:
        _record_failure("modules/pc_autonomy_queue.py:foreground_window")
        return ""


def _cooldown_seconds(settings: dict) -> float:
    """Aynı anda gelen adaylar kullanıcıyı boğmasın: bildirimler arası en kısa süre.

    Belge "10 dakikada en fazla bir bildirim" diyordu ama kodda böyle bir sınır
    yoktu; yalnız aynı aday bir daha söylenmiyordu. Sınır artık gerçekten uygulanıyor.
    """
    from modules import awareness_watch
    default_minutes = awareness_watch.COOLDOWN_SECONDS / 60
    try:
        minutes = float((settings or {}).get('watch_cooldown_minutes', default_minutes))
    except (TypeError, ValueError):
        minutes = default_minutes
    return max(0.0, min(minutes, 240.0)) * 60.0


_LAST_ANNOUNCE = 0.0


def watch_tick(runtime=None, *, hour=None, now=None) -> list[dict]:
    """Uyanıklık (A8): kapalıysa hiç aday üretmez; adaylar yalnız günlüğe yazılır.

    `hour` yalnız testler içindir: duvar saatine bağlı testler CI'da farklı saatte
    düşüyordu (sessiz saat 22–08). Üretimde None → gerçek saat kullanılır.
    """
    from modules import awareness_watch
    # Ayarın tek sahibi `config.load_settings`; canlı kusur (25 Kasım): varsayılan
    # `profile.settings` diye bir alan yok, bu yüzden uyanıklık hiç açılamıyordu.
    try:
        from config import load_settings
        settings = load_settings() or {}
    except Exception:
        _record_failure("modules/pc_autonomy_queue.py:watch_tick_settings")
        settings = {}
    if not awareness_watch.enabled(settings):
        return []
    state = {"window": foreground_window()}
    # Mail/takvim geri geldi (kullanıcı isteği 26 Kasım 16:5x): "bir şey olduğunda söylesin".
    state.update(_inbox_and_calendar())
    items = awareness_watch.candidates(state, seen=_SEEN, hour=hour,
                                       quiet=awareness_watch.quiet_bounds(settings))
    # Ses açık, ama **gereksiz bilgi yok** (kullanıcı isteği 26 Kasım): pencere değişimi
    # gibi zaten gözünün önünde olan şeyler konuşulmaz; yalnız günlüğe yazılır.
    speak_windows = _truthy(settings.get("watch_window_notice"))
    global _LAST_ANNOUNCE
    instant = time.time() if now is None else float(now)
    if items and instant - _LAST_ANNOUNCE < _cooldown_seconds(settings):
        # Bekleme süresi dolmadı: adaylar bir sonraki uygun tike kalır, kaydedilmez.
        return []
    spoken = 0
    for item in items:
        if runtime is not None and hasattr(runtime, "log"):
            runtime.log.info("uyanıklık: %s", item["text"])
        if item.get("kind") == "window" and not speak_windows:
            continue
        _announce(item["text"])
        spoken += 1
    if spoken:
        _LAST_ANNOUNCE = instant
    awareness_watch.mark_seen(items, _SEEN)
    return items


_SEEN: set[str] = set()


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "evet", "acik", "açık", "on"}


def _inbox_and_calendar() -> dict:
    """Okunmamış mail / yaklaşan takvim: uyanıklığın gerçek besleyicisi.

    Canlı bulgu (26 Kasım): `awareness_watch.candidates` bu iki alanı okuyordu ama
    `watch_tick` hiç doldurmuyordu — yani mail/takvim hiç kontrol edilmiyordu.
    Google bağlı değilse sessizce boş döner (hata kullanıcıya gösterilmez).
    """
    state: dict = {}
    try:
        from modules import google_api
        if google_api.connected():
            unread = google_api.unread_count()
            if isinstance(unread, int) and unread > 0:
                state["unread_mail"] = unread
    except Exception:
        _record_failure("modules/pc_autonomy_queue.py:_inbox_and_calendar:mail")
    try:
        from modules import google_api
        if google_api.connected():
            events = google_api.day_events(0)
            now = __import__("datetime").datetime.now()
            soonest = None
            for start, _summary in events:
                if start is None:
                    continue
                minutes = (start - now).total_seconds() / 60.0
                if minutes >= 0 and (soonest is None or minutes < soonest):
                    soonest = minutes
            if soonest is not None:
                state["next_event_minutes"] = int(soonest)
    except Exception:
        _record_failure("modules/pc_autonomy_queue.py:_inbox_and_calendar:calendar")
    return state


def _announce(text: str) -> bool:
    """Bildirimi seslendirir — ses varsayılan **açık**, kapatmak için `watch_voice=false`.

    Canlı düzeltme (26 Kasım): kullanıcı "sesi aç ama gereksiz bilgi vermesin" dedi.
    Ses yolu açık kalır; gereksizlik `watch_tick` içinde süzülür (pencere değişimi
    varsayılan olarak konuşulmaz).
    """
    try:
        from config import load_settings
        settings = load_settings() or {}
    except Exception:
        _record_failure("modules/pc_autonomy_queue.py:_announce_settings")
        return False
    if "watch_voice" in settings and not _truthy(settings.get("watch_voice")):
        return False
    try:
        from modules import voice_runtime
        return bool(voice_runtime.announce_active(text, background=True))
    except Exception:
        _record_failure("modules/pc_autonomy_queue.py:_announce")
        return False


def tick_loop(stop_event, *, interval: float = TICK_SECONDS, runner=None, sleeper=None,
              max_ticks: int | None = None) -> None:
    """Arka planda periyodik olarak kuyruğa bakar. Ana anahtar kapalıysa hiç iş yapmaz.

    `runner`/`sleeper` test için enjekte edilebilir; üretimde gerçek `run_due` ve
    `time.sleep` kullanılır.
    """
    import time as _time
    run = runner or run_due
    wait = sleeper or _time.sleep
    runtime_holder = getattr(stop_event, "runtime", None)
    ticks = 0
    while stop_event is not None and not stop_event.is_set():
        if max_ticks is not None and ticks >= max_ticks:
            return
        ticks += 1
        try:
            if enabled():
                result = run(abort=stop_event)
                if result.get("status") not in ("idle", "disabled", None):
                    _record_failure("modules/pc_autonomy_queue.py:tick")   # yalnız tanı izi
        except Exception:
            _record_failure("modules/pc_autonomy_queue.py:tick_loop")
        if stop_event is None:
            return
        wait(interval)
