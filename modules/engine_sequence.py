"""engine sequence; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def _split_steps(runtime, command: str) -> list[str] | None:
    """'önce A, sonra B' / 'A ardından B' -> [A, B]. Tek adımlıysa None. En fazla 5 adım."""
    text = runtime.re.sub(r"^\s*önce\s+", "", command, flags=runtime.re.I)
    if text == command and not runtime.re.search(r"\s(?:ardından|akabinde)\s", command, runtime.re.I) \
            and not runtime.re.search(r"\bönce\b.+\bsonra\b", command, runtime.re.I):
        return None
    parts = [x.strip(" ,.") for x in runtime._STEP_SPLIT.split(text)]
    parts = [x for x in parts if len(x) >= 3]
    return parts[:5] if len(parts) >= 2 else None

def _run_steps(runtime, steps: list[str]) -> str:
    from modules.command_manager import awaiting_input
    session, owner = runtime._session(), runtime.profile.slug
    session._in_multi = True
    out = []
    try:
        for i, st in enumerate(steps, 1):
            if runtime.flags.get('closing') or runtime.stop_event.is_set():
                out.append("(Jarvis kapanıyor; kalan adımları çalıştırmadım.)")
                break
            reply = runtime.handle(st)
            out.append(f"{i}. {reply}")
            if getattr(reply, 'ok', None) is True:
                out.append('(Bu adım doğrulanamadı; ona bağlı kalan adımları çalıştırmadım.)')
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
