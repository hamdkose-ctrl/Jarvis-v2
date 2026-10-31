"""engine queue; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def submit(runtime, text: str, source: str = "yazı", user: str | None = None, rid: str | None = None) -> bool:
    """Arayüzden ya da telefondan gelen komutu motora iletir; 'dur' okumayı keser.
    user: komutu gönderen kişi (telefonlar). Boşsa bilgisayardaki aktif kullanıcı.
    Kuyruğa alındıysa True, doğrudan durdurulduysa veya reddedildiyse False döner."""
    text = text.strip()
    if not text:
        return False
    if runtime._tr_lower(text).strip(" .!") in ("dur", "sus", "yeter", "stop"):
        from modules import pc_guide
        pc_guide.stop(runtime.slugify(user or runtime.pc_profile().name))
        runtime.voice.stop_speaking()
        runtime.requests_state.cancel(runtime.slugify(user or runtime.pc_profile().name))
        return False
    owner = runtime.slugify(user or runtime.pc_profile().name)
    rid = rid or runtime.secrets.token_hex(16)
    if not runtime.requests_state.register(owner, rid):
        return False
    user = user or runtime.pc_profile().name
    from modules import brain_gates
    status = brain_gates.goal_status_selection(runtime._tr_lower(text))
    if status is not None:
        from modules import goal_executor
        profile=runtime._get_profile(user)
        with runtime.requests_state.activate(owner,rid):
            job=goal_executor.latest(owner)
            runtime._emit_for(profile,'user',text,source,rid=rid)
            formatter = goal_executor.render if status == 'details' else goal_executor.status_summary
            runtime._emit_for(profile,'assistant',formatter(job) if job else 'Kayıtlı hedef yok.',source,rid=rid)
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
