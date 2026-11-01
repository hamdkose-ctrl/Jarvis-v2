"""Early command orchestration with explicit user/session dependencies."""
from dataclasses import dataclass
from typing import Callable
import re


@dataclass(frozen=True)
class CommandContext:
    profile: object
    session: object
    emit: Callable
    table_chat: Callable
    history_read: Callable
    study_intent: Callable
    conversation_summary: Callable
    pc_owner: Callable | None = None
    source: str = 'yazı'


PENDING_INPUT_FIELDS = ('pending_action', 'pending_weather_location', 'pending_confirm', 'pending_msg',
                        'pending_organize', 'pending_level', 'pending_voice', 'pending_event_title',
                        'pending_app', 'pending_request', 'pending_desktop', 'pending_visual')


def awaiting_input(session):
    return any(getattr(session, name) is not None and getattr(session, name) is not False
               for name in PENDING_INPUT_FIELDS)


def dispatch(context, command, normalized):
    """Return None to let existing legacy handlers continue; preserve priority.

    Erken kapıların sınıflandırması (PR10c kesiti F). Hiçbiri anlam üreten ikinci
    bir Brain değildir; hepsi ya exact bir kalıbın ardındadır ya da açıkça kurulmuş
    bir oturum durumunun devamıdır:
      - visual_chat: görsel türünün kendi kalıp listesi (DOMAIN_OWNED_PROTOCOL).
      - 'pc görevi/onayla/izin..': sabit önek (DETERMINISTIC_FAST_GATE).
      - 'görev akışı …:': sabit önek; sözdizimi bozuksa sohbet yerine hata döner.
      - pending_action: oturumda bekleyen onayın devamı, sahiplik + süre çitiyle.
      - usage_meter / smart_router / system_doctor: tam cümle listesi (exact).
      - task_agents: 'görev …' / 'kuyruk …' / 'hesap …' tam kalıpları; gerisinde None.
      - pc_guide / developer: kullanıcının açtığı rehberlik/geliştirme oturumunun
        devamı; kapanış ve kaçış kalıpları listede, oturum yoksa None.
      - desktop_agent: 'pc görevi/pc onayla' veya izin kalıbı; değilse None.
      - tablo: brain_gates.table_request — tek exact tanıyıcı, cümlenin tamamı istek olmalı.
      - konuşma özeti: brain_gates.conversation_summary_request — aynı şekilde tek exact
        tanıyıcı; hedef dosya değil bu oturumun sohbet tarihidir, yürütücü engine_output'tır.
      - 'tamam/ok/teşekkürler': bekleyen onay yokken geçen kısa karşılık.
      - study_intent: Hoca domain'inin kendi kapısı (hoca.handle).
    """
    from modules import app_actions, brain_gates
    owner, session = context.profile.slug, context.session
    from modules import visual_chat
    visual_result = visual_chat.handle(context, command, normalized)
    if visual_result is not None:
        return visual_result
    # Explicit desktop commands must not be interpreted as invented app actions.
    if re.match(r'^pc\s+(?:görev(?:i)?(?=[:\s])|onayla\s|iz(?:in|ni|inleri|inler)\b)', command.strip(), re.I):
        from modules import desktop_agent
        result = desktop_agent.handle(owner, command, context.emit, current=context.pc_owner, source=context.source)
        if result is not None:
            session.pending_desktop = True if desktop_agent.awaiting(owner) else None
            session.speech_override = desktop_agent.spoken(owner)
            return result
    # A new explicit workflow is not an answer to an older application choice.
    # Invalid workflow syntax must stop here instead of becoming a chat/app request.
    if re.match(r'^görev\s+akışı(?:\s|:|$)', normalized.strip()):
        from modules import task_agents
        result = task_agents.handle(owner, command, context.emit, summary=True)
        if result is None:
            raise ValueError('Kullanım: görev akışı kod: isteğin (veya rapor, mail, video).')
        session.speech_override = 'Görev sonucu sohbet ekranında hazır.'
        return result
    if session.pending_action is not None:
        result = app_actions.continue_voice(command, session, context.profile, context.emit)
        if result is not None: return result
    from modules import usage_meter
    result = usage_meter.handle(owner, command)
    if result is not None: return result
    from modules import smart_router
    result = smart_router.handle(owner, command)
    if result is not None: return result
    from modules import system_doctor
    result = system_doctor.handle(owner, command)
    if result is not None: return result
    from modules import task_agents
    result = task_agents.handle(owner, command, context.emit, summary=True)
    if result is not None:
        session.speech_override = 'Görev sonucu sohbet ekranında hazır.'
        return result
    from modules import pc_guide
    result = pc_guide.handle(context.profile, command)
    if result is not None:
        return result
    from modules import developer
    result = developer.handle(owner, command, context.emit)
    if result is not None:
        session.speech_override = 'Geliştirme sonucu sohbet ekranında hazır.'
        return result
    from modules import desktop_agent
    desktop_command = 'PC görevi devam' if session.pending_desktop and normalized.strip(' .!?') in ('devam', 'devam et', 'kaldığın yerden devam et') else command
    if desktop_command == command and session.pending_desktop:
        desktop_command = desktop_agent.consent_reply(owner, normalized) or command
    result = desktop_agent.handle(owner, desktop_command, context.emit, current=context.pc_owner, source=context.source)
    if result is not None:
        session.pending_desktop = True if desktop_agent.awaiting(owner) else None
        session.speech_override = desktop_agent.spoken(owner)
        return result
    if brain_gates.conversation_summary_request(normalized):
        return context.conversation_summary()
    if brain_gates.table_request(normalized):
        return context.table_chat()
    if normalized.strip(' .!') in ('tamam', 'ok', 'teşekkürler', 'tesekkurler') and not awaiting_input(session):
        return 'Tamam.'
    result = context.study_intent(normalized)
    return result if result else None


def engine_control(normalized, *, source, sleeping, close, set_sleep):
    """Explicit engine controls bypass conversational guides and model routing."""
    normalized = normalized.replace('’', "'")
    self_close = re.fullmatch(
        r"\s*(?:(?:hey\s+)?jarvis(?:'i|i)?|kendini|uygulamayı|uygulamayi)\s+"
        r"(?:kapat|kapan|çık|cik|sonlandır|sonlandir)\w*\s*[.!?]*", normalized)
    if self_close and not re.search(r"\b(?:bilgisayar|pc|windows|sistem)\b", normalized):
        if source == 'telefon':
            return 'Jarvis’i kapatma işlemini bilgisayarından yapabilirsin.'
        return close()
    if re.fullmatch(r"\s*(?:uyu|uyku moduna geç|uyku modu|hazırda bekle|beklemeye geç|bekleme moduna geç)\w*[\s.!]*", normalized):
        return set_sleep(True, announce=False)
    if sleeping and re.fullmatch(r"\s*(?:uyan|kalk|uyku modundan çık)\w*[\s.!]*", normalized):
        return set_sleep(False, announce=False)
    return None
