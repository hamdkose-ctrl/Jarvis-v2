"""engine queue; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib
import re

# Exact owner+job-ID protocols only; natural-language intent still uses Brain.
_FAST_GOAL_ID = re.compile(r'hedef (sonucu|iptal) ([a-f0-9]{16})[.!]?\Z')
# User explicitly selects CREATE: the words after ':' are still natural language
# and are planned by the existing owner-pinned Scheduler/Brain planner.
# No inference about an ambiguous conversational follow-up is made here.
_INDEPENDENT_GOAL = re.compile(r'yeni (?:bağımsız )?hedef\s*:\s*(.*)\Z', re.IGNORECASE | re.DOTALL)
# STT commonly omits a colon. Require a deliberately spoken CREATE verb
# rather than promoting conversational "yeni hedef ne ..." into an action.
_INDEPENDENT_VOICE_GOAL = re.compile(
    r'yeni bağımsız hedef oluştur\s*[,.:]?\s+(.+)\Z', re.IGNORECASE | re.DOTALL,
)


def _release_inline_voice_pause(runtime, source):
    """Inline completion never reaches engine_loop's usual microphone release.

    VoiceSession.submit_voice pauses capture for queued commands. Explicit
    fast results and fast status have no queue item to clear that flag. Only
    release the pause for a successfully handled voice turn; the existing
    speaker/device guard still prevents recognizing Jarvis's own audio.
    """
    if source == "ses":
        runtime.pause_listening.clear()


def _notify_waiting_while_busy(runtime, owner, user, source, rid):
    """Non-final, owner-scoped queue acknowledgment; never start another turn.

    An HTTP phone response waiter only accepts assistant completions, not a
    system activity notice, so this cannot masquerade as the actual result.
    """
    lock = getattr(runtime, '_execution_lock', None)
    if lock is None:
        return False
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return False
    try:
        if source in ('ses', 'yazı'):
            profile = runtime.pc_profile()
            if profile.slug != owner:
                return False
        else:
            registered = runtime.match_user(user)
            if not registered or runtime.slugify(registered) != owner:
                return False
            profile = runtime._get_profile(registered)
            if profile.slug != owner:
                return False
        runtime._emit_for(
            profile, 'system',
            'İsteğin sıraya alındı. Önceki uzun işlem bitince işlenecek; '
            'kuyruk bekleme süresi en fazla 5 dakika.',
            source, rid=rid,
        )
        return True
    except Exception:
        # A UI notification is never an authority to retry/destroy the
        # already registered command.
        runtime._record_failure('modules/engine_queue.py:queue_wait_notice')
        return False


def submit(runtime, text: str, source: str = "yazı", user: str | None = None, rid: str | None = None) -> bool:
    """Arayüzden ya da telefondan gelen komutu motora iletir; 'dur' okumayı keser.
    user: komutu gönderen kişi (telefonlar). Boşsa bilgisayardaki aktif kullanıcı.
    Kuyruğa alındıysa True, doğrudan durdurulduysa veya reddedildiyse False döner."""
    text = text.strip()
    if not text:
        return False
    command = runtime._tr_lower(text).strip(" .!")
    if command in ("sus", "yeter", "sesini kes", "konuşmayı kes"):
        # Voice-only interruption must not cancel Core work or an active request.
        runtime.voice.stop_speaking()
        return False
    if command in ("dur", "stop", "tüm istekleri iptal et"):
        # Never select the only live request: it may be a background planner.
        # A bare stop can interrupt only an actively executing foreground turn.
        runtime.voice.stop_speaking()
        name = user or runtime.pc_profile().name
        owner = runtime.slugify(name)
        outcome, _target = runtime.requests_state.cancel_foreground(owner)
        if command == "tüm istekleri iptal et":
            reply = ('Toplu iptal devre dışı. Yalnız aktif foreground işlemine '
                     'durdurma istendi; arka plan hedefleri korunuyor. '
                     'Tek hedefi iptal etmek için “hedef iptal <kimlik>” de.')
        elif outcome == 'ambiguous':
            reply = ('Birden fazla foreground isteği çalışıyor. Hiçbiri iptal edilmedi. '
                     'İptal edeceğin hedefi kimliğiyle belirt.')
        elif outcome == 'none':
            reply = ('Konuşma kesildi. İptal edilecek aktif foreground isteği yok. '
                     'Arka plan hedefleri çalışmaya devam ediyor.')
        else:
            reply = None
        if reply is not None:
            runtime._emit_for(runtime._get_profile(name), 'assistant', reply, source, rid=rid)
        return False
    if command == "rehberi durdur":
        from modules import pc_guide
        owner = runtime.slugify(user or runtime.pc_profile().name)
        pc_guide.stop(owner)
        runtime.voice.stop_speaking()
        return False
    owner = runtime.slugify(user or runtime.pc_profile().name)
    rid = rid or runtime.secrets.token_hex(16)
    # A second ordinary conversation may wait behind a synchronous legacy
    # task. Keep a finite queue admission window (5 min), then start its own
    # 90s execution clock only if it really reaches the engine. This is NOT
    # background execution or an extension of effect permissions.
    if not runtime.requests_state.register(
            owner, rid, seconds=300, execution_seconds=90):
        return False
    user = user or runtime.pc_profile().name
    # A deliberately selected independent CREATE can be admitted while an
    # unrelated legacy foreground turn holds the mutable profile lock.
    # No second executor/model: the existing owner-pinned Scheduler does all
    # planning, and only allowlisted read-only DAGs may actually run there.
    # Without a live Scheduler, never silently run the goal in this thread.
    selected_goal = (_INDEPENDENT_GOAL.fullmatch(text) or
                     (_INDEPENDENT_VOICE_GOAL.fullmatch(text)
                      if source == 'ses' else None))
    if selected_goal is not None:
        profile = runtime._get_profile(user)
        with runtime.requests_state.activate(owner, rid, foreground=True):
            runtime._emit_for(profile, 'user', text, source, rid=rid)
            from modules import llm, task_queue
            token = llm._key_context.set(owner)
            try:
                # Unlike normal queued turns, no as_user() call will authorize
                # this route. Verify the owner against the registered profile
                # list, or the selected local PC user for local inputs.
                registered = runtime.match_user(user)
                local_pc = (source in ('yazı', 'ses')
                            and runtime.pc_profile().slug == owner)
                if (profile.slug != owner or
                        not (local_pc or (registered is not None and
                                          runtime.slugify(registered) == owner))):
                    reply = 'Kullanıcı kimliği doğrulanamadı; hedef oluşturulmadı.'
                elif not selected_goal.group(1).strip():
                    reply = 'Yeni hedef için somut bir istek söyle; iş başlatılmadı.'
                elif len(selected_goal.group(1)) > 20000:
                    reply = 'Yeni hedef çok uzun; iş başlatılmadı.'
                elif not task_queue.scheduler_active():
                    reply = ('Arka plan görev yürütücüsü şu anda hazır değil; '
                             'yeni hedef kaydedilmedi veya çalıştırılmadı.')
                else:
                    from modules import canonical_planning_queue
                    try:
                        _job_id, reply = canonical_planning_queue.enqueue(
                            owner, rid, selected_goal.group(1).strip(),
                        )
                    except (ValueError, PermissionError, OSError):
                        reply = ('Yeni hedefin güvenli kaydı doğrulanamadı; '
                                 'başka bir görev başlatılmadı. Durumu kontrol et.')
                runtime._emit_for(profile, 'assistant', reply, source, rid=rid)
            finally:
                llm._key_context.reset(token)
        _release_inline_voice_pause(runtime, source)
        return True
    # An explicit goal ID needs no semantic model or mutable foreground
    # session. Keep status/cancel responsive even while the normal engine
    # event loop holds as_user for an unrelated, long-running task.
    # Only read_result_command's exact RESULT route is admitted here:
    # "hedef cevap <id> ..." mutates a pending question and stays in Core.
    exact = _FAST_GOAL_ID.fullmatch(command)
    if exact is not None:
        profile = runtime._get_profile(user)
        with runtime.requests_state.activate(owner, rid, foreground=True):
            # Core's service_store.identity requires the caller's ContextVar
            # to match this authenticated request owner. The main event-loop
            # normally installs it through as_user; this out-of-queue path
            # must bind it *per thread*, never change mutable runtime.profile.
            from modules import llm
            token = llm._key_context.set(owner)
            try:
                runtime._emit_for(profile, 'user', text, source, rid=rid)
                if exact.group(1) == 'sonucu':
                    from modules import canonical_goal_flow
                    reply = canonical_goal_flow.read_result_command(owner, text)
                    if reply is None:
                        reply = 'Bu kimliğe ait sonuç sorgusu doğrulanamadı; iş başlatılmadı.'
                else:
                    from modules import goal_executor
                    try:
                        reply = goal_executor.cancel_job(owner, exact.group(2))
                    except (ValueError, PermissionError, OSError):
                        # Do not reveal another owner's job state or silently
                        # retry an uncertain cancel; existing Core fences decide.
                        reply = ('Bu hedefin iptali doğrulanamadı; başka bir hedefe '
                                 'işlem uygulanmadı. Hedef kartından durumunu kontrol et.')
                runtime._emit_for(profile, 'assistant', reply, source, rid=rid)
            finally:
                llm._key_context.reset(token)
        _release_inline_voice_pause(runtime, source)
        return True
    from modules import brain_entry
    try:
        lane = brain_entry.fast_lane(owner, rid, runtime._tr_lower(text), source)
    except Exception:
        runtime._record_failure('modules/engine_queue.py:fast_lane')
        lane = None   # hızlı yol bozulsa da komut kaybolmaz: normal kuyruğa girer
    status = lane.selection if lane is not None else None
    if status is not None:
        from modules import goal_executor
        profile=runtime._get_profile(user)
        with runtime.requests_state.activate(owner,rid,foreground=True):
            runtime._emit_for(profile,'user',text,source,rid=rid)
            runtime._emit_for(profile,'assistant',
                              goal_executor.fast_status(owner, details=status == 'details'),
                              source,rid=rid)
        _release_inline_voice_pause(runtime, source)
        return True
    runtime.events.put(("command", text, source, user, rid))
    waiting = _notify_waiting_while_busy(runtime, owner, user, source, rid)
    if waiting and source == "ses":
        # VoiceSession.submit_voice paused capture for this accepted command,
        # but the one command loop is still busy with a different turn. There
        # is NO queued consumer available to release this new pause yet.
        # Restore wake capture immediately; the existing VoiceSession
        # speech/capture device fence still blocks echo and overlapping audio.
        # The engine turn will take its own listening pause when it executes.
        _release_inline_voice_pause(runtime, source)
    return True

def submit_audio(runtime, path: str, source: str = "telefon", user: str | None = None, rid: str | None = None) -> bool:
    """Telefonda kaydedilen konuşmayı yazıya çevirip komut olarak işler (tarayıcıda konuşma tanıma yoksa)."""
    user = user or runtime.pc_profile().name
    rid = rid or runtime.secrets.token_hex(16)
    if not runtime.requests_state.register(runtime.slugify(user), rid):
        return False
    runtime.events.put(("audio", path, source, user, rid))
    return True

def submit_photo(runtime, path: str, question: str = "", source: str = "telefon",
                 user: str | None = None, rid: str | None = None) -> bool:
    """Queue a phone photo with the same owner-bound canonical request identity as text/audio."""
    user = user or runtime.pc_profile().name
    owner = runtime.slugify(user)
    rid = rid or runtime.secrets.token_hex(16)
    if not runtime.requests_state.register(owner, rid):
        return False
    runtime.events.put(("photo", path, question.strip()[:300], source, user, rid))
    return True

def _reject_queued_input(runtime):
    pass  # Shared fields are held by the explicit engine context.
    runtime._cur_source = ""
    runtime._cur_rid = None
    runtime.pause_listening.clear()
    runtime.emit("system", "İstek işlenemedi. Kullanıcı seçimini kontrol edip yeniden gönder.")
    runtime.emit("state", "idle")
