"""engine background; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def _start_hang_watch(runtime) -> None:
    """Teşhis: Jarvis donarsa (1,5 dk hiçbir iş parçacığı ilerleyemezse ya da günlük kilidi takılırsa) bütün
    iş parçacıklarının o anki yerini ~/.jarvis/donma_kaydi.txt dosyasına yazar. Davranışı değiştirmez."""
    import faulthandler
    try:
        fh = open(runtime.DATA_DIR / "donma_kaydi.txt", "a", encoding="utf-8")
    except OSError:
        return

    def loop():
        try:
            while not runtime.stop_event.is_set():
                try:
                    faulthandler.dump_traceback_later(90, repeat=False, file=fh, exit=False)
                    for h in runtime.logging.getLogger().handlers + runtime.logging.getLogger("jarvis").handlers:
                        lk = getattr(h, "lock", None)
                        if lk is not None:
                            if lk.acquire(timeout=45):
                                lk.release()
                            else:
                                fh.write(f"\n==== {runtime.datetime.now():%Y-%m-%d %H:%M:%S} günlük kilidi 45 sn açılmadı ====\n")
                                fh.flush()
                                faulthandler.dump_traceback(file=fh, all_threads=True)
                except Exception:   # noqa: BLE001 - teşhis aracı Jarvis'i asla durdurmasın
                    runtime._record_failure('main.py:loop')
                    pass
                runtime.stop_event.wait(20)
        finally:
            faulthandler.cancel_dump_traceback_later()
            fh.close()

    runtime.threading.Thread(target=loop, daemon=True, name="donma-izleyici").start()

def _emit_for(runtime, owner, kind, text, source=""):
    """Background events keep the captured user's identity, never the mutable active profile."""
    pass  # Shared fields are held by the explicit engine context.
    with runtime._event_lock:
        runtime._log_id += 1
        runtime.event_log.append({"id": runtime._log_id, "kind": kind, "text": text, "source": source,
                          "user": owner.name, "rid": None})
        del runtime.event_log[:-200]
        row = runtime.history.append(owner.slug, kind, text, source)
        runtime.event_log[-1]["hid"] = (row or {}).get("id")
        metadata = {'user': owner.slug, 'mid': (row or {}).get('id'), 'rid': None}
    if owner.slug == runtime.pc_profile().slug and runtime._ui is not None:
        try:
            if getattr(runtime._ui, 'event_metadata', False) is True:
                runtime._ui(kind, text, source, metadata=metadata)
            else:
                runtime._ui(kind, text, source)
        except Exception:
            runtime._record_failure('main.py:_emit_for')

def _reminder_tick(runtime):
    for name in runtime.list_users():
        owner = runtime._get_profile(name)
        for ev in owner.due_events(runtime.datetime.now()):
            msg = f"Hatırlatma: {ev['title']}"
            runtime._emit_for(owner, "assistant", msg, "hatırlatma")
            topic = owner.data["prefs"].get("ntfy_topic")
            if topic:
                runtime.threading.Thread(target=runtime.notify.send, args=(topic, "Jarvis hatırlatma", ev["title"]), daemon=True).start()
            if owner.slug == runtime.pc_profile().slug:
                runtime.events.put(("say", msg, owner.slug))

def _reminder_loop(runtime):
    while not runtime.stop_event.is_set():
        try:
            runtime._reminder_tick()
        except Exception:
            runtime._record_failure('main.py:_reminder_loop')
        runtime.stop_event.wait(5)

def _handoff_notice(runtime):                 # açılışta (sabah özeti olmayan saatlerde) bekleyen devir notları
    if runtime.stop_event.wait(12):
        return
    try:
        owner = runtime.pc_profile()
        if 5 <= runtime.datetime.now().hour < 12 and owner.data["prefs"].get("morning_brief") is not False:
            return                     # sabah özeti zaten söylüyor
        from modules import handoff
        note = handoff.startup_notice()
        if note and not runtime.stop_event.is_set():
            runtime._emit_for(owner, "assistant", note)
            runtime.events.put(("say", note, owner.slug))
    except Exception:
        runtime._record_failure('main.py:_handoff_notice')

def _learning_notice(runtime):                # haftada bir: kendi hatalarından gelişim raporu (yeterli kullanım varsa)
    if runtime.stop_event.wait(90):
        return
    try:
        from modules import learning
        owner = runtime.pc_profile()
        runtime._llm.set_user_context(owner.slug)
        note = learning.startup_notice(owner)
        if note and not runtime.stop_event.is_set() and owner.slug == runtime.pc_profile().slug:
            runtime.emit("system", note)
    except Exception:
        runtime._record_failure('main.py:_learning_notice')

def _google_health(runtime):                  # Google izni düştüyse ya da yarın düşecekse günde bir kez söyle
    runtime.stop_event.wait(20)
    while not runtime.stop_event.is_set():    # Jarvis günlerce açık kalsa da her 6 saatte bir bakılır
        try:
            today = runtime.datetime.now().strftime("%Y-%m-%d")
            home = runtime.pc_profile()
            if home.data["prefs"].get("google_warned") != today:
                runtime._llm.set_user_context(home.slug)
                msgs = runtime.google_api.health()
                if msgs:
                    home.set_pref("google_warned", today)
                    text = " ".join(msgs)
                    runtime._emit_for(home, "assistant", text)
                    runtime.events.put(("say", text, home.slug))
                    topic = home.data["prefs"].get("ntfy_topic")
                    if topic:          # telefon bildirimi açıksa oraya da
                        runtime.notify.send(topic, "Jarvis: Google izni", text)
        except Exception:
            runtime._record_failure('main.py:_google_health')
        runtime.stop_event.wait(6 * 3600)
