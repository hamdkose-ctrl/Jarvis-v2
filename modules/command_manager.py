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
        aramaz, uzun cümleyi reddeder (negatif kilitler `ExactAdminArmScopeTests`). Yazım düzeltilmiş
        görünümün görebileceği kapalı kümenin üyeleridir (`exact_admin_view`).
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
      - visual_chat (A): yalnız canonical olarak sahiplenilmiş pending source cevabı ve son görsel
        retry'ını tüketir. Yeni görsel türü seçimi BRAIN-MIG-063 / PR3C-6 ile Understanding
        visual.create → Core visual_create yoluna taşındı; bu adapter yeni cümleden tür seçmez.
    """
    from modules import app_actions, brain_entry, brain_gates, brain_precedence
    owner, session = context.profile.slug, context.session
    from modules import visual_chat
    # Açık admin önekleri (B — KEEP_EXACT_ADMIN) geniş anahtar taramasından ÖNCE sahiplerine gider.
    # visual_chat artık tür seçmez; yalnız Brain'in bağladığı pending source cevabını veya retry'ı
    # tüketir. Yine de explicit admin önceliği sabit kalır: bir alanın bounded devamı başka protokolü
    # gölgeleyemez.
    # Explicit desktop commands must not be interpreted as invented app actions.
    if brain_precedence.explicit_desktop_owner_protocol(command):
        from modules import desktop_agent
        result = desktop_agent.handle(owner, command, context.emit, current=context.pc_owner, source=context.source)
        if result is not None:
            session.pending_desktop = True if desktop_agent.awaiting(owner) else None
            session.speech_override = desktop_agent.spoken(owner)
            return result
    # A new explicit workflow is not an answer to an older application choice.
    # Invalid workflow syntax must stop here instead of becoming a chat/app request.
    from modules import brain_precedence
    if brain_precedence.explicit_workflow_owner_protocol(normalized):
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


def exact_admin_view(context, corrected, speak_flag=None):
    """Yazım düzeltmesinin görebileceği ilk kapalı küme: tam-cümle exact admin tanıyıcıları (§25 A, BRAIN-MIG-042).

    İkinci bir pipeline geçişi değildir: kanonical tur ham cümleyi yürüttü ve hiçbir kol almadı.
    Buradaki altı tanıyıcının tamamı kararını *cümlenin tamamı* üzerinde verir — tam cümle kümesi
    üyeliği veya sabit-olmayan `fullmatch` — ve ham cümle bu turn'de zaten reddedildiği için
    efekt en çok bir kez çalışır. Domain/akış kolları (görev, rehberlik, geliştirme, masaüstü,
    görsel, Hoca, ek komutlar) listeye giremez: düzeltilmiş bir görünüm onların akışının sahibi
    olamaz. Düzeltilmiş görünümün ikinci (ve son) yetkisi salt-okuma kurtarmasıdır:
    `typo_read_recovery`. Kilidi `tests/test_brain_pr3b_legacy_front_door_authority.py`."""
    from modules import brain_gates, diagnose, smart_router, system_doctor, usage_meter
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
    if diagnose.requested(corrected):
        # Tam-cümle arıza tespiti (`sistemi kontrol et`): teşhis salt-okunurdur, sahibi ve tek
        # yürütmesi `modules.diagnose`dır. Ham cümle bu turn'de düz-metin kapısını kendi yazımıyla
        # zaten geçemediği için tarama en çok bir kez koşar; domain akış kollarının aksine burada
        # bir akışın sahibi olmaz, yalnız kendi sorusunun cevabını üretir.
        return diagnose.summary(diagnose.run(speak_flag=speak_flag))
    if brain_gates.conversation_summary_request(corrected):
        return context.conversation_summary()
    if brain_gates.table_request(corrected):
        return context.table_chat()
    return None


_TYPO_READ_INTENTS = frozenset({'notes_read'})


def typo_read_plan(corrected):
    """Düzeltilmiş tam cümlenin doğrulanmış salt-okuma planı: Core önerisi veya None.

    Yürütme burada değildir: etki intent'in kendi sahibindedir ve planı seam'in kendisi
    `engine_intents.dispatch`e verir (`engine_commands`). `core_plan`ın döndürdüğü intent
    `_TYPO_READ_INTENTS` dışındaysa öneri reddedilir; yazma/organize/açma akışları bu kapalı
    setten geçemez. Kanonical aday/referans/model geçişi yeniden çalışmaz."""
    from modules import brain_core_map, brain_understanding
    view = brain_understanding.notes_read_view(corrected)
    if view is None:
        return None
    plan = brain_core_map.core_plan(*view)
    return plan if plan is not None and plan[0] in _TYPO_READ_INTENTS else None


def typo_read_recovery(context, runtime, corrected):
    """Yazım düzeltmesinin salt-okuma kurtarması (metin sahipleri): iki tam-cümle grameri, sıfır etki.

    Koşul (§25 A, BRAIN-MIG-042): bu turn'de kanonical State/Fast/Understanding, ham cepheler ve
    `exact_admin_view` ham cümleyi hiçbir kol almadan geçirdi. Burası ikinci bir pipeline değildir —
    candidates/references/model/State/Fast/Understanding yeniden çalışmaz, ham kapı düzeltilmiş metinle
    yeniden yürümez. Yalnız *düzeltilmiş tam cümle* salt-okuma gramerlerine sorulur ve cevap o gramerin
    kendi sahibinden yürür: `main_planner.agenda_read_request` + `runtime._agenda_text`,
    `tasks.list_request` + `tasks.list_text`. Not listesinin kanonical Core intent'i plan olarak
    `typo_read_plan`da durur; sahibi `engine_intents`tir. Tarayıcı açan alt biçim ve yazma/organize
    akışları bu sette değildir. Kilidi
    `tests/test_brain_pr3b_legacy_front_door_authority.py::TypoReadRecovery(Tests|GuardTests)`."""
    from modules import main_planner, tasks
    read = main_planner.agenda_read_request(corrected, runtime.datetime.now())
    if read is not None:
        return runtime._agenda_text(*read)
    if tasks.list_request(corrected):
        return tasks.list_text(context.profile)
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
