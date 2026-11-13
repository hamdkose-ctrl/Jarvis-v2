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

def _emit_for(runtime, owner, kind, text, source="", rid=None):
    """Background events keep the captured user's identity, never the mutable active profile."""
    pass  # Shared fields are held by the explicit engine context.
    with runtime._event_lock:
        runtime._log_id += 1
        runtime.event_log.append({"id": runtime._log_id, "kind": kind, "text": text, "source": source,
                          "user": owner.name, "rid": rid})
        del runtime.event_log[:-200]
        row = runtime.history.append(owner.slug, kind, text, source)
        runtime.event_log[-1]["hid"] = (row or {}).get("id")
        metadata = {'user': owner.slug, 'mid': (row or {}).get('id'), 'rid': rid}
        if kind=='assistant' and rid and getattr(runtime,'response_waiters',None) is not None:
            runtime.response_waiters.publish(owner.slug,rid,text)
    if owner.slug == runtime.pc_profile().slug and runtime._ui is not None:
        try:
            if getattr(runtime._ui, 'event_metadata', False) is True:
                runtime._ui(kind, text, source, metadata=metadata)
            else:
                runtime._ui(kind, text, source)
        except Exception:
            runtime._record_failure('main.py:_emit_for')

REMINDER_SPEECH_TTL_SECONDS = 120.0


def reminder_speech_id(event) -> str:
    """The stable speech identity of one reminder record (Core names it, voice carries it).

    The record id, not the occurrence time: a rescheduled or skipped reminder keeps
    its identity, so an utterance still waiting in the queue can be dropped when the
    user corrects the record. It is deliberately NOT the duplicate-delivery identity:
    a repeating record announces the same sentence at every occurrence under this same
    id, so the occurrence has to be named separately (``reminder_occurrence_id``).
    """
    return f"reminder:{event.get('id')}"


def reminder_occurrence_id(event) -> str:
    """The speech identity of one ringing of a reminder record.

    ``due_events`` stamps ``fired`` with the occurrence it just released (a snoozed
    repeat rings with its snooze time) and a one-off record keeps its own ``when``,
    so this names the occurrence while ``reminder_speech_id`` names the record. Two
    occurrences of the same daily reminder therefore stay two separate deliveries,
    and a retry of the occurrence that was already heard is still the same one.
    """
    return f"{reminder_speech_id(event)}@{event.get('fired') or event.get('when')}"


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
                # The written notice is delivered either way; the TTL only bounds how
                # long the audio stays honest while Jarvis is busy with an answer.
                runtime.events.put(("say", msg, owner.slug, {
                    "kind": "reminder", "event_id": reminder_speech_id(ev),
                    "turn_id": reminder_occurrence_id(ev),
                    "ttl_seconds": REMINDER_SPEECH_TTL_SECONDS}))

def _reminder_loop(runtime):
    while not runtime.stop_event.is_set():
        try:
            runtime._reminder_tick()
        except Exception:
            runtime._record_failure('main.py:_reminder_loop')
        runtime.stop_event.wait(5)


def _scheduled_brief_facts(runtime) -> list[str]:
    """Reuse the existing read-only day plan and add only current Core work-state facts."""
    from modules import continuity, main_planner
    now = runtime.datetime.now()
    facts = [f"Şu an: {now.strftime('%d.%m.%Y %H:%M')}, {runtime._DAYS[now.weekday()]}. Kullanıcının adı: {runtime.profile.name}."]
    try:
        wx = runtime.weather.report(runtime.profile.data['prefs'].get('city') or None)
        if wx:
            facts.append('Hava: ' + ' '.join(wx.split()))
    except Exception:
        runtime._record_failure('modules/engine_background.py:_scheduled_brief_facts.weather')
        facts.append('Hava kaynağına şu anda ulaşılamadı.')
    try:
        facts.append(main_planner._day_plan(runtime, 0))
    except Exception:
        runtime._record_failure('modules/engine_background.py:_scheduled_brief_facts.day_plan')
        facts.append('Günlük plan kaynaklarına şu anda ulaşılamadı.')
    try:
        from modules import outlook, worktrack
        if outlook.installed():
            facts.append('İş maili (Outlook): ' + outlook.unread_mail())
            line = worktrack.brief_line()
            if line:
                facts.append(line)
    except Exception:
        runtime._record_failure('modules/engine_background.py:_scheduled_brief_facts.outlook')
        facts.append('İş maili kaynağına şu anda ulaşılamadı.')
    try:
        snap = continuity.snapshot(runtime.profile.slug)
        goal = snap.get('goal') or {}
        task = snap.get('task') or {}
        pending = []
        completed = []
        blocked = []
        if goal.get('state') == 'approval':
            pending.append('açık hedef kullanıcı onayı bekliyor')
        if task.get('state') == 'approval':
            pending.append('açık görev işi kullanıcı onayı bekliyor')
        if goal.get('state') in {'done', 'complete', 'completed'}:
            completed.append('son hedef tamamlandı')
        if task.get('state') in {'done', 'complete', 'completed'}:
            completed.append('son görev işi tamamlandı')
        if goal.get('state') in {'blocked', 'failed', 'error'}:
            blocked.append('hedef=' + str(goal.get('state')))
        if task.get('state') in {'blocked', 'failed', 'error'}:
            blocked.append('görev=' + str(task.get('state')))
        if pending:
            facts.append('Bekleyen onay: ' + '; '.join(pending) + '.')
        if completed:
            facts.append('Tamamlanan iş: ' + '; '.join(completed) + '.')
        if blocked:
            facts.append('Engel: ' + '; '.join(blocked) + '.')
    except Exception:
        runtime._record_failure('modules/engine_background.py:_scheduled_brief_facts.continuity')
        facts.append('Görev durumuna şu anda ulaşılamadı.')
    return facts


def _scheduled_brief(runtime, startup_delay: bool = False) -> None:
    """Run the existing morning brief contract from the engine scheduler without a second scheduler/state system."""
    from types import SimpleNamespace
    from modules import main_planner
    if startup_delay and runtime.stop_event.wait(8):
        return
    claim = None
    try:
        owner = runtime.pc_profile()
        now = runtime.datetime.now()
        today = now.strftime('%Y-%m-%d')
        if not 5 <= now.hour < 12 or runtime.flags.get('sleep'):
            return
        if owner.data['prefs'].get('morning_brief') is False:
            return
        with main_planner._BRIEF_LOCK:
            if main_planner._brief_done(owner, today) or (owner.slug, today) in main_planner._BRIEF_RUNNING:
                return
            claim = (owner.slug, today)
            main_planner._BRIEF_RUNNING.add(claim)
        owned = SimpleNamespace(**vars(runtime))
        owned.profile = owner
        owned._brief_facts = lambda: _scheduled_brief_facts(owned)
        owned._llm.set_user_context(owner.slug)
        text = main_planner._daily_briefing(owned)
        if now.weekday() == 4:
            try:
                from modules import outlook, worktrack
                if outlook.installed():
                    text += ' ' + worktrack.report('weekly')
            except Exception:
                runtime._record_failure('modules/engine_background.py:_scheduled_brief.weekly')
        if runtime.stop_event.is_set() or runtime.pc_profile().slug != owner.slug or runtime.flags.get('sleep'):
            return
        with main_planner._BRIEF_LOCK:
            if main_planner._brief_done(owner, today):
                return
            owner.set_pref('last_brief', today)
        runtime._emit_for(owner, 'assistant', text)
        runtime.events.put(('say', text, owner.slug, {'kind': 'notice', 'event_id': f'brief:{today}'}))
    except Exception:
        runtime._record_failure('modules/engine_background.py:_scheduled_brief')
    finally:
        if claim:
            with main_planner._BRIEF_LOCK:
                main_planner._BRIEF_RUNNING.discard(claim)


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