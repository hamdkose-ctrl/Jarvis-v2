"""Native application choices remain owned by the requesting conversation."""
import re
import time

_CLOSE_NAME_MAX = 40


def request_close_app(runtime, name):
    """Open the existing close confirmation; the effect stays behind approval and system_control guards."""
    clean = str(name).strip()
    if not clean or len(clean) > _CLOSE_NAME_MAX or "\x00" in clean:
        return None
    runtime._session().pending_confirm = {'action': 'close_app', 'name': clean}
    return (f"{clean} uygulamasını kapatmak kaydedilmemiş çalışmayı kaybettirebilir. "
            "Kapatmamı onaylıyor musun? Evet ya da hayır de.")


def open_app(runtime, name):
    result = runtime.system_control.open_application(name)
    choices = getattr(result, 'candidates', ())
    runtime._session().pending_app = {'choices': choices, 'at': time.monotonic()} if choices else None
    return result


def continue_app(runtime, command):
    session = runtime._session()
    pending = session.pending_app
    if not pending:
        return None
    if time.monotonic() - pending['at'] > 120:
        session.pending_app = None
        return None
    text = command.casefold().strip(' .!?')
    if text in {'iptal', 'vazgeç', 'boşver'}:
        session.pending_app = None
        return 'Uygulama seçimini iptal ettim.'
    match = re.fullmatch(r'(\d+)(?:\s*(?:numara|numarayı|olanı|aç))?', text)
    chosen = None
    if match and 1 <= int(match[1]) <= len(pending['choices']):
        chosen = pending['choices'][int(match[1])-1]
    else:
        matches = [name for name in pending['choices'] if name.casefold() == text]
        if len(matches) == 1:
            chosen = matches[0]
    if chosen:
        session.pending_app = None
        return open_app(runtime, chosen)
    if match:
        return 'Listeden geçerli bir numara veya uygulamanın adını söyle.'
    # A different request must never accidentally approve a previous choice.
    session.pending_app = None
    return None
