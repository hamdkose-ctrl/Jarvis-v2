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
    record_failure: Callable | None = None
    output: object | None = None


def _record_failure(context, location):
    callback = context.record_failure
    if callback is not None:
        callback(location)
        return
    from modules import diagnostics
    diagnostics.record_failure(location)


PENDING_INPUT_FIELDS = ('pending_action', 'pending_weather_location', 'pending_confirm', 'pending_msg',
                        'pending_organize', 'pending_level', 'pending_voice', 'pending_event_title',
                        'pending_app', 'pending_desktop', 'pending_visual')

def awaiting_input(session):
    return any(getattr(session, name) is not None and getattr(session, name) is not False
               for name in PENDING_INPUT_FIELDS)


def dispatch(context, command, normalized):
    """Only exact admin and State-owned replies; never classify open language.

    The Brain model owns every free utterance. This adapter is strictly for
    explicit machine-addressed protocols, bounded Core pending replies, and
    exact administrative status/setting commands. It does not inspect every
    domain's natural-language handler in a cascade.
    """
    from modules import brain_entry, brain_precedence
    owner, session = context.profile.slug, context.session

    if brain_precedence.explicit_desktop_owner_protocol(command):
        from modules import desktop_agent
        result = desktop_agent.handle(
            owner, command, context.emit, current=context.pc_owner,
            source=context.source)
        if result is not None:
            session.pending_desktop = True if desktop_agent.awaiting(owner) else None
            session.speech_override = desktop_agent.spoken(owner)
            return result

    if brain_precedence.explicit_workflow_owner_protocol(normalized):
        from modules import task_agents
        result = task_agents.handle(owner, command, context.emit, summary=True)
        if result is None:
            return "Kullanım: görev akışı kod: isteğin (veya rapor, mail, video)."
        session.speech_override = "Görev sonucu sohbet ekranında hazır."
        return result

    if session.pending_action is not None and brain_entry.pending_answer_owned("pending_action"):
        from modules import app_actions
        result = app_actions.continue_voice(command, session, context.profile, context.emit)
        if result is not None:
            return result

    if getattr(session, "pending_visual", None) is not None and brain_entry.pending_answer_owned("pending_visual"):
        from modules import visual_chat
        result = visual_chat.handle(context, command, normalized)
        if result is not None:
            return result

    if getattr(session, "pending_desktop", None) and brain_entry.pending_answer_owned("pending_desktop"):
        from modules import desktop_agent
        followup = desktop_agent.consent_reply(owner, normalized) or command
        result = desktop_agent.handle(
            owner, followup, context.emit, current=context.pc_owner,
            source=context.source)
        if result is not None:
            session.pending_desktop = True if desktop_agent.awaiting(owner) else None
            session.speech_override = desktop_agent.spoken(owner)
            return result

    from modules import usage_meter, smart_router, system_doctor
    for admin in (usage_meter.handle, smart_router.handle, system_doctor.handle):
        result = admin(owner, command)
        if result is not None:
            return result
    return None


def exact_admin_view(context, corrected, speak_flag=None, *, original_text=None, runtime=None):
    """Yazım düzeltmesinin görebileceği ilk kapalı küme: tam-cümle exact admin tanıyıcıları (§25 A, BRAIN-MIG-042).

    İkinci bir pipeline geçişi değildir: kanonical tur ham cümleyi yürüttü ve hiçbir kol almadı.
    Altı salt-okuma admin tanıyıcısı kararını *cümlenin tamamı* üzerinde verir — tam cümle
    kümesi üyeliği veya `fullmatch`; düzeltilmiş görünüm yalnız bu bounded kolları görebilir.
    Git yayınlama ve updater install/check ise ayrı, salt ham özgün cümlede `fullmatch` yapan
    admin protokolleridir; typo düzeltmesi veya model önerisi onlara yetki veremez.
    Domain/akış kolları (görev, rehberlik, geliştirme, masaüstü, görsel, Hoca, ek komutlar)
    listeye giremez. Salt-okuma typo kurtarması `typo_read_recovery` ile biter.
    Kilidi `tests/test_brain_pr3b_legacy_front_door_authority.py`.
"""
    from modules import brain_gates, smart_router, system_doctor, usage_meter
    owner = context.profile.slug
    result = usage_meter.handle(owner, corrected)
    if result is not None:
        return result
    result = smart_router.handle(owner, corrected)
    if result is not None:
        return result
    result = system_doctor.handle(owner, corrected)
    if result is not None:
        return result
    # Existing exact Git/update protocols stay model-independent.  The effect itself
    # is implemented exactly once in engine_intents: no second admin executor here.
    if isinstance(original_text, str):
        from modules import git_publish
        import updater
        intent = ("git_publish" if git_publish.requested(original_text)
                  else "system_update" if updater.command_request(original_text) is not None
                  else None)
        if intent is not None:
            if runtime is None:
                return "Yönetici işlemi için yürütme bağlamı gerekli; işlem yapılmadı."
            from modules.engine_intents import dispatch
            return dispatch(runtime, intent, {}, original_text, original_text.casefold())
    if brain_gates.conversation_summary_request(corrected):
        return context.conversation_summary()
    if brain_gates.table_request(corrected):
        return context.table_chat()
    return None


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
