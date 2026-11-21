"""engine commands; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib


def handle_request(runtime, command: str) -> str:
    """Public entry: bu turn'ün tek pipeline geçişi; aynı request'te ikinci bir geçiş çalışmaz.

    Yazım düzeltme yeniden deneme veya ikinci doğal dil sınıflandırıcısı değildir.
    Düzeltilmiş görünüm yalnız `command_manager.exact_admin_view` kapalı admin
    protokolüne sunulur; serbest dilin tek kararı Brain modelinden gelir."""
    return handle(runtime, command)


def _typed_location_answer(text: str) -> bool:
    """Kısa ve tek başına bir şehir cevabı mı? Kapalı sözcük kümeleriyle, model olmadan."""
    from modules.brain_understanding import _looks_like_location_answer
    return bool(text) and bool(_looks_like_location_answer(text))


def _canonical_tail(runtime, command: str, cmd_lower: str):
    """Bu turn'ün tek kanonical rota kararı ve tek yürütmesi.

    Cümle burada yeniden sınıflandırılmaz: `route_command` yalnız bu turn'ün Understanding'ini
    okur, etki ise seçilen intent'in kendi sahibinde (`engine_intents.dispatch`) yürür. Ham
    cephe(ler) bittiğinde de, bir açıklama turu hiç cepheye inmeden de aynı tek yol çalışır."""
    from modules import brain_entry
    try:
        r = brain_entry.route_command(runtime, command)
    except Exception:
        runtime._record_failure('main.py:handle')
        raise
    intent = str(r.get("intent") or "chat")
    a = r.get("args")
    if not isinstance(a, dict):
        a = {}
    runtime.profile.log_command(intent)
    from modules.engine_intents import dispatch
    return dispatch(runtime, intent, a, command, cmd_lower)


def handle(runtime, command: str):

    from modules import requests_state
    requests_state.check()
    command = command.strip()
    cmd_lower = runtime._tr_lower(command)

    # Her komutta LLM bağlamını o anki aktif masaüstü profiliyle eşitle.
    # Web ayarları / telefon / geçici kullanıcı işlemleri istek bağlamını değiştirmiş olabilir.
    runtime._llm.set_user_context(runtime.profile.slug)

    from modules.command_manager import CommandContext, dispatch, engine_control, exact_admin_view
    from modules.confirmation import decision
    session = runtime._session()
    session.speech_override = None  # Only this command may choose its short spoken response.
    control_result = engine_control(cmd_lower, source=runtime._cur_source, sleeping=runtime.flags.get('sleep'),
                                    close=runtime._close_jarvis, set_sleep=runtime.set_sleep)
    if control_result is not None:
        return control_result
    from modules import brain_entry
    if brain_entry.matched_protocol("job.empty_cancel"):
        from modules import job_front
        # Preserve the old exact no-op message, but recheck active Goal/Job
        # status at execution time. Never let an unrelated model invent an
        # operation just because the user said "iptal".
        empty = job_front.route(
            runtime.profile.slug, lambda *a, **k: runtime.emit(*a, **k),
            cmd_lower, session, bounded=True,
            photo_pending=bool(getattr(runtime, "_pending_photo", {}).get(runtime.profile.slug)))
        return empty if empty is not None else (
            "İptal edilecek tek bir açık işlem doğrulayamadım; hiçbir şeyi iptal etmedim.")
    # Açık clarification'ın iptali canonical kapıda seçildiyse sahibi bu turdur; Goal/Job
    # çıplak "iptal"i ikinci kez yorumlayamaz.
    if brain_entry.matched_protocol("session.pending_action.clarify_cancel"):
        runtime._session().pending_action = None
        return "Tamam, işlemi iptal ettim."
    # State owns bare resume/cancel; a raw "hedef" or "görev" prefix can
    # never create a GoalState or authorize a worker on a free-language turn.
    from modules import goal_executor, job_front
    if brain_entry.matched_protocol('goal.closed_resume'):
        return goal_executor.closed_resume_status(
            runtime.profile.slug, brain_entry.protocol_selection('goal.closed_resume'))
    if brain_entry.matched_protocol("job.resume", "job.cancel"):
        outcome = job_front.route(
            runtime.profile.slug,
            lambda *a, **k: runtime.emit(*a, **k),
            cmd_lower, session,
            photo_pending=bool(getattr(runtime, "_pending_photo", {}).get(runtime.profile.slug)),
            bounded=True,
        )
        if outcome is not None:
            return outcome
    if brain_entry.matched_protocol("goal.resume", "goal.cancel", "goal.approval"):
        outcome = goal_executor.handle(runtime, command)
        if outcome is not None:
            return outcome
    # Exact Core-issued, owner/job-bound effect consent protocol. This is NOT
    # another natural-language classifier or a model-issued permission: the
    # displayed 64-hex control key is rechecked against current durable state
    # by canonical_goal_control; the foreground sends nothing.
    import re
    exact_effect_consent = re.fullmatch(
        r'hedef\s+onayla\s+([a-f0-9]{16})\s+([a-f0-9]{64})',
        command, re.IGNORECASE,
    )
    if (exact_effect_consent is not None
            and goal_executor.canonical_scheduler_owned(
                runtime.profile.slug, exact_effect_consent.group(1).lower(),
            )):
        return goal_executor.handle(runtime, command)

    # Kanonical açıklama turu (Understanding'ın tek EXPLANATION hükmü): cümle bilgi ister, yürütülecek
    # iş değildir. Buradan sonrası ham cümleyi yeniden sınıflandıran cephelerdir — erken dispatch
    # kolları bile bir soruyu kendi akışına çekebilir (ölçüldü: "infografik nedir?" görsel taslağı
    # başlattı, "görev akışı nedir?" kullanım hatası verdi) ve admin/efekt cepheleri bir soru için
    # gerçek iş yapar (yayın, güncelleme kurma, arıza taraması, not silme, ekran OCR'ı). Tur kendi tek
    # kanonical rotasına döner; icra yetkisi olan cümleler burada fence edilmez.
    if brain_entry.explanation_turn():
        return _canonical_tail(runtime, command, cmd_lower)
    context = CommandContext(profile=runtime.profile, session=session, emit=runtime.emit,
        table_chat=runtime._table_chat, history_read=runtime.history.read,
        conversation_summary=runtime._conversation_summary,
        pc_owner=lambda: runtime.pc_profile().slug, source=runtime._cur_source,
        record_failure=runtime._record_failure, output=runtime.output)
    early_result = dispatch(context, command, cmd_lower)
    if early_result is not None:
        return early_result
    from modules.command_execution import continue_app
    if not session.pending_action and not session.pending_confirm:
        # Açık uygulama seçimi yalnız canonical sahibi o turn'de ham metni tüketir.
        if brain_entry.pending_answer_owned("pending_app"):
            selected = continue_app(runtime, command)
            if selected is not None:
                return selected

    # Telefondan fotoğraf geldi ve "ne yapayım?" diye soruldu: işlem kararı canonical Brain/Core'da.
    ph = runtime._pending_photo.get(runtime.profile.slug)
    if ph and not runtime._session()._in_multi:
        from modules import brain_entry
        if runtime.time.time() - ph["t"] > brain_entry.PENDING_PHOTO_TTL:
            runtime._pending_photo.pop(runtime.profile.slug, None)
        elif brain_entry.matched_protocol("phone_photo.cancel"):
            runtime._pending_photo.pop(runtime.profile.slug, None)
            return "Tamam, fotoğrafla bir şey yapmıyorum."
        else:
            entry = brain_entry.current()
            if brain_entry.photo_followup_owned(entry):
                # Devam isteği Core planıyla yürütülür; bu yüzey ham metinden fotoğraf işlemi seçmez.
                pass
            elif brain_entry.relation_decided(entry):
                # Brain cevabı fotoğrafa bağlamadı: pending düşer, normal akış devam eder.
                runtime._pending_photo.pop(runtime.profile.slug, None)
            # Canonical karar eksik/belirsizse pending fotoğraf korunur; kullanıcının
            # cevabı sessizce düşmez, Core'un clarify/normal yanıtı akışa devam eder.

    # Klasör düzenleme onayı
    if runtime._session().pending_organize is not None:
        if brain_entry.pending_answer_owned("pending_organize"):
            job, runtime._session().pending_organize = runtime._session().pending_organize, None
            approval = decision(cmd_lower, extra=('düzenle', 'duzenle', 'evet düzenle', 'evet duzenle'))
            if approval is True:
                # Uygulamadan hemen önce tazelik: önizlenen plan ile güncel plan birebir aynı çiftleri
                # taşıyorsa yürür. Klasör araya dosya eklediyse ya da bir kaynak silindiyse ESKİ planla
                # taşıma yapılmaz — kullanıcıya taze önizleme yeniden sorulur.
                from modules import engine_intents
                current = runtime.files.plan_organize(job["folder"])
                fresh = runtime.files.plan_stamp(current)
                # Yol çiftleri birebir dursa bile önizlemedeki dosya kimliği değişmiş olabilir
                # (aynı yola başka dosya / yeni içerik): mühür farklıysa ESKİ onay yürümez.
                if not runtime.files.same_plan(job["plan"], current) or job.get("stamp") != fresh:
                    if not current:
                        runtime._session().pending_organize = None
                        return f"{job['label']} klasöründe düzenlenecek dosya yok."
                    runtime._session().pending_organize = dict(job, plan=current, stamp=fresh)
                    return engine_intents.organize_preview_question(job["label"], current)
                moved = runtime.files.apply_organize(
                    job["plan"], runtime.profile.slug, expected_stamp=job.get("stamp"),
                )
                runtime.privacy.audit("klasör düzenleme", f"{job['label']}: {moved} dosya")
                return f"{job['label']} klasöründe {moved} dosyayı düzenledim. Beğenmezsen “düzenlemeyi geri al” de."
            if approval is False:
                return "Tamam, dosyalara dokunmadım."

    # WhatsApp mesajı: eksik bilgi sorulur, göndermeden önce onay alınır
    if runtime._session().pending_msg is not None:
        # Açık mesaj alanı yalnız canonical olarak kendi cevabı olan turu tüketir; bağımsız yeni
        # istek (NEW_REQUEST/CHAT/kontrol) ham metni mesaj gövdesine yazmaz, alan korunur.
        if brain_entry.pending_answer_owned("pending_msg"):
            reply = runtime._message_step(command, cmd_lower)
            if reply is not None:
                return reply
    # An open reminder-title question is a bounded State continuation, not
    # authority for a raw planner to scan every user utterance.
    if session.pending_event_title is not None and brain_entry.pending_answer_owned("pending_event_title"):
        from modules.main_planner import continue_pending_event_title
        event_reply = continue_pending_event_title(runtime, command, cmd_lower)
        if event_reply is not None:
            return event_reply

    # Yeni WhatsApp mesajı ve rehber cümleleri artık ham cümleden seçilmez: Understanding
    # `message.send`/`contacts.manage` önerir, Core biçimi doğrular, etki `engine_intents`
    # sahibinde yürür. Buradaki dal yalnız açık `pending_msg` oturumunun devamını tüketir.

    # Learning semantics are model-proposed and Core-validated; exact pending
    # selections are handled by the canonical State Gate, never raw text here.

    # Dosyalar ekranındaki düğmeler: '"C:\...\x.pdf" dosyasını özetle' -> yapay zekâya sormadan doğrudan o dosyada
    file_reply = runtime._file_command(command)
    if file_reply is not None:
        return file_reply

    # Mikrofon açma/kapama ve uyandırma kurulumu artık yalnız Fast Gate (`fast.mic.toggle`)
    # ve Core `voice.wake.enable` intent'i üzerinden yürür; burada ham cümle kalıbı yoktur.

    # Windows Settings and Jarvis self-control are Core-validated typed proposals.
    # The old natural-language owners must not reinterpret the same utterance.

    # Onay bekleyen işlem (örn. bilgisayarı kapatma)
    if runtime._session().pending_confirm:
        if brain_entry.pending_answer_owned("pending_confirm"):
            action, runtime._session().pending_confirm = runtime._session().pending_confirm, None
            approval = decision(cmd_lower)
            if approval is True:
                if action == "shutdown":
                    if runtime.system_control.shutdown_pc() is False:
                        return 'Bilgisayarı kapatma komutu kabul edilmedi; kapatma zamanlandı demiyorum.'
                    runtime.privacy.audit("bilgisayarı kapatma", "60 sn zamanlandı")
                    return "Bilgisayarı 60 saniye içinde kapatmak üzere zamanladım. İptal için kapatmayı iptal et de."
                if isinstance(action, dict) and action.get('action') == 'notes_clear':
                    from modules import main_planner
                    return main_planner.clear_notes_confirmed(runtime, action)
                if isinstance(action, dict) and action.get('action') == 'tasks_clear_done':
                    from modules import tasks
                    return tasks.clear_done_confirmed(runtime.profile, action)
                if isinstance(action, dict) and action.get('action') == 'reminder_modify':
                    from modules import main_planner
                    return main_planner.modify_reminder_confirmed(runtime, action)
                if isinstance(action, dict) and action.get('action') == 'reminder_delete':
                    # Bounded canonical pending_confirm response only. It cannot
                    # target a different owner or a changed event since preview.
                    from modules import main_planner
                    return main_planner.delete_reminder_confirmed(runtime, action)
                if isinstance(action, dict) and action.get('action') == 'close_app':
                    name = str(action.get('name') or '').strip()
                    if name:
                        return (runtime.system_control.close_application(name)
                                or f"'{name}' adında açık bir uygulama bulamadım.")
            if approval is False:
                return "Tamam, vazgeçtim."
            # Başka bir komut geldi: onay iptal edildi, normal akışa devam et.

    # "70 yap" sorusunun cevabı (ses mi parlaklık mı?) artık yalnız State Gate'in
    # `session.pending_level.select` protokolünden Core `level_set` intent'ine gider.

    # Jarvis az önce şehir sorduysa bu mesaj şehir cevabıdır.
    if runtime._session().pending_weather_location:
        # Şehir sorusu yalnız semantik olarak cevap verilen turu tüketir; yeni istek şehir sanılmaz.
        # Kanonik sahip seçimi birincil; ancak sağlayıcı yokken/asılı kaldığında (canlı kanıt
        # 21 Kasım 09:48: ResponseValidationError -> ProviderExhausted) tur tümüyle düşüyordu.
        # Bu slot zaten kapalı sözlüklü bir sınıflandırıcıyla ayrılıyor: kısa şehir cevabı
        # ("istanbul") konumdur, "merhaba"/"hava nasıl"/"evet" değildir. Etki tek sahibinde:
        # Core `weather` intent'i; burada yalnız okuma yapan bir niyet tetiklenir.
        if (brain_entry.pending_answer_owned("pending_weather_location")
                or _typed_location_answer(command)):
            if brain_entry.matched_protocol("session.pending_weather_location.cancel") \
                    or cmd_lower in ("iptal", "vazgeç", "boşver"):
                runtime._session().pending_weather_location = False
                return "Hava durumu aramasını iptal ettim."
            if not command:
                return "Hangi şehir için hava durumuna bakayım?"
            runtime._session().pending_weather_location = False
            # Cevabın şehir olduğuna buradaki ham cümle karar vermez: owner seçimi canonical.
            # Etki tek sahibinden, Core `weather` intent'i üzerinden yürür.
            from modules.engine_intents import dispatch as core_dispatch
            return core_dispatch(runtime, "weather", {"location": command}, command, cmd_lower)

    # Free-language semantic ownership is exclusively the accepted Brain
    # proposal. There is no raw camera/share, note/calendar, fuzzy shortcut,
    # plugin or domain cascade reclassification here. The exact registered
    # shortcut and quoted UI file protocols are claimed at core_brain_adapter.handoff
    # before this legacy handler, with Core fences; they never reach this tail.

    # Kayıtlı şehir ("şehrim İzmir" / "şehrimi sıfırla") artık burada seçilmiyor: karar Understanding'in
    # `weather.city.set`/`weather.city.reset` önerisi, değer hükmü Core'un, tercih yazması tek intent
    # sahibinde (`engine_intents`). BRAIN-03 dilim 1, BRAIN-MIG-099.

    # Hava durumu isteğini artık yalnız Understanding yakalar (`weather.read` / `weather.read.current`);
    # buradaki ham `\bhava\b` kalıbı başka alan cümlelerini de seçiyordu.

    # Nesnesi söylenmemiş "aç/kapat" ve hedefi söylenmemiş sayı soruları artık Understanding'in
    # typed eksikleri (APP_TARGET_MISSING / level target unspecified) üzerinden yazılır; buradan
    # hiçbir netleştirme sorusu üretilmez.

    # Ses, parlaklık, kapatma, medya, ekran görüntüsü ve saat/tarih/sistem durumu okumaları artık
    # kendi sahiplerinde: Fast Gate (konuşma durdur, saat, tarih, sistem durumu), Understanding +
    # Core intent (pc.audio.action, pc.media.action, screen.capture, pc.shutdown.*) ve pc.level.set.
    # Bu yüzeyde ham cümleden seçilen tek bir etki kalmadı.

    # Fiyat/kur sorusu artık buradan seçilmez: Understanding `finance.read` önerir, Core
    # biçimi doğrular, veri finans domain'inde çekilir.

    # Uygulama açma/kapatma artık yalnız Understanding'in `<ad> aç/kapat` gramerinden ve
    # doğrulanmış Core `open_app` / `close_app` intent'lerinden yürür. Ham hedef burada seçilmez.

    # Exact admin receives ONLY the original request, never a typo-corrected
    # second semantic pass. General free-language decisions have already been
    # accepted (or refused) by the primary Brain model before this handler.
    view = exact_admin_view(
        context, cmd_lower, runtime.flags.get("speak"),
        original_text=command, runtime=runtime,
    )
    if view is not None:
        return view
    return _canonical_tail(runtime, command, cmd_lower)
