"""engine commands; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def handle(runtime, command: str) -> str:

    from modules import requests_state
    requests_state.check()
    command = command.strip()
    cmd_lower = runtime._tr_lower(command)

    # Her komutta LLM bağlamını o anki aktif masaüstü profiliyle eşitle.
    # Web ayarları / telefon / geçici kullanıcı işlemleri istek bağlamını değiştirmiş olabilir.
    runtime._llm.set_user_context(runtime.profile.slug)

    from modules import app_actions
    from modules.command_manager import CommandContext, dispatch, engine_control
    from modules.confirmation import decision
    session = runtime._session()
    session.speech_override = None  # Only this command may choose its short spoken response.
    control_result = engine_control(cmd_lower, source=runtime._cur_source, sleeping=runtime.flags.get('sleep'),
                                    close=runtime._close_jarvis, set_sleep=runtime.set_sleep)
    if control_result is not None:
        return control_result
    from modules import goal_executor
    if not goal_executor.active() and (cmd_lower.startswith(('hedef:','görev:','görev yap:','hedef ')) or cmd_lower.strip(' .!?') in goal_executor.RESUME_COMMANDS or cmd_lower.strip(' .!?') in ('evet','onaylıyorum','onayla','iptal','vazgeç','boşver')):
        goal_result=goal_executor.handle(runtime,command)
        if goal_result is not None:return goal_result
    context = CommandContext(profile=runtime.profile, session=session, emit=runtime.emit,
        table_chat=runtime._table_chat, history_read=runtime.history.read, translate=lambda text, target: runtime.tr.translate(text, target),
        study_intent=lambda text: runtime._study_intent(text),
        pc_owner=lambda: runtime.pc_profile().slug, source=runtime._cur_source)
    early_result = dispatch(context, command, cmd_lower)
    if early_result is not None:
        return early_result
    if not goal_executor.active():
        goal_result=goal_executor.handle(runtime,command)
        if goal_result is not None:return goal_result
    from modules.command_execution import continue_app
    if not session.pending_action and not session.pending_confirm:
        selected = continue_app(runtime, command)
        if selected is not None:
            return selected

    # Telefondan fotoğraf geldi ve "ne yapayım?" diye soruldu: bu cevap o fotoğraf için
    ph = runtime._pending_photo.get(runtime.profile.slug)
    if ph and not runtime._session()._in_multi:
        if runtime.time.time() - ph["t"] > 600:
            runtime._pending_photo.pop(runtime.profile.slug, None)
        elif runtime.re.fullmatch(r"(?:vazgeç|iptal|boşver|gerek yok|hiçbir şey|bir şey yapma)\w*", cmd_lower.strip(" .!?")):
            runtime._pending_photo.pop(runtime.profile.slug, None)
            return "Tamam, fotoğrafla bir şey yapmıyorum."
        elif runtime._PHOTO_INTENT.search(cmd_lower):
            runtime._pending_photo.pop(runtime.profile.slug, None)
            return runtime._photo_action(ph["path"], command)
        else:
            runtime._pending_photo.pop(runtime.profile.slug, None)     # başka bir konuya geçildi

    # Çok adımlı komut: "önce X sonra Y", "X ardından Y". Adımlar sırayla çalışır, yanıtlar birleştirilir.
    if not runtime._session()._in_multi and runtime._session().pending_msg is None and runtime._session().pending_confirm is None and runtime._session().pending_organize is None:
        steps = runtime._split_steps(command)
        if steps:
            return runtime._run_steps(steps)

    # Klasör düzenleme onayı
    if runtime._session().pending_organize is not None:
        job, runtime._session().pending_organize = runtime._session().pending_organize, None
        approval = decision(cmd_lower, extra=('düzenle', 'duzenle', 'evet düzenle', 'evet duzenle'))
        if approval is True:
            moved = runtime.files.apply_organize(job["plan"])
            runtime.privacy.audit("klasör düzenleme", f"{job['label']}: {moved} dosya")
            return f"{job['label']} klasöründe {moved} dosyayı düzenledim. Beğenmezsen “düzenlemeyi geri al” de."
        if approval is False:
            return "Tamam, dosyalara dokunmadım."

    # WhatsApp mesajı: eksik bilgi sorulur, göndermeden önce onay alınır
    if runtime._session().pending_msg is not None:
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

    mic_match = runtime.re.fullmatch(r"mikrofon(?:u|umu)?\s+(kapat|aç|ac)[ .!?]*", cmd_lower)
    if mic_match:
        return app_actions.voice({'action':'set_flag','params':{'name':'mic','value':mic_match.group(1)!='kapat'}}, runtime._session(), runtime.profile, runtime.emit, command)
    if runtime.re.fullmatch(r"(?:hey jarvis|jarvis) uyandırmasını aç[ .!?]*", cmd_lower):
        return app_actions.voice({'action':'settings_save','params':{'data':{'wake_word':'Jarvis','wake_aliases':['jarvis','hey jarvis','yarvis'],'wake_engine':'auto'}}}, runtime._session(), runtime.profile, runtime.emit, command)

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
        action, runtime._session().pending_confirm = runtime._session().pending_confirm, None
        approval = decision(cmd_lower)
        if approval is True:
            if action == "shutdown":
                if runtime.system_control.shutdown_pc() is False:
                    return 'Bilgisayarı kapatma komutu kabul edilmedi; kapatma zamanlandı demiyorum.'
                runtime.privacy.audit("bilgisayarı kapatma", "60 sn zamanlandı")
                return "Bilgisayarı 60 saniye içinde kapatmak üzere zamanladım. İptal için kapatmayı iptal et de."
        if approval is False:
            return "Tamam, vazgeçtim."
        # Başka bir komut geldi: onay iptal edildi, normal akışa devam et.

    # "70 yap" gibi hedefi söylenmemiş sayı sorulduysa cevap: ses ya da parlaklık
    if runtime._session().pending_level is not None:
        level, runtime._session().pending_level = runtime._session().pending_level, None
        if runtime.re.search(r"\bses\w*", cmd_lower):
            return f"Ses seviyesini yüzde {level} yaptım." if runtime.system_control.set_volume(level) \
                else "Ses seviyesini ayarlayamadım."
        if runtime.re.search(r"parlak\w*|ekran", cmd_lower):
            return f"Ekran parlaklığını yüzde {level} olarak ayarladım." if runtime.system_control.set_brightness(level) \
                else "Ekran parlaklığını ayarlayamadım."
        # başka bir komut geldi: soru iptal, normal akışa devam

    # Jarvis az önce şehir sorduysa bu mesaj şehir cevabıdır.
    if runtime._session().pending_weather_location:
        if cmd_lower in ("iptal", "vazgeç", "boşver"):
            runtime._session().pending_weather_location = False
            return "Hava durumu aramasını iptal ettim."
        if not command:
            return "Hangi şehir için hava durumuna bakayım?"
        runtime._session().pending_weather_location = False
        return runtime._weather(command)

    # ---- Hızlı yol: basit komutlar LLM'e gitmeden çalışır ----

    user_reply = runtime._user_command(command, cmd_lower)
    if user_reply is not None:
        return user_reply

    plan_reply = runtime._planner_command(command, cmd_lower)
    if plan_reply is not None:
        return plan_reply

    # Kısayollar (öğret / çalıştır / listele) ve ek komutlar: hepsi LLM'e gitmeden çalışır
    for handler, arguments in ((runtime._macro_teach, (command, cmd_lower)), (runtime._macro_manage, (cmd_lower,)),
                               (runtime._macro_run, (cmd_lower,)), (runtime._extra_commands, (command, cmd_lower))):
        reply = handler(*arguments)
        if reply is not None:
            return reply

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

    # Hava durumu: modele sormadan, şehir sormadan (konum otomatik)
    if runtime.re.search(r"\bhava(\s+durumu)?\b|yağmur yağacak mı|yağmur var mı", cmd_lower) \
            and not runtime.re.search(r"havalimanı|havaalanı|hava yolu|havai|hava kuvvet", cmd_lower):
        return runtime._weather(runtime._city_in(cmd_lower))

    # Son analizi dosyaya kaydet ("çıktı al", "kaydet"); yeni analiz/çeviri isteği değilse
    if runtime._session().last_doc is not None and runtime.re.search(r"\bçıktı\w*|\bkaydet\w*", cmd_lower) \
            and not runtime.re.search(r"analiz|özet|çevir|ekran|görüntü", cmd_lower):
        text, source, label = runtime._session().last_doc
        saved = runtime.output.save_text_result(text, source, label)
        return f"Çıktıyı kaydettim: {saved}" if saved else "Kaydetme iptal edildi."

    # Nesnesi söylenmemiş işlem ("kapat", "aç", "sil"): tahmin edip yanlış şeyi kapatma, sor
    verb = runtime.re.fullmatch(r"(?:lütfen\s+)?(kapat|kapa|kapatır mısın|kapatsana|aç|açar mısın|açsana|sil|siler misin|"
                                r"gönder|gönderir misin|başlat)", cmd_lower.strip(" .!?"))
    if verb:
        what = next(v for k, v in (("kap", "kapatmamı"), ("aç", "açmamı"), ("sil", "silmemi"), ("gön", "göndermemi"),
                                   ("baş", "başlatmamı")) if verb.group(1).startswith(k))
        question = f"Neyi {what} istiyorsun?"
        runtime._session().pending_request = {'command': command, 'question': question}
        return question

    # Hedefi söylenmemiş sayı ("70 yap"): modele sormadan hemen netleştir
    bare = runtime.re.fullmatch(r"(yüzde\s*)?(\d{1,3})\s*(yap|olsun|ayarla|yapar mısın|yapsana)?", cmd_lower.strip(" .!"))
    if bare:
        runtime._session().pending_level = min(int(bare.group(2)), 100)
        return f"Yüzde {runtime._session().pending_level}, ses mi parlaklık mı?"

    # Sessize alma / sessizden çıkarma: durum tersine çevrilmez ("sessize al" iki kez denince ses açılmaz)
    if runtime.re.search(r"sessiz(?:i|den)\s+(?:kaldır|çık|aç)\w*|sesi\s+geri\s+(?:aç|getir)\w*|sessiz\s*modu?nu?\s+kapat\w*", cmd_lower):
        if runtime.system_control.set_mute(False):
            lvl = runtime.system_control.current_volume()
            return "Sessizi kaldırdım." + (f" Ses yüzde {lvl}." if lvl is not None else "")
        return "Sesi açamadım."
    if runtime.re.search(r"sessize\s+al\w*|\bsesi\s+(?:tamamen\s+)?(?:kapat|kes|sustur)\w*|bilgisayarı\s+sustur\w*|sesi\s+sıfırla", cmd_lower) \
            and not runtime._numbers(cmd_lower):
        if runtime.system_control.is_muted():
            return "Ses zaten kapalı (sessizde)."
        return "Sesi kapattım, bilgisayar sessizde." if runtime.system_control.set_mute(True) else "Sesi kapatamadım."

    # Ses
    if runtime.re.search(r"\bses(i|ini)?\b", cmd_lower):
        nums = runtime._numbers(cmd_lower)
        if nums:
            level = min(nums[0], 100)
            if runtime.system_control.set_volume(level):
                return f"Ses seviyesini yüzde {level} yaptım."
            return "Ses seviyesini ayarlayamadım."
        if any(w in cmd_lower for w in ("kapat", "sessiz", "sıfır", "sustur")):
            if runtime.system_control.is_muted():
                return "Ses zaten kapalı (sessizde)."
            return "Sesi kapattım, bilgisayar sessizde." if runtime.system_control.set_mute(True) else "Sesi kapatamadım."
        if any(w in cmd_lower for w in ("aç", "yükselt", "arttır", "artır")):
            if runtime.system_control.is_muted() and "aç" in cmd_lower and not any(w in cmd_lower for w in ("yükselt", "arttır", "artır")):
                runtime.system_control.set_mute(False)            # sessizdeyken "sesi aç": önce sessizi kaldır, seviye aynı kalsın
                lvl = runtime.system_control.current_volume()
                return "Sessizi kaldırdım." + (f" Ses yüzde {lvl}." if lvl is not None else "")
            return runtime._volume_step(15, "arttırdım")
        if any(w in cmd_lower for w in ("kıs", "azalt", "düşür")):
            return runtime._volume_step(-10, "kıstım")

    # Ekran parlaklığı
    if "parlakl" in cmd_lower or "ekran ışığı" in cmd_lower:
        nums = runtime._numbers(cmd_lower)
        if nums:
            level = min(nums[0], 100)
            if runtime.system_control.set_brightness(level):
                return f"Ekran parlaklığını yüzde {level} olarak ayarladım."
            return "Ekran parlaklığını ayarlayamadım."

    # Bilgisayarı kapatma: iptal komutu önce kontrol edilir, kapatma için onay istenir.
    if "kapatmayı iptal" in cmd_lower or "kapatma iptal" in cmd_lower:
        if runtime.system_control.cancel_shutdown() is False:
            return 'Kapatma iptal komutu kabul edilmedi; iptal edildi demiyorum.'
        return "Zamanlanmış bilgisayar kapatma işlemini iptal ettim."
    if "bilgisayarı kapat" in cmd_lower or "pc kapat" in cmd_lower:
        runtime._session().pending_confirm = "shutdown"
        return "Bilgisayarı kapatmamı onaylıyor musun? Evet ya da hayır de."

    if runtime.re.fullmatch(r"(?:konuşmayı|konuşmanı|cevabı|seslendirmeyi)\s+(?:durdur|kes|sustur)[.!?]*", cmd_lower):
        runtime.requests_state.cancel(runtime.profile.slug)
        runtime.voice.stop_speaking()
        return "Konuşmayı durdurdum."

    # Medya
    if any(w in cmd_lower for w in ("müzik", "şarkı", "oynat", "durdur")):
        if "sonraki" in cmd_lower or runtime._has_word(cmd_lower, "geç"):
            runtime.system_control.media_control("next")
            return "Sonraki şarkıya geçiliyor."
        if "önceki" in cmd_lower:
            runtime.system_control.media_control("prev")
            return "Önceki şarkıya dönülüyor."
        if "durdur" in cmd_lower or "oynat" in cmd_lower or runtime._has_word(cmd_lower, "kes"):
            runtime.system_control.media_control("play_pause")
            return "Medya oynatıcısı tetiklendi."

    # Ekran görüntüsü (analiz isteği değilse)
    wants_analysis = any(w in cmd_lower for w in ("analiz", "açıkla", "incele", "ne görüyor", "oku"))
    if ("ekran görüntüsü" in cmd_lower or "screenshot" in cmd_lower or "resmini çek" in cmd_lower) \
            and not wants_analysis:
        return runtime.desktop.screenshot()

    # Sistem durumu
    if runtime.re.search(r"\bsaat (kaç|ne)\b|\bsaati\b", cmd_lower):
        return "Saat " + runtime.time.strftime("%H:%M")
    if "günlerden" in cmd_lower or runtime.re.search(r"\bhangi gün\b|\bayın kaçı\b|\btarih(i)?\b", cmd_lower):
        return runtime.time.strftime("Bugün %d.%m.%Y, ") + runtime._DAYS[runtime.time.localtime().tm_wday]

    if "sistem durumu" in cmd_lower or "bilgisayar durumu" in cmd_lower or "pc durumu" in cmd_lower:
        return runtime.desktop.system_status()

    # Döviz (LLM'e gitmeden gerçek kur çeker)
    if "dolar" in cmd_lower or "euro" in cmd_lower:
        from modules import finance
        return finance.get_live_rate("dolar" if "dolar" in cmd_lower else "euro")

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

    # Uygulama kapatma: "chrome'u kapat", "word'ü kapatır mısın" (pencereye nazikçe kapan denir)
    cm = runtime.re.match(r"^(?:lütfen\s+)?(.+?)\s+(?:kapat|kapatır mısın|kapatsana|kapa)$", cmd_lower)
    if cm and len(cm.group(1)) <= 40 and not runtime.re.match(
            r"^(?:ses|sesi|müzi|bilgisayar|pc|mikrofon|kamera|ekran|paylaşım|ışı|wifi|internet|bluetooth|"
            r"jarvis|telefon|uyku|alarm|hatırlat|bildirim|parlaklı)", cm.group(1)):
        closed = runtime.system_control.close_application(cm.group(1))
        if closed:
            return closed

    # Uygulama açma: yalnızca izinli listedeki uygulamalar
    om = runtime.re.match(r"^(?:lütfen\s+)?(.+?)\s+(?:aç|açar mısın|açsana|başlat|çalıştır)$", cmd_lower)
    if om and len(om.group(1)) <= 40:
        spoken = runtime.re.sub(r"\b(uygulamasını|programını|uygulamayı|programı|oyununu|oyunu)\b", "", om.group(1)).strip()
        # Native app lookup must return real choices/failure, never a chat promise.
        if not runtime.re.match(r'^(?:ses|sesi|ışık|ışı|kapı|kamera|mikrofon|wifi|bluetooth|internet|onu|bunu|şunu|o|bu|şu|az önceki)\b', spoken):
            from modules.command_execution import open_app
            return open_app(runtime, spoken)

    # ---- Yazım hatası: hiçbir kalıba uymadıysa düzeltilmiş hâliyle bir kez daha dene ("kotrol" -> "kontrol") ----
    pass  # Shared fields are held by the explicit engine context.
    if not runtime._typo_pass:
        fixed = runtime.typo.fix(cmd_lower)
        if fixed != cmd_lower:
            runtime.log.info("İşlem kaydı: %s", 'main.py:handle')
            runtime._typo_pass, runtime._typo_orig = True, command
            try:
                return runtime.handle(fixed)
            finally:
                runtime._typo_pass, runtime._typo_orig = False, ""
    elif runtime._typo_orig:
        # Düzeltilmiş hâli de hızlı komutlara uymadı: yapay zekaya kullanıcının yazdığı asıl cümle gitsin
        # ("yarış merhaba" -> "yarın merhaba" gibi bozulmalar olmasın; yapay zeka yazım hatasını zaten anlar).
        command = runtime._typo_orig
        cmd_lower = runtime._tr_lower(command)

    # ---- Karmaşık istekler: LLM ile niyet tespiti ----
    # Sınıflandırma ve cevap sıralıdır; kullanılmayacak cevap için ek kota harcanmaz.
    try:
        r = runtime.route(command)
    except Exception:
        runtime._record_failure('main.py:handle')
        raise
    intent = str(r.get("intent") or "chat")
    a = r.get("args")
    if not isinstance(a, dict):
        a = {}
    runtime.profile.log_command(intent)
    # "Bekle, önce analiz bitsin" gibi cümleler yanlışlıkla müziği duraklatmasın: medya kelimesi yoksa sohbet say
    if intent == "media" and not runtime.re.search(r"müzi|şarkı|video|oynat|\bçal\b|çalsın|duraklat|parça|youtube|spotify|"
                                           r"sonraki|önceki|devam ettir", cmd_lower):
        intent = "chat"

    from modules.engine_intents import dispatch
    return dispatch(runtime, intent, a, command, cmd_lower)
