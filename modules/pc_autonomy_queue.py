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
        return str(win32gui.GetWindowText(win32gui.GetForegroundWindow()) or "")
    except Exception:
        _record_failure("modules/pc_autonomy_queue.py:foreground_window")
        return ""


def watch_tick(runtime=None) -> list[dict]:
    """Uyanıklık (A8): kapalıysa hiç aday üretmez; adaylar yalnız günlüğe yazılır."""
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
    items = awareness_watch.candidates(state, seen=_SEEN)
    for item in items:
        if runtime is not None and hasattr(runtime, "log"):
            runtime.log.info("uyanıklık: %s", item["text"])
        _announce(item["text"])
    awareness_watch.mark_seen(items, _SEEN)
    return items


_SEEN: set[str] = set()


def _announce(text: str) -> bool:
    """Bildirimi mevcut tek sahibe (voice_runtime.notice) devreder; yoksa sessiz."""
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
