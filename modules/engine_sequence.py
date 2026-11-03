"""engine sequence; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations

def _run_steps(runtime, steps: list[str]) -> str:
    """Her adım KENDİ canonical kararıyla sırayla çalışır; ham adım eski zincire dönmez.

    `brain_entry.run_step` adım için prepare -> handoff kurar: owner/istek kimliği turn'ün,
    semantic karar adımın (outer cümlenin Understanding'i ödünç verilmez; outer entry bağlıyken
    `runtime.handle(step)` ile ikinci bir yorumlama yoktur). Adım doğrulanamazsa, needs-input/onay
    beklerse, kullanıcı değişirse veya Jarvis kapanırsa sonraki adım çalışmaz."""
    from modules.brain_entry import run_step
    from modules.command_manager import awaiting_input
    session, owner = runtime._session(), runtime.profile.slug
    session._in_multi = True
    out = []
    try:
        for i, st in enumerate(steps, 1):
            if runtime.flags.get('closing') or runtime.stop_event.is_set():
                out.append("(Jarvis kapanıyor; kalan adımları çalıştırmadım.)")
                break
            reply, feedback = run_step(runtime, st)
            out.append(f"{i}. {reply}")
            if getattr(reply, 'ok', None) is False:
                out.append('(Bu adım doğrulanamadı; ona bağlı kalan adımları çalıştırmadım.)')
                break
            if getattr(feedback, 'result_status', 'handled') != 'handled':
                out.append('(Bu adım yanıt veya onay bekliyor; kalan adımları yanıtından sonra tekrar söyle.)')
                break
            if runtime.flags.get('closing') or runtime.stop_event.is_set():
                out.append("(Jarvis kapanıyor; kalan adımları çalıştırmadım.)")
                break
            if runtime.profile.slug != owner:
                out.append("(Kullanıcı değişti; kalan adımları yeni kullanıcıyla tekrar söyle.)")
                break
            if awaiting_input(session):
                out.append("(Bu adım yanıt veya onay bekliyor; kalan adımları yanıtından sonra tekrar söyle.)")
                break
    finally:
        session._in_multi = False
        session.speech_override = None  # The aggregate reply must not speak only one step.
    runtime.privacy.audit("çok adımlı komut", f"{len(steps)} adım")
    return "\n".join(out)

def _close_jarvis(runtime):
    runtime.flags['closing'] = True
    runtime.emit("activity", "Jarvis kapatma istendi", "working|Jarvis|Yalnızca Jarvis uygulaması kapanacak; bilgisayar açık kalacak.")
    runtime.threading.Timer(1.8, runtime.stop_event.set).start()
    return "Jarvis'i kapatıyorum. Bilgisayar açık kalacak."
