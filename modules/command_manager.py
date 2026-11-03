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
                        'pending_app', 'pending_desktop', 'pending_visual')


def awaiting_input(session):
    return any(getattr(session, name) is not None and getattr(session, name) is not False
               for name in PENDING_INPUT_FIELDS)


def dispatch(context, command, normalized):
    """Return None to let existing legacy handlers continue; preserve priority.

    PR3B bölüm 3 denetimi (her kol sınıflandırıldı; topluca silinmedi). Bu kollar anlam üreten
    ikinci bir Brain değildir; hiçbiri kanonical State/Fast/Understanding kararından sonra cümleden
    *genel* domain seçmez. Sınıflar: B = exact admin/FAST grameri, A = bounded durum devamı,
    C = domain'in kendi yürütme kapısı. Ölçülen tek gerçek yetki hatası sıraydı: sabit-olmayan
    görsel anahtar taraması açık admin öneklerini gölgelemesi (kilidi
    `tests/test_brain_pr3b_legacy_front_door_authority.py::DispatchArmPrecedenceTests`).
      - 'pc görevi/onayla/izin..' (B): sabit önek; yürütme `desktop_agent`'ındır, önek yalnız
        sahiplik kapısıdır. Bu kol yüzeyde konum yetkisi taşır: aktif rehberlik oturumu
        (`pc_guide`) çıplak `pc görevi:` cümlesini yutmadan önce masaüstü sahibi seçilmeli.
        Kanonical-öncesi yakalama BRAIN-MIG-088 gereği PR3C'de emekli olur (Core masaüstü önerisi yok).
      - 'görev akışı …:' (B): sabit önek; sözdizimi bozuksa sohbet yerine kullanım hatası döner.
      - pending_action (A): oturumda bekleyen onayın devamı, `pending_answer_owned` + süre çitiyle.
      - usage_meter / smart_router / system_doctor (B): tam cümle kümesi üyeliği; cümlenin içinde
        aramaz, uzun cümleyi reddeder (negatif kilitler `ExactAdminArmScopeTests`).
      - task_agents (B/C): 'görev akışı/akışları', 'görev kuyruğu', 'hesap durumu' gibi tam kalıplar;
        general NL girişi BRAIN-MIG-070 gereği PR3C envanterinde.
      - pc_guide (A/B): kullanıcının açtığı rehberlik oturumunun devamı; kapanış/kaçış kalıpları
        listede, oturum yoksa yalnız açık `pc yardımı:` öneki ve `adım adım yardım et` kalıbı.
        Migration map'te `pc_guide` satırı yoktur; geniş NL girişi PR3C envanterine yazıldı.
      - developer (A/B/C): geliştirme modu kapalıyken ilk satırda None; açıkken exact draft/test/
        apply kalıpları (BRAIN-MIG-087), genel oturum devamı BRAIN-MIG-085 sözleşme kararı bekler.
      - desktop_agent (A/B): 'pc görevi/pc onayla' veya izin kalıbı; değilse None.
      - tablo (B): brain_gates.table_request — tek exact tanıyıcı, cümlenin tamamı istek olmalı.
      - konuşma özeti (B): brain_gates.conversation_summary_request — aynı şekilde tek exact
        tanıyıcı; hedef dosya değil bu oturumun sohbet tarihidir, yürütücü engine_output'tır.
        Kanonical Fast Gate aynı tanıyıcıyı plan olarak seçtiğinde bu kol hiç çalışmaz.
      - 'tamam/ok/teşekkürler' (B): bekleyen onay yokken geçen kısa karşılık; model çağırmaz.
      - study_intent (C): Hoca domain'inin kendi kapısı (`hoca.handle` tam cümle önekleri + aktif
        ders devamı); hoca modunun olmadığı her cümlede None.
      - visual_chat (C, henüz kanonical sahibi yok): görsel türünün kendi kalıp listesi; tür
        cümlenin *içinde* aranır, bu yüzden admin öneklerinden sonra gelir. BRAIN-MIG-063
        görsel türü önerisini Understanding'e taşır; kanonical `capability_hint` gelene kadar bu
        kol domain-owned kalır (PR3C).
    """
    from modules import app_actions, brain_entry, brain_gates
    owner, session = context.profile.slug, context.session
    from modules import visual_chat
    # Açık admin önekleri (B — KEEP_EXACT_ADMIN) geniş anahtar taramasından ÖNCE sahiplerine gider.
    # `visual_chat` görsel türünü cümlenin *içinde* arar; sırası eski olduğu sürece "pc görevi:
    # infografik çiz" masaüstü görevi ve "görev akışı rapor: infografik tasarla" görev akışı görsel
    # taslağa düşüyordu (ölçüldü). Bir alanın geniş NL taraması explicit admin önekini gölgeleyemez.
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
    visual_result = visual_chat.handle(context, command, normalized)
    if visual_result is not None:
        return visual_result
    if session.pending_action is not None:
        # Açık onay/netleştirme yalnız canonical olarak kendi cevabı olan turu tüketir.
        if brain_entry.pending_answer_owned("pending_action"):
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
    # Başka bir bounded State/Fast protokolü canonical kapıda seçildiyse "evet/devam"
    # masaüstü iznine yeniden yorumlanmaz; canonical protokol tek sahiptir.
    desktop_command = command
    if brain_entry.pending_answer_owned("pending_desktop"):
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
