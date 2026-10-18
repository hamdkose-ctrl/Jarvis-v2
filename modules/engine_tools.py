"""engine tools; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def route(runtime, command: str) -> dict:
    session = runtime._session()
    from modules import privacy
    recent = runtime._recent_turns(runtime.profile.slug, hours=2, limit=6)
    context = {'recent_turns': [(role, privacy.redact(text[:1600], force=True)) for role, text in recent],
               'last_command': session.last_command,
               'pending_request': session.pending_request}
    context = privacy.redact(runtime.json.dumps(context, ensure_ascii=False), force=True)
    result = runtime.intent_router.classify(command, runtime.ask, context=context)
    session.pending_request = None
    if result.get('intent') != 'clarify':
        session.last_command = command[:2000]
    return result

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

def _city_in(runtime, cmd_lower: str) -> str | None:
    """'izmir hava durumu', 'ankara'da hava nasıl' gibi cümlelerden şehri çıkarır."""
    m = runtime.re.search(r"([a-zçğıöşü]{3,}?)(?:['’]?(?:da|de|ta|te|daki|deki|nın|nin))?\s+hava", cmd_lower)
    if not m or m.group(1) in runtime._WEATHER_STOP:
        return None
    word = m.group(1)
    return (word[:1].replace("i", "İ").replace("ı", "I").upper() + word[1:]) if word else None

def _volume_step(runtime, delta: int, verb: str) -> str:
    new_vol = runtime.system_control.change_volume_by_delta(delta)
    if new_vol is None:
        return "Ses seviyesini değiştiremedim."
    return f"Ses seviyesini {verb}. Yeni seviye yüzde {new_vol}."

def _explicit_output_format(runtime, command_lower: str) -> str | None:
    """Kullanıcı analiz sonucunu açıkça belirli dosya formatında istediyse onu döndürür."""
    c = command_lower
    if runtime.re.search(r"(?:sonuc|rapor|çıktı|cikti).{0,35}(?:excel|xlsx)|(?:excel|xlsx).{0,25}(?:olarak|format|rapor|çıktı|cikti|hazırla|olustur|oluştur)", c):
        return "xlsx"
    if runtime.re.search(r"(?:sonuc|rapor|çıktı|cikti).{0,35}(?:word|docx)|(?:word|docx).{0,25}(?:olarak|format|rapor|çıktı|cikti|hazırla|olustur|oluştur)", c):
        return "docx"
    if runtime.re.search(r"(?:sonuc|rapor|çıktı|cikti).{0,35}(?:pdf)|(?:pdf).{0,25}(?:olarak|formatında|rapor|çıktı|cikti|hazırla|olustur|oluştur)", c):
        return "pdf"
    return None

def _file_command(runtime, command: str) -> str | None:
    from modules import main_documents
    return main_documents._file_command(runtime, command)

def _resolve_doc(runtime, raw, command: str='') -> tuple[str | None, str | None]:
    from modules import main_documents
    return main_documents._resolve_doc(runtime, raw, command)

def _folder_overview(runtime, folder) -> str:
    from modules import main_documents
    return main_documents._folder_overview(runtime, folder)

def _study_answer(runtime, command: str, cmd_lower: str) -> str | None:
    """Dosya adı verilmeden "o kitaptan örnek ver", "çıkmış sorulardan sor" denirse: Çalışma'ya yüklenen
    kitap / çıkmış sorulardan cevap ver (bu kaynaklar dosya listesinde değil, Çalışma modülünde durur)."""
    if not runtime.re.search(r"kitap|kaynak|çıkmış|sınav|ünite|konu|çalış|test|soru|örnek", cmd_lower):
        return None
    try:
        from modules import study
        if not study._state(runtime.profile).get("docs"):
            return None
        return study.ask(runtime.profile, command)
    except Exception:
        runtime._record_failure('main.py:_study_answer')
        return None

def _study_media_topic(runtime, cmd_lower: str) -> str:
    t = runtime.re.sub(r"\b(bununla|bunlarla|bu konuyla|konuyla|alakalı|ilgili|hakkında|bir|bana|birkaç|sağ\w*|sekme\w*|pencere\w*|"
               r"görsel\w*|resim\w*|fotoğraf\w*|şekil\w*|video\w*|wikipedia\w*|vikipedi\w*|youtube\w*|göster\w*|aç\w*|"
               r"ver\w*|bul\w*|getir\w*|misin|mısın|musun|müsün|lütfen|gösteren|arasındaki|farkı?|olabilir|mesela|örneğin|yani|"
               r"sanki|şey|acaba|daha|olarak|şimdi|hemen|da|de)\b", " ", cmd_lower)
    return runtime.re.sub(r"\s+", " ", t).strip(" .,?!")

def _study_intent(runtime, cmd_lower: str) -> str | None:
    # Hoca modu: yalnız açık söyleniş ("hoca modu: X", "X konusunu öğret") ve aktif dersin komut/cevapları; gerisi normal yol.
    try:
        from config import load_settings
        from modules import hoca
        reply = hoca.handle(runtime.profile, cmd_lower, enabled=bool(load_settings().get("hoca_enabled", True)))
        if reply:
            return reply
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

def _photo_action(runtime, path: str, question: str) -> str:
    from modules import main_documents
    return main_documents._photo_action(runtime, path, question)

def _sys_prompt(runtime, command: str = "") -> str:
    """Sohbet talimatı. Soru sesle sorulduysa cevap kısa olsun (hızlı gelir, dinlemesi kolay); 'Detaylı' seçiliyse dokunma."""
    base = runtime.profile.system_prompt(command)
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
        if cmd_lower.strip(" .!?") in ("iptal", "iptal et", "vazgeç", "vazgeçtim", "boşver"):
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

def _contact_command(runtime, command: str, cmd_lower: str) -> str | None:
    """Kişi numarası kaydetme: 'kişi ekle Ahmet 0532 123 45 67' / 'Ahmet'in numarası 0532...' / 'kişileri listele'."""
    m = runtime.re.match(r"^(?:kişi ekle|rehbere ekle|numara kaydet)\s+([a-zçğıöşü ]+?)\s+(\+?\d[\d\s\-()]{8,})$", cmd_lower) \
        or runtime.re.match(r"^([a-zçğıöşü]+)['’]?(?:in|ın|un|ün|nin|nın)\s+(?:numarası|telefonu)\s+(\+?\d[\d\s\-()]{8,})(?:\s+(?:kaydet|olarak kaydet))?$", cmd_lower)
    if m:
        phone = runtime.messaging.normalize_phone(m.group(2))
        if not phone:
            return "Numarayı anlayamadım, 0532 123 45 67 gibi söyler misin?"
        name = " ".join(runtime.display_name(w) for w in m.group(1).split())
        runtime.profile.data.setdefault("contacts", {})[name] = phone
        runtime.profile.save()
        return f"{name} kişisini kaydettim. Artık WhatsApp mesajları daha güvenilir gider."
    if runtime.re.search(r"kişileri (listele|göster)|rehberim", cmd_lower):
        names = list(runtime.profile.data.get("contacts", {}))
        return "Kayıtlı kişiler: " + ", ".join(names) + "." if names else "Kayıtlı kişi yok. \"kişi ekle Ahmet 0532 123 45 67\" diyebilirsin."
    return None

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
    """İş maili (Outlook) açıkça istenirse yalnızca onu; genel 'maili kontrol et'te Gmail + açıksa Outlook."""
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
    from modules import folder_analysis              # "İndirilenler klasörünü incele", "masaüstünde ne var"
    folder_reply = folder_analysis.handle(cmd_lower, runtime.profile)
    if folder_reply is not None:
        return folder_reply
    web = runtime.browser.handle(cmd_lower)
    if web:
        return web
    if runtime.re.search(r"günlük özet|bugünün özeti|sabah özeti|günümü özetle|brifing|gün özeti|bugün neler (?:oldu|var)|"
                 r"bugün ne var|neler var bugün|günüm nasıl|bugünkü durum|bugün ne yapıyoruz", cmd_lower):
        return runtime._daily_briefing()
    # Ekrandaki metni kopyala / oku / hatayı nota ekle
    for mod in (runtime.tasks, runtime.kb):            # görev listesi ve bilgi tabanı komutları
        out = mod.handle(cmd_lower, runtime.profile)
        if out:
            return out
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
    from modules import file_ops                      # tek dosya: taşı, yeniden adlandır, metin dosyası oluştur, geri al (onaysız, geri alınabilir)
    file_reply = file_ops.handle(command, runtime.profile.slug)
    if file_reply is not None:
        return file_reply
    # Klasör düzenleme (onaylı) ve geri alma
    if runtime.re.search(r"düzenlemey[ie] geri al|düzenlemeyi iptal et|taşıdıklarını geri", cmd_lower):
        back = runtime.files.undo_organize()
        return "Geri alınacak bir düzenleme kaydı yok." if back is None else f"{back} dosyayı eski yerine taşıdım."
    target = runtime.files.wants_organize(cmd_lower)
    if target:
        folder, label = target
        plan = runtime.files.plan_organize(folder)
        if not plan:
            return f"{label} klasöründe düzenlenecek dosya yok."
        runtime._session().pending_organize = {"folder": folder, "label": label, "plan": plan}
        return (f"{label} klasöründeki {len(plan)} dosyayı klasörlere taşıyayım mı? ({runtime.files.summary(plan)}) "
                "Kısayollar ve geçici dosyalar yerinde kalır, istersen “düzenlemeyi geri al” diyebilirsin. Evet mi?")
    from modules import filesend, worktrack
    sent = filesend.handle(cmd_lower)                 # "test planını telefonuma gönder" (Tailscale Taildrop)
    if sent is not None:
        return sent
    work = worktrack.handle(cmd_lower, runtime.profile)       # iş takibi: proje durumu, cevap bekleyenler, tarihli işler
    if work is not None:
        return work
    for fn in (runtime.files.handle, runtime.media.handle, runtime._mail_handle):
        reply = fn(cmd_lower)
        if reply is not None:
            return reply
    return runtime.notify.handle(cmd_lower, runtime.profile.data["prefs"], runtime.profile.save)
