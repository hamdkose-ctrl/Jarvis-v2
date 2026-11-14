"""engine queue; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib
import re

# Exact owner+job-ID protocols only; natural-language intent still uses Brain.
_FAST_GOAL_ID = re.compile(r'hedef (sonucu|iptal) ([a-f0-9]{16})[.!?]?\Z')

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
    if command in ("dur", "stop"):
        # Stop speech immediately, but do not mistake a bare utterance for
        # permission to cancel every independent queued/running request.
        runtime.voice.stop_speaking()
        name = user or runtime.pc_profile().name
        owner = runtime.slugify(name)
        outcome, _target = runtime.requests_state.cancel_unambiguous(owner)
        if outcome == 'ambiguous':
            runtime._emit_for(
                runtime._get_profile(name), 'assistant',
                'Birden fazla istek çalışıyor. Hiçbiri iptal edilmedi. '
                'Durdurmak istediğin hedefi kimliğiyle seç veya açıkça '
                '“tüm istekleri iptal et” de.', source, rid=rid,
            )
        elif outcome == 'none':
            runtime._emit_for(
                runtime._get_profile(name), 'assistant',
                'Konuşma kesildi. İptal edilecek tek bir aktif istek yok; '
                'arka plan hedefini durdurmak için hedef kimliğini seç.',
                source, rid=rid,
            )
        return False
    if command == "tüm istekleri iptal et":
        # Explicit all-request scope. This still does not cancel GoalState
        # jobs, which must use their owner-bound goal ID control.
        owner = runtime.slugify(user or runtime.pc_profile().name)
        runtime.voice.stop_speaking()
        runtime.requests_state.cancel(owner)
        return False
    if command == "rehberi durdur":
        from modules import pc_guide
        owner = runtime.slugify(user or runtime.pc_profile().name)
        pc_guide.stop(owner)
        runtime.voice.stop_speaking()
        return False
    owner = runtime.slugify(user or runtime.pc_profile().name)
    rid = rid or runtime.secrets.token_hex(16)
    if not runtime.requests_state.register(owner, rid):
        return False
    user = user or runtime.pc_profile().name
    # An explicit goal ID needs no semantic model or mutable foreground
    # session. Keep status/cancel responsive even while the normal engine
    # event loop holds as_user for an unrelated, long-running task.
    # Only read_result_command's exact RESULT route is admitted here:
    # "hedef cevap <id> ..." mutates a pending question and stays in Core.
    exact = _FAST_GOAL_ID.fullmatch(command)
    if exact is not None:
        profile = runtime._get_profile(user)
        with runtime.requests_state.activate(owner, rid):
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
        with runtime.requests_state.activate(owner,rid):
            runtime._emit_for(profile,'user',text,source,rid=rid)
            runtime._emit_for(profile,'assistant',
                              goal_executor.fast_status(owner, details=status == 'details'),
                              source,rid=rid)
        return True
    runtime.events.put(("command", text, source, user, rid))
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
