"""engine tools; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def _tr_lower(runtime, text: str) -> str:
    """Türkçe harflere uygun küçük harf (I -> ı, İ -> i)."""
    return text.replace("I", "ı").replace("İ", "i").lower()

def _numbers(runtime, text: str) -> list[int]:
    return [int(n) for n in runtime.re.findall(r"\d+", text)]

def _has_word(runtime, text: str, *words: str) -> bool:
    """Kelime başı eşleşmesi: 'geç' kelimesi 'geçmiş' ile karışmaz ('geç', 'geçiyor' kabul)."""
    return any(runtime.re.search(rf"\b{runtime.re.escape(w)}", text) for w in words)

def _web_search(runtime, query: str) -> None:
    runtime.desktop.open_url(f"https://www.google.com/search?q={runtime.quote_plus(query)}")

def _weather(runtime, location: str | None = None) -> str:
    """Hava durumunu söyler. Şehir verilmediyse kayıtlı şehri, o da yoksa IP'den bulunan konumu kullanır."""
    city = (location or "").strip() or runtime.profile.data["prefs"].get("city")
    text = runtime.weather.report(city or None)
    if text:
        return text
    if not city:   # konum otomatik bulunamadı (ağ yok ya da servis kapalı): ancak o zaman sor
        runtime._session().pending_weather_location = True
        return "Konumunu otomatik bulamadım. Hangi şehir için hava durumuna bakayım?"
    runtime._web_search(f"{city} hava durumu")
    return f"{city} için hava bilgisini alamadım, tarayıcıda aramasını açtım."

def _volume_step(runtime, delta: int, verb: str) -> str:
    new_vol = runtime.system_control.change_volume_by_delta(delta)
    if new_vol is None:
        return "Ses seviyesini değiştiremedim."
    return f"Ses seviyesini {verb}. Yeni seviye yüzde {new_vol}."

def _file_command(runtime, command: str) -> str | None:
    from modules import main_documents
    return main_documents._file_command(runtime, command)

def _study_media_topic(runtime, cmd_lower: str) -> str:
    t = runtime.re.sub(r"\b(bununla|bunlarla|bu konuyla|konuyla|alakalı|ilgili|hakkında|bir|bana|birkaç|sağ\w*|sekme\w*|pencere\w*|"
               r"görsel\w*|resim\w*|fotoğraf\w*|şekil\w*|video\w*|wikipedia\w*|vikipedi\w*|youtube\w*|göster\w*|aç\w*|"
               r"ver\w*|bul\w*|getir\w*|misin|mısın|musun|müsün|lütfen|gösteren|arasındaki|farkı?|olabilir|mesela|örneğin|yani|"
               r"sanki|şey|acaba|daha|olarak|şimdi|hemen|da|de)\b", " ", cmd_lower)
    return runtime.re.sub(r"\s+", " ", t).strip(" .,?!")

def _study_intent(runtime, cmd_lower: str) -> str | None:
    # Hoca modu: yalnız açık söyleniş ("hoca modu: X", "X konusunu öğret") ve aktif dersin komut/cevapları; gerisi normal yol.
    from modules import requests_state
    try:
        from config import load_settings
        from modules import hoca
        settings = load_settings()
        reply = hoca.handle(runtime.profile, cmd_lower, enabled=bool(settings.get("hoca_enabled", True)))
        if reply:
            if settings.get("hoca_voice_full"):
                # Sesli Hoca modu (6. adım): genel kısa okuma sınırı (400 karakter) ders anlatımını
                # yarıda keser; bu ayar açıkken tam metin okunur. En iyi çaba — başarısız olursa
                # yazılı cevap etkilenmez, yalnız sesli okuma normal kısa haline döner.
                try:
                    runtime._session().speech_override = runtime.richtext.speakable(reply)
                except Exception:
                    runtime._record_failure('main.py:_study_intent')
            return reply
    except (requests_state.Cancelled, PermissionError):
        raise
    except Exception:
        runtime._record_failure('main.py:_study_intent')
    if runtime.re.fullmatch(r"(?:ders )?çalışmaya başla[.! ]*", cmd_lower.strip()):
        runtime.emit("study_start", "")
        return "Çalışma ekranında seçili konu veya kaynaktan dersi hazırlıyorum."
    # Çalışırken "görsel/video göster": tarayıcıda Google açmak yerine Çalışma ekranındaki yan pencerede göster
    if runtime._MEDIA_Q.search(cmd_lower):
        try:
            from modules import study
            if study._state(runtime.profile).get("docs"):
                topic = runtime._study_media_topic(cmd_lower)
                if len(topic) < 3:
                    topic = study.last_topic(runtime.profile)
                if topic:
                    runtime.emit("nav", "study")
                    runtime.emit("study_media", topic)
                    return f"{topic} ile ilgili görselleri ve videoları sağdaki pencerede açtım."
        except Exception:
            runtime._record_failure('main.py:_study_intent')
    plan_q = runtime.re.search(r"(?:ders|çalışma)\s+program|programım|bugün ne çalış|bugünkü çalışma", cmd_lower)
    focus_q = runtime.re.search(r"(?:hangi|ne)\s+(?:konu\w*\s+|derse?\s+)?çalış|hangi\s.{0,25}konu\w*\s.{0,12}çalış|neye çalış|ne çalışay|sınav analiz\w*|"
                        r"zayıf\s+(?:olduğum|konu)|eksik\s+(?:olduğum|konu)|eksiklerim|nereden başla", cmd_lower)
    if not (plan_q or focus_q):
        return None
    try:
        from modules import study, studyexam
        if not study._state(runtime.profile).get("docs"):
            return None
        if plan_q:
            p = studyexam.plan(runtime.profile)
            if not p.get("days"):
                return p.get("note") or "Henüz ders programın yok. Çalışma ekranında Programım sekmesinden oluşturabilirsin."
            d = p["days"][0]
            today = " ve ".join(f"{b.get('topic') or b['text']} {b['minutes']} dakika" for b in d["blocks"])
            nxt = "; ".join(f"{x['day']} {x['blocks'][0].get('topic') or x['blocks'][0]['text']}" for x in p["days"][1:4])
            left = f" Sınava {p['days_left']} gün kaldı." if p.get("days_left") is not None else ""
            return f"{d['day']} günü programın: {today}.{left}" + (f" Sonraki günler: {nxt}." if nxt else "")
        fc = studyexam.focus(runtime.profile, 3)
        if not fc:
            return ("Yönlendirme için önce Çalışma ekranında dersini seçip sınav analizini başlatman gerekiyor; "
                    "ondan sonra hangi konuya çalışacağını söyleyebilirim.")
        items = "; ".join(f"{i + 1}. {f['topic']} (sınavda yüzde {f['weight']:g}, {f['why']})" for i, f in enumerate(fc))
        return (f"Çıkmış sorulara ve senin sonuçlarına göre öncelik sırası: {items}. "
                f"İstersen {fc[0]['topic']} konusunu anlatmaya başlayayım ya da Çalışma ekranındaki Soru Çöz'den bu konudan soru çözebilirsin.")
    except Exception:
        runtime._record_failure('main.py:_study_intent')
        return None

def _translate_file(runtime, path: str, target: str) -> str:
    from modules import main_documents
    return main_documents._translate_file(runtime, path, target)

def _plain(runtime, text: str) -> str:
    from modules import main_planner
    return main_planner._plain(runtime, text)

def _note_text(runtime, command: str, cmd_lower: str) -> str:
    from modules import main_planner
    return main_planner._note_text(runtime, command, cmd_lower)

def _add_note(runtime, text: str, photo: str | None = None) -> dict:
    from modules import main_planner
    return main_planner._add_note(runtime, text, photo)

def _fix_word(runtime, text: str, right: str) -> str | None:
    from modules import main_planner
    return main_planner._fix_word(runtime, text, right)

def _note_fix(runtime, command: str, cmd_lower: str) -> str | None:
    from modules import main_planner
    return main_planner._note_fix(runtime, command, cmd_lower)

def _keep_photo(runtime, src: str) -> str:
    from modules import main_documents
    return main_documents._keep_photo(runtime, src)

def _sys_prompt(runtime, command: str = "") -> str:
    """Sohbet talimatı. Soru sesle sorulduysa cevap kısa olsun (hızlı gelir, dinlemesi kolay); 'Detaylı' seçiliyse dokunma."""
    base = runtime.profile.system_prompt(command)
    try:
        from config import load_settings
        from modules import advisory_router
        base += (" " + advisory_router.prompt_for(command, load_settings())).strip()
    except Exception:
        runtime._record_failure("modules/engine_tools.py:_sys_prompt")
    base += (' Bu yanıt yalnızca sohbet metnidir; bu yolda bilgisayar işlemi, dosya değişikliği veya arka plan görevi çalıştırılmaz. '
             'İşlem yaptığını/yapacağını veya çalışmaya başladığını söyleme. Desteklenmeyen eylemde sınırı açıkla; '
             'belirsiz hedefte tek net soru sor. Yalnızca gerçekten ürettiğin metni/kodu hazır olarak sunabilirsin.')
    if runtime._cur_source == "ses" and runtime.profile.data["prefs"].get("verbosity", "orta") != "uzun":
        base += (" Bu soru sesle soruldu ve cevabın sesli okunacak: en fazla 2 kısa cümleyle doğrudan cevap ver. "
                 "Liste, kod ya da uzun açıklama gerekiyorsa kısaca özetle ve 'ayrıntısını ekrana yazayım mı?' diye sor.")
    return base

def _notes_text(runtime) -> str:
    from modules import main_planner
    return main_planner._notes_text(runtime)

def _agenda_text(runtime, day: str, label: str) -> str:
    from modules import main_planner
    return main_planner._agenda_text(runtime, day, label)

def _add_event(runtime, title: str, when: str) -> str:
    from modules import main_planner
    return main_planner._add_event(runtime, title, when)

def _planner_command(runtime, command: str, cmd_lower: str) -> str | None:
    from modules import main_planner
    return main_planner._planner_command(runtime, command, cmd_lower)

def load_approve(runtime) -> bool:
    """Hassas işlemlerde (mesaj gönderme, kapatma, dosya taşıma) onay iste. Ayarlar -> approve_sensitive (varsayılan açık)."""
    from config import load_settings
    return bool(load_settings().get("approve_sensitive", True))

def _message_step(runtime, command: str | None, cmd_lower: str) -> str | None:
    """WhatsApp akışının bir adımı. command=None ise yeni başlamıştır. None dönerse akış iptal olmuş, normal işlem sürer."""
    from modules.confirmation import decision
    p = runtime._session().pending_msg
    assert p is not None
    if command is not None:
        from modules import brain_entry
        if brain_entry.matched_protocol("session.pending_msg.cancel") \
                or cmd_lower.strip(" .!?") in ("iptal", "iptal et", "vazgeç", "vazgeçtim", "boşver"):
            runtime._session().pending_msg = None
            return "Tamam, mesajı göndermedim."
        stage = p["stage"]
        if stage == "to":
            p["to"] = runtime.re.sub(r"['’](?:e|a|ye|ya)$", "", command.strip(" .")).strip() or p["to"]
        elif stage == "text":
            p["text"] = command.strip()
    if not p["to"]:
        p["stage"] = "to"
        return "Kime yazayım?"
    if not p["text"]:
        p["stage"] = "text"
        return f"{p['to']} kişisine ne yazayım?"
    name, text = p["to"], p["text"]
    if runtime.load_approve() and not p.get("confirmed"):
        if command is not None and p.get("stage") == "confirm":
            approval = decision(cmd_lower, extra=('gönder', 'gonder', 'evet gönder', 'evet gonder', 'gönder gitsin', 'gonder gitsin'))
            if approval is True:
                p["confirmed"] = True
            elif approval is False:
                runtime._session().pending_msg = None
                return "Tamam, mesajı göndermedim."
            else:
                runtime._session().pending_msg = None
                return None            # başka komut geldi: akış iptal, normal işlem sürer
        if not p.get("confirmed"):
            p["stage"] = "confirm"
            return f"{name} kişisine şunu göndereyim mi: “{text}”? Evet ya da hayır de."
    runtime._session().pending_msg = None
    found = runtime.messaging.find_contact(runtime.profile.data.get("contacts", {}), name)
    phone = None
    if found:
        name, phone = found

    owner = runtime.profile
    task_id = runtime.secrets.token_hex(16)
    if not runtime.requests_state.register_background(owner.slug, task_id):
        return 'Mesaj gönderimi başlatılmadı; işlem kimliği zaten kayıtlı.'
    import contextvars
    captured_context = contextvars.copy_context()
    def work() -> None:
        try:
            with runtime.requests_state.activate(owner.slug, task_id):
                runtime.requests_state.check()
                result = runtime.messaging.send_whatsapp(name, text, phone)
                runtime.privacy.audit("whatsapp gönderim denemesi", f"{name} kişisine ({len(text)} karakter)")
        except runtime.requests_state.Cancelled:
            result = "WhatsApp gönderim işlemi iptal edildi."
        except Exception as exc:
            runtime._record_failure('main.py:whatsapp_worker')
            from modules.diagnostics import user_message
            result = "Mesaj gönderim işlemi tamamlanamadı: " + user_message(exc)
        runtime._emit_for(owner, "assistant", result)
        if owner.slug == runtime.pc_profile().slug:
            runtime.events.put(("say", result, owner.slug))

    try:
        runtime.threading.Thread(target=lambda: captured_context.run(work), daemon=True).start()
    except BaseException:
        runtime.requests_state.cancel(owner.slug, task_id)
        raise
    return f"{name} kişisine gönderiyorum: \"{text}\". Klavye ve fareye birkaç saniye dokunma."

def _macro_key(runtime, text: str) -> str:
    from modules import main_planner
    return main_planner._macro_key(runtime, text)

def _macro_teach(runtime, command: str, cmd_lower: str) -> str | None:
    from modules import main_planner
    return main_planner._macro_teach(runtime, command, cmd_lower)

def _macro_run(runtime, cmd_lower: str) -> str | None:
    from modules import main_planner
    return main_planner._macro_run(runtime, cmd_lower)

def _macro_manage(runtime, cmd_lower: str) -> str | None:
    from modules import main_planner
    return main_planner._macro_manage(runtime, cmd_lower)

def _screen_ocr(runtime, prompt: str) -> str:
    import pyautogui
    path = runtime.os.path.join(runtime.tempfile.gettempdir(), "jarvis_ocr.png")
    try:
        pyautogui.screenshot(path)
        return runtime.ask_image(path, prompt, "").strip()
    finally:
        try:
            runtime.os.remove(path)
        except OSError:
            pass

def _brief_facts(runtime) -> list[str]:
    from modules import main_planner
    return main_planner._brief_facts(runtime)

def _daily_briefing(runtime) -> str:
    from modules import main_planner
    return main_planner._daily_briefing(runtime)

def _morning_brief(runtime) -> None:
    from modules import main_planner
    return main_planner._morning_brief(runtime)

def _important_mail(ga, outlook, cmd_lower: str) -> str:
    """"Önemli maillerim": önem işareti yalnız Gmail'de var. Gmail bağlıysa o (Outlook da varsa iş maili yolunu söyler);
    Gmail yoksa Outlook'un okunmamışları ve neden öyle olduğu; ikisi de yoksa neyin eksik olduğu."""
    if ga._ready() is None:
        reply = ga.important_text()
        if outlook.installed():
            reply += ' İş mailin (Outlook) için "iş maillerimi kontrol et" de.'
        return reply
    if outlook.installed():
        return outlook.unread_mail(prefix="Gmail bağlı değil, o yüzden önemli işaretine bakamadım. "
                                          + outlook.IMPORTANT_NOTE)
    reply = ga.important_text()
    if reply != ga.SETUP_HELP:
        return reply
    return reply + " Bu bilgisayarda klasik Outlook da kurulu değil, iş maili için o da kullanılamıyor."

def _mail_handle(runtime, cmd_lower: str) -> str | None:
    """İş maili (Outlook) açıkça istenirse yalnızca onu; genel 'maili kontrol et'te Gmail + açıksa Outlook.

    BRAIN-MIG-051 (§12) envanteri: bu dört sıra (meeting prep → Outlook draft → Outlook okuma →
    Gmail) provider/account değişmezlerinin domain sahibidir; "bu cümle mail mi?" hükmünü de
    burada verir. Kanonical communication/mail capability ve Core eşlemesi gelene kadar bu hüküm
    PR3C satırıdır (kilit: `CascadeRootTests.test_the_mail_owner_is_reached_only_from_the_cascade`
    — yüzeylerden hiçbir yer doğrudan buraya bakamaz, tek giriş cascade kolu). Provider eklenmez,
    Gmail/Outlook davranışı yeniden yazılmaz.
    """
    from modules import meeting_prep, outlook
    if meeting_prep.asked(cmd_lower):
        return meeting_prep.handle(cmd_lower, runtime.profile, runtime.datetime.now())
    reply = outlook.draft_handle(cmd_lower, getattr(runtime, "ask", None))
    if reply is not None:
        return reply
    reply = outlook.handle(cmd_lower)
    if reply is not None:
        return reply
    ga = runtime.google_api
    from modules import google_api as _g
    if _g._IMPORTANT.search(cmd_lower) and not _g._MAIL_SEND.search(cmd_lower):
        return _important_mail(_g, outlook, cmd_lower)
    reply = ga.handle(cmd_lower)
    if reply is not None and runtime.google_api._MAIL_CHECK.search(cmd_lower) and outlook.installed():
        reply = "Gmail: " + reply + " İş (Outlook): " + outlook.unread_mail()
    return reply

def _extra_commands(runtime, command: str, cmd_lower: str) -> str | None:
    """Domain cascade'inin tek sırası; §0 envanteri koldan kaleme sınıflandırıldı.

    Bu cascade tek bir yerden çağrılır: `engine_commands.handle` kuyruğu
    `brain_precedence.claim_tail` üzerinden sıra sözleşmesine devredildi (§25 B) ve başka üretim
    çağıranı yoktur (§25 D kilidi
    `CascadeRootTests.test_the_cascade_has_one_production_call_owner`). Her kol kendi
    tanırıcısıyla ilk-yanıt-verir; sınıflar A KEEP_STATE / B KEEP_EXACT_ADMIN / C
    KEEP_DOMAIN_EXECUTION / D RETIRE_RAW_FRONT_DOOR:

    1. `finance_alert_commands` (B): kalıp `fullmatch`/tam küme üyeliğidir, cümlenin *içinde*
       alan aramaz — ölçüldü, §13'ün "global semantic selection" ön kabulu kod gerçeği değil.
       Kalan iş alarmın kanonical öneri/Core eşlemesi (BRAIN-MIG-053 → PR3C).
    2. `plugins` (D → PR3C): kullanıcı eklentileri ham cümleyi sırayla yoklar; kanonical sahibi
       ve capability sözlüğü yok. Kaldırmak ürün gerilemesidir, parity ile sökülecek.
    3. `handoff` (D → PR3C): "işte neler var / evde neler var" `re.search` ile sabit-önek değil.
    4. `folder_analysis` (D, PR3C-4 kapandı): ham kalıp ve `_NOT_THIS` vetosu artık yok; karar
       `brain_understanding.folder_analysis_request` → Core `folder_analyze` → `engine_intents` →
       `folder_analysis.analyze_turn` zincirinde yürür. İzinli kökler, derinlik/okuma sınırları, gizli
       dosya ve yalnız-çevrimiçi korumaları ile KB dizine ekleme + en çok bir model çağrısı yürüticide
       olduğu gibi kaldı; tek dosya isteği (`files.read`) karışmaz.
    5. `browser` (C): URL + özetleme ya da sabit "… ara" kalıbı; effekte gitmeden önce privacy
       kapısı var. Kanonical sayfa-okuma capability'si yok → PR3C.
    6. `günlük özet` (D → PR3C, §21): cümlenin içinde aranan fazlasıyla uzun bir sözcük listesi;
       briefing'i ayrı bir alt sistem kurmadan en yakın kanonical okuma yeteneğine bağlama kararı
       PR3C'nindir.
    7. `tasks` ve 8. `kb` (C): eklemeler `re.match` ile kalıba bağlı; kb'nin "hangi dosyada"
       doğal soruları domain-owned. Görev yönetimi/kanonical `task` eşlemesi BRAIN-MIG-070 → PR3C.
    9. ekran metni kopyala/oku ve 10. ekran hatası → not (D → PR3C, §20): typed
       `screen.text.read` / `screen.text.copy` / `screen.error.note` kararı bekliyor; OCR ve
       nota-yazma yürütmesi mevcut domain sahibinde kalır.
    11. `file_ops` (C) tek dosya taşı/yeniden adlandır/oluştur/geri al; 12. düzenlemeyi geri al
        ve 13. klasör düzenleme planı (C, §22 bounded onay akışı) → BRAIN-MIG-052/048 PR3C.
    14. `filesend` (C): Taildrop dosya gönderimi; "hangisi?" cevabını kendi 180 sn'lik modül-içi
        bekleyen listesiyle tüketir — bu, kanonical `pending_answer_owned` sahibi olmayan ikinci
        bir bekleyen yetkisidir ve PR3C'de kanonical clarification'a bağlanmalı (§33 yasağı).
    15. `worktrack`, 16. `files`, 17. `media`, 18. `_mail_handle`, 19. `notify` (C): alanların
        kendi yürütme kapıları; hiçbiri kanonical karar sonrası genel domain seçimi yapmamalı,
        kanonical capability'leri gelene kadar PR3C envanterindedir.

    §33: buradaki kalıplar başka bir helper'a taşınarak "emekli" ilan edilmez; bir kol ancak
    kanonical capability + Core eşlemesi + owner testleri parite verdiğinde bu sıradan silinir.
    """
    from modules import finance_alert_commands
    if finance_alert_commands.matches(command):
        return finance_alert_commands.handle(runtime.profile.slug, command)
    plug = runtime.plugins.handle(command, cmd_lower)
    if plug:
        return plug
    try:                                              # ev/iş devir listesi: "yarın işte … bakayım", "evde neler var"
        from modules import handoff
        hand = handoff.handle(command, cmd_lower)
        if hand:
            return hand
    except Exception:
        runtime._record_failure('main.py:_extra_commands')
    web = runtime.browser.handle(cmd_lower)
    if web:
        return web
    if runtime.re.search(r"günlük özet|bugünün özeti|sabah özeti|günümü özetle|brifing|gün özeti|bugün neler (?:oldu|var)|"
                 r"bugün ne var|neler var bugün|günüm nasıl|bugünkü durum|bugün ne yapıyoruz", cmd_lower):
        return runtime._daily_briefing()
    # Ekrandaki metni kopyala / oku / hatayı nota ekle
    tasks_reply = runtime.tasks.handle(cmd_lower, runtime.profile)     # görev listesi komutu
    if tasks_reply:
        return tasks_reply
    kb_reply = runtime.kb.handle(cmd_lower, runtime.profile)           # bilgi tabanı komutu
    if kb_reply:
        return kb_reply
    if runtime.re.search(r"ekrandaki\s+(?:metn\w*|yaz\w*)\s+(?:kopyala|al|çıkar|oku)\b|ekran(?:ın)?\s+metnini", cmd_lower):
        text = runtime._screen_ocr("Bu ekran görüntüsündeki tüm okunabilir metni olduğu gibi, satır düzenini koruyarak yaz. "
                           "Yorum, başlık ya da açıklama ekleme; yalnızca metin.")
        if not text:
            return "Ekranda okunabilir bir metin bulamadım."
        if runtime.re.search(r"\boku\b", cmd_lower):
            return text
        ok = runtime._copy_text(text)
        head = " ".join(text[:80].split())
        if not ok:
            return "Metni çıkardım ama panoya kopyalayamadım."
        return f"Ekrandaki metni panoya kopyaladım ({len(text)} karakter). Başı: “{head}…”"
    if runtime.re.search(r"ekrandaki\s+hata\w*\s+(?:not al|kaydet|nota ekle|not et)", cmd_lower):
        text = runtime._screen_ocr("Ekranda bir hata ya da uyarı mesajı varsa, Türkçe olarak tek cümleyle ne olduğunu ve "
                           "olası çözümünü yaz. Hata yoksa sadece 'Hata görünmüyor' yaz.")
        if not text or "Hata görünmüyor" in text:
            return "Ekranda bir hata görünmüyor."
        runtime.profile.add_note_item("Ekran hatası: " + " ".join(text.split()))
        return "Ekrandaki hatayı notlarına ekledim: " + " ".join(text.split())[:200]
    # PR3C-5: file mutations are handled only by canonical Brain -> Core typed proposals.
    # Klasör düzenleme geri alması (önizleme artık kanonical: `files.organize` → `file_organize`)
    if runtime.re.search(r"düzenlemey[ie] geri al|düzenlemeyi iptal et|taşıdıklarını geri", cmd_lower):
        back = runtime.files.undo_organize(runtime.profile.slug)
        return "Geri alınacak bir düzenleme kaydı yok." if back is None else f"{back} dosyayı eski yerine taşıdım."
    from modules import filesend, worktrack
    sent = filesend.handle(cmd_lower)                 # "test planını telefonuma gönder" (Tailscale Taildrop)
    if sent is not None:
        return sent
    work = worktrack.handle(cmd_lower, runtime.profile)       # iş takibi: proje durumu, cevap bekleyenler, tarihli işler
    if work is not None:
        return work
    files_reply = runtime.files.handle(cmd_lower)     # "indirilenlerdeki son dosyayı aç", "masaüstünü aç"
    if files_reply is not None:
        return files_reply
    media_reply = runtime.media.handle(cmd_lower)     # "youtube'da türkü aç", "spotify'da podcast aç"
    if media_reply is not None:
        return media_reply
    mail_reply = runtime._mail_handle(cmd_lower)      # BRAIN-MIG-051: provider kararları domain'de
    if mail_reply is not None:
        return mail_reply
    return runtime.notify.handle(cmd_lower, runtime.profile.data["prefs"], runtime.profile.save)
