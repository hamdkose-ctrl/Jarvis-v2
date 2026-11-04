"""engine commands; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib


def handle_request(runtime, command: str) -> str:
    """Public entry: bu turn'ün tek pipeline geçişi; aynı request'te ikinci bir geçiş çalışmaz.

    Yazım düzeltme artık yeniden deneme değildir (§25 A, BRAIN-MIG-042): kanonical tur ham cümleyi
    bir kez yürütür, düzeltilmiş görünümün yetkisi iki kapalı setle sınırlıdır —
    `command_manager.exact_admin_view` (tam-cümle admin) ve `command_manager.typo_read_recovery` +
    `command_manager.typo_read_plan` (tam-cümle salt-okuma gramerleri; plan yürütme yetkisi seam'de,
    effect sahibi `engine_intents`tedir). Yazma, organize ve açma akışları düzeltilmiş metni görmez."""
    return handle(runtime, command)


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


def _read_plan_tail(runtime, plan, command: str, cmd_lower: str):
    """Yazım kurtarmasının tek salt-okuma planı: yürütme intent'in kendi sahibindedir.

    Seam buradan başka bir intent seçmez; `command_manager.typo_read_plan` kapalı salt-okuma
    setinden geçmiş doğrulanmış Core önerisini taşır. Kullanıcının yazdığı asıl cümle
    (`command`) provenance olarak sahibine geçer. `engine_intents.dispatch`in denetlenmiş tek
    üretim çağıranı bu yüzeydir (BRAIN-MIG-042)."""
    from modules.engine_intents import dispatch
    return dispatch(runtime, plan[0], plan[1], command, cmd_lower)


def handle(runtime, command: str):

    from modules import requests_state
    requests_state.check()
    command = command.strip()
    cmd_lower = runtime._tr_lower(command)

    # Her komutta LLM bağlamını o anki aktif masaüstü profiliyle eşitle.
    # Web ayarları / telefon / geçici kullanıcı işlemleri istek bağlamını değiştirmiş olabilir.
    runtime._llm.set_user_context(runtime.profile.slug)

    from modules.command_manager import (CommandContext, dispatch, engine_control, exact_admin_view,
                                         typo_read_plan, typo_read_recovery)
    from modules.confirmation import decision
    session = runtime._session()
    session.speech_override = None  # Only this command may choose its short spoken response.
    control_result = engine_control(cmd_lower, source=runtime._cur_source, sleeping=runtime.flags.get('sleep'),
                                    close=runtime._close_jarvis, set_sleep=runtime.set_sleep)
    if control_result is not None:
        return control_result
    from modules import brain_entry
    # Açık clarification'ın iptali canonical kapıda seçildiyse sahibi bu turdur; Goal/Job
    # çıplak "iptal"i ikinci kez yorumlayamaz.
    if brain_entry.matched_protocol("session.pending_action.clarify_cancel"):
        runtime._session().pending_action = None
        return "Tamam, işlemi iptal ettim."
    from modules import goal_executor, job_front
    if job_front.wants(cmd_lower):
        front_result = job_front.route(runtime.profile.slug, lambda *a, **k: runtime.emit(*a, **k), cmd_lower, session, photo_pending=bool(getattr(runtime, '_pending_photo', {}).get(runtime.profile.slug)))
        if front_result is not None:
            return front_result
    if not goal_executor.active() and (cmd_lower.startswith(('hedef:','görev:','görev yap:','hedef ')) or cmd_lower.strip(' .!?') in goal_executor.RESUME_COMMANDS or cmd_lower.strip(' .!?') in ('evet','onaylıyorum','onayla','iptal','vazgeç','boşver')):
        goal_result=goal_executor.handle(runtime,command)
        if goal_result is not None:return goal_result
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
        study_intent=lambda text: runtime._study_intent(text),
        conversation_summary=runtime._conversation_summary,
        pc_owner=lambda: runtime.pc_profile().slug, source=runtime._cur_source)
    early_result = dispatch(context, command, cmd_lower)
    if early_result is not None:
        return early_result
    if not goal_executor.active():
        goal_result=goal_executor.handle(runtime,command)
        if goal_result is not None:return goal_result
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

    # Çok adımlı komut: sıra semantiği kanonical Understanding'de doğar (`brain_entry.step_plan`);
    # bu yüzey cümleyi bölmez, yalnız bağlı turn'ün tipli planını okur ve typed adım adaptörüne verir.
    # Açık bir soru varken adım bölünmez: ilk adım o soruyu cevaplamış sayılamaz, kalan adımlar çalışmaz.
    # Bu tur açık alanın cevabı değilse ham cümle kısmi yürütülmez; kullanıcıya açıkça söylenir.
    if not runtime._session()._in_multi:
        steps = brain_entry.step_plan(command)
        if steps:
            blocked = [field for field in ("pending_msg", "pending_confirm", "pending_organize")
                       if getattr(runtime._session(), field) is not None]
            if not blocked:
                return runtime._run_steps(list(steps))
            if not any(brain_entry.pending_answer_owned(field) for field in blocked):
                return ("Açık bir mesaj/onay/düzenleme akışı varken çok adımlı komutu başlatmadım; "
                        "önce onu tamamla ya da iptal et, sonra adımları yeniden söyle.")

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
                moved = runtime.files.apply_organize(job["plan"], runtime.profile.slug)
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
    elif runtime.messaging.is_whatsapp_message(cmd_lower):
        fast = runtime.messaging.quick_parse(cmd_lower, runtime.profile.data.get("contacts", {}))   # kayıtlı kişi: LLM beklemeden
        to, text = fast if fast else runtime.messaging.extract(command, runtime.ask)
        runtime._session().pending_msg = {"to": to, "text": text, "stage": "to"}
        return runtime._message_step(None, "")
    contact_reply = runtime._contact_command(command, cmd_lower)
    if contact_reply is not None:
        return contact_reply

    # Öğrenme: kurallar, onay bekleyen bilgiler, gelişim raporu ("kural ekle: …", "öğrendiklerini kaydet")
    from modules import learning
    learn_reply = learning.handle(cmd_lower, command, runtime.profile)
    if learn_reply is not None:
        return learn_reply

    # Klasör izleme: "İndirilenler'i izle, PDF gelince önemli yerleri tablo yap", "izlenen klasörler", "izlemeyi durdur"
    from modules import watcher
    watch_reply = watcher.handle(runtime.profile.slug, command)
    if watch_reply is not None:
        return watch_reply

    # Dosyalar ekranındaki düğmeler: '"C:\...\x.pdf" dosyasını özetle' -> yapay zekâya sormadan doğrudan o dosyada
    file_reply = runtime._file_command(command)
    if file_reply is not None:
        return file_reply

    # Mikrofon açma/kapama ve uyandırma kurulumu artık yalnız Fast Gate (`fast.mic.toggle`)
    # ve Core `voice.wake.enable` intent'i üzerinden yürür; burada ham cümle kalıbı yoktur.

    # Jarvis'in kendi işlemleri: sayfa aç, güvenli ayarlar, yeniden başlat ("hafıza sayfasını aç", "cevap hızını sabırlı yap")
    windows_reply = runtime.system_control.windows_settings(cmd_lower)   # "wifi ayarlarını aç": Windows Ayarlar sayfası, Jarvis'in değil
    if windows_reply is not None:
        return windows_reply
    from modules import selfctl
    self_reply = selfctl.handle(cmd_lower, runtime.emit)
    if self_reply is not None:
        return self_reply

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
        if brain_entry.pending_answer_owned("pending_weather_location"):
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

    # ---- Hızlı yol: basit komutlar LLM'e gitmeden çalışır ----

    user_reply = runtime._user_command(command, cmd_lower)
    if user_reply is not None:
        return user_reply

    plan_reply = runtime._planner_command(command, cmd_lower)
    if plan_reply is not None:
        return plan_reply

    # Kısayollar (öğret / çalıştır / listele) ve ek komutlar: hepsi LLM'e gitmeden çalışır.
    # Sıra ve imza tek sahibindedir (`brain_precedence`); yüzey ikinci bir ham aday döngüsü taşımaz (§25 B).
    from modules import brain_precedence
    tail = brain_precedence.claim_tail(runtime, command, cmd_lower)
    if tail is not None:
        return tail[1]

    # Kayıtlı şehir: "şehrim İzmir" / "konumum Ankara" (hava durumu bu şehre göre bakar)
    m = runtime.re.match(r"^(?:şehrim|konumum|yaşadığım şehir)\s+(.+?)(?:['’]?(?:da|de|ta|te))?\s*(?:olsun|dır|dir)?$", cmd_lower)
    if m and len(m.group(1)) >= 3:
        city = m.group(1).title()
        runtime.profile.set_pref("city", city)
        return f"Şehrini {city} olarak kaydettim; hava durumuna bu şehre göre bakacağım."
    if runtime.re.search(r"(şehrimi|konumumu)\s+(sıfırla|sil|unut)", cmd_lower):
        runtime.profile.data["prefs"].pop("city", None)
        runtime.profile.save()
        return "Kayıtlı şehrini sildim; artık bulunduğun konuma göre bakacağım."

    # Hava durumu isteğini artık yalnız Understanding yakalar (`weather.read` / `weather.read.current`);
    # buradaki ham `\bhava\b` kalıbı başka alan cümlelerini de seçiyordu.

    # Son analizi dosyaya kaydet ("çıktı al", "kaydet"); yeni analiz/çeviri isteği değilse
    if runtime._session().last_doc is not None and runtime.re.search(r"\bçıktı\w*|\bkaydet\w*", cmd_lower) \
            and not runtime.re.search(r"analiz|özet|çevir|ekran|görüntü", cmd_lower):
        text, source, label = runtime._session().last_doc
        saved = runtime.output.save_text_result(text, source, label)
        return f"Çıktıyı kaydettim: {saved}" if saved else "Kaydetme iptal edildi."

    # Nesnesi söylenmemiş "aç/kapat" ve hedefi söylenmemiş sayı soruları artık Understanding'in
    # typed eksikleri (APP_TARGET_MISSING / level target unspecified) üzerinden yazılır; buradan
    # hiçbir netleştirme sorusu üretilmez.

    # Ses, parlaklık, kapatma, medya, ekran görüntüsü ve saat/tarih/sistem durumu okumaları artık
    # kendi sahiplerinde: Fast Gate (konuşma durdur, saat, tarih, sistem durumu), Understanding +
    # Core intent (pc.audio.action, pc.media.action, screen.capture, pc.shutdown.*) ve pc.level.set.
    # Bu yüzeyde ham cümleden seçilen tek bir etki kalmadı.

    # Döviz kuru ve çevirisi (modelsiz); kur sorusu değilse None döner ve akış devam eder
    from modules import finance
    rate_reply = finance.answer(command)
    if rate_reply is not None:
        return rate_reply

    # GitHub'a yayın: Ev/İş fark etmez; yalnız açık "git yükle / GitHub'a gönder" komutuyla.
    if runtime.re.search(r"(?:^|\b)(?:git|github'?a?)\s+(?:yükle|gönder|yayınla)\b|değişiklikleri\s+github'?a?\s+(?:yükle|gönder)", cmd_lower):
        try:
            import updater
            verified = updater.verify_sync()
            if verified.get("sync_state") in ("diverged", "unknown", "offline"):
                return "GitHub'a yüklemedim: " + str(verified.get("sync_msg") or "durum güvenli değil")
            from modules import git_publish as sc_publish
            return sc_publish.publish_worktree("kullanıcı 'git yükle' komutuyla yayınladı")
        except Exception as exc:
            runtime._record_failure('main.py:handle')
            return f"GitHub'a yükleyemedim: {exc}"

    # Güncelleme: "güncelleme var mı", "kendini güncelle"
    if runtime.re.search(r"güncelleme\w*\s+(?:var\s*mı|kontrol|bak)|kendini\s+güncelle|jarvis'?\w*\s+güncelle|güncellemeleri?\s+(?:al|yükle|kur)", cmd_lower):
        try:
            import updater
            wants_install = bool(runtime.re.search(r"kendini\s+güncelle|güncellemeleri?\s+(?:al|yükle|kur)|jarvis'?\w*\s+güncelle", cmd_lower))
            note = updater.install_latest() if wants_install else updater.check(apply_now=False, force=True)
            if note:
                return note + (" Jarvis'i kapatıp açınca devreye girer." if wants_install else " Kurmak için açıkça ‘güncellemeyi kur’ de.")
            st = updater.status()
            if st["error"] and not st["sha"]:
                return "Güncellemeye bakamadım: " + st["error"].split(" ", 2)[-1]
            return "Zaten en güncel sürümdesin." + (f" ({st['msg']})" if st["msg"] else "")
        except Exception as exc:
            runtime._record_failure('main.py:handle')
            return f"Güncellemeye bakamadım: {exc}"

    # Arıza tespiti: "sistemi kontrol et", "her şey yolunda mı", "neden çalışmıyor"
    if runtime.re.search(r"(?:sistem\w*|bağlantı\w*|jarvis\w*|kendin\w*)\s+(?:kontrol|tara|test)|arıza\w*|teşhis|"
                 r"her şey yolunda mı|sorun var mı|neden çalışmıyor|ne bozuk|sistem taraması", cmd_lower):
        from modules import diagnose
        return diagnose.summary(diagnose.run(speak_flag=runtime.flags.get("speak")))

    # Uygulama açma/kapatma artık yalnız Understanding'in `<ad> aç/kapat` gramerinden ve
    # doğrulanmış Core `open_app` / `close_app` intent'lerinden yürür. Ham hedef burada seçilmez.

    # ---- Yazım hatası: ikinci bir pipeline geçişi yok (§25 A, BRAIN-MIG-042) ----
    # Düzeltilmiş görünüm iki kapalı sete gösterilir: exact-admin tanıyıcıları ve salt-okuma
    # kurtarması. Ham cümle bu turn'de tüm kolları geçtiği için o kolun efekti en çok bir kez
    # çalışır; yazma/organize/açma akışları düzeltilmiş metni hiçbir zaman görmez. Kurtarma hiçbir
    # intent'i burada seçmez: not listesinin doğrulanmış salt-okuma planı effect'in kendi sahibine
    # (`engine_intents`) buradan gider. Yapay zekaya her zaman kullanıcının yazdığı asıl cümle gider
    # ("yarış merhaba" -> "yarın merhaba" bozulması olmaz).
    corrected = runtime.typo.fix(cmd_lower)
    view = exact_admin_view(context, corrected, runtime.flags.get("speak"))
    if view is not None:
        return view
    if corrected != cmd_lower:
        recovered = typo_read_recovery(context, runtime, corrected)
        if recovered is not None:
            return recovered
        plan = typo_read_plan(corrected)
        if plan is not None:
            return _read_plan_tail(runtime, plan, command, cmd_lower)

    # ---- Karmaşık istekler: bu turn'ün canonical Brain kararı ----
    # Sınıflandırma ve cevap sıralıdır; kullanılmayacak cevap için ek kota harcanmaz.
    return _canonical_tail(runtime, command, cmd_lower)
