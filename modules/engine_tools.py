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

def mail_read_typed(runtime, source: str) -> str:
    """Read the model-selected account via the existing Gmail/Outlook workers.

    No raw mail intent probe, sending, drafting or new account discovery.
    Gmail's important/starred semantics and Outlook's unread-only limitation
    remain owned by their current provider modules.
    """
    from modules import google_api, outlook, requests_state
    requests_state.check()
    if source in {"awaiting_mine", "awaiting_theirs"}:
        return google_api.awaiting_text("mine" if source == "awaiting_mine" else "theirs")
    if source in {"first_attachments", "first_attachment_read"}:
        from modules import task_agents
        return task_agents.mail_attachments_typed(
            runtime.profile.slug,
            "read_attachment" if source == "first_attachment_read" else "list_attachments",
            emit=runtime.emit)
    if source == "work":
        return outlook.unread_mail()
    if source == "work_important":
        return outlook.unread_mail(prefix=outlook.IMPORTANT_NOTE)
    if source == "inbox":
        return google_api.unread_mail()
    if source == "combined":
        gmail = google_api.unread_mail()
        if outlook.installed():
            requests_state.check()
            return "Gmail: " + gmail + " İş (Outlook): " + outlook.unread_mail()
        return gmail
    if source != "important":
        return "Mail kaynağını doğrulayamadım; hiçbir işlem yapmadım."
    problem = google_api._ready()
    if problem is None:
        answer = google_api.important_text()
        if outlook.installed():
            answer += ' İş mailin (Outlook) için "iş maillerimi kontrol et" de.'
        return answer
    if outlook.installed():
        return outlook.unread_mail(prefix="Gmail bağlı değil, o yüzden önemli işaretine bakamadım. "
                                  + outlook.IMPORTANT_NOTE)
    answer = google_api.important_text()
    if answer != google_api.SETUP_HELP:
        return answer
    return (answer + " Bu bilgisayarda klasik Outlook da kurulu değil, "
            "iş maili için o da kullanılamıyor.")


def _file_command(runtime, command: str) -> str | None:
    from modules import main_documents
    return main_documents._file_command(runtime, command)

def study_read(runtime, view: str, *, missing_reply: bool = True) -> str | None:
    """Typed Core study read; never classifies a new natural-language request.

    Lesson progression has a separate State and typed Hoca worker.
    """
    if view not in {'plan', 'focus'}:
        raise ValueError("Study view must be Core-validated.")
    from modules import requests_state
    requests_state.check()
    try:
        from modules import study, studyexam
        if not study._state(runtime.profile).get("docs"):
            return ("Çalışma ekranında önce bir konu veya kaynak seçip dersini hazırla." if missing_reply else None)
        if view == 'plan':
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
    except (requests_state.Cancelled, PermissionError):
        raise
    except Exception:
        runtime._record_failure('modules/engine_tools.py:study_read_typed')
        return ("Ders verisini şu an okuyamadım." if missing_reply else None)

def _translate_file(runtime, path: str, target: str) -> str:
    from modules import main_documents
    return main_documents._translate_file(runtime, path, target)

def _plain(runtime, text: str) -> str:
    from modules import main_planner
    return main_planner._plain(runtime, text)

def _add_note(runtime, text: str, photo: str | None = None) -> dict:
    from modules import main_planner
    return main_planner._add_note(runtime, text, photo)

def _fix_word(runtime, text: str, right: str) -> str | None:
    from modules import main_planner
    return main_planner._fix_word(runtime, text, right)

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
            # When the exact State Gate selected an existing contact, use its
            # owner-scoped candidate rather than parsing the sentence again.
            # Non-exact replies can only reach here under the model's typed
            # MESSAGE_TO pending ownership, and are revalidated below.
            selected = brain_entry.protocol_selection("session.pending_msg.recipient")
            p["to"] = (selected if isinstance(selected, str) and selected.strip()
                       else runtime.re.sub(r"['’](?:e|a|ye|ya)$", "", command.strip(" .")).strip()) or p["to"]
        elif stage == "text":
            p["text"] = command.strip()
    if not p["to"]:
        p["stage"] = "to"
        return "Kime yazayım?"
    if not p["text"]:
        p["stage"] = "text"
        return f"{p['to']} kişisine ne yazayım?"
    text = p["text"]
    contacts = runtime.profile.data.get("contacts", {}) or {}
    if p.get("confirmed") and p.get("phone"):
        name, phone = p["to"], p["phone"]
    else:
        # Onaydan ÖNCE çözümleme: onay metni kullanıcının gerçekten göndereceği kişiyi göstermeli.
        # İsim belirsizliği numara geçerliliğinden bağımsızdır: adı eşleşen herkes karara girer;
        # bir adayın numarası bozuk diye diğer aday otomatik seçilmez.
        names = runtime.messaging.name_matches(contacts, p["to"])
        if not names:
            runtime._session().pending_msg = None
            return (f"Rehberinde “{p['to']}” diye kayıtlı bir kişi yok; mesajı göndermedim. "
                    f"Önce “kişi ekle {p['to']} 05xx xxx xx xx” de ya da kayıtlı kişinin tam adını söyle.")
        valid = dict(runtime.messaging.contact_matches(contacts, p["to"]))
        if len(names) > 1:
            # Seçim kullanıcınındır ve açık olmalı: alıcı sorusu yeniden açılır, gövde korunur.
            listed = ", ".join(f"{person} ({runtime.messaging.mask_phone(valid[person])})"
                               if person in valid else f"{person} (numarası geçersiz)"
                               for person in names)
            p["stage"], p["to"] = "to", ""
            return (f"Rehberinde birkaç kişi eşleşiyor: {listed}. "
                    "Hangisine göndereyim? Kişinin tam adını yaz.")
        if names[0] not in valid:
            runtime._session().pending_msg = None
            return (f"Rehberindeki “{names[0]}” kaydının numarası geçerli değil; mesajı göndermedim. "
                    f"“kişi ekle {names[0]} 05xx xxx xx xx” ile numarayı düzeltebilirsin.")
        name, phone = names[0], valid[names[0]]
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
            p["to"], p["phone"] = name, phone
            return (f"{name} ({runtime.messaging.mask_phone(phone)}) kişisine şunu göndereyim mi: "
                    f"“{text}”? Evet ya da hayır de.")
    runtime._session().pending_msg = None

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
            # The result belongs to this request id, so "sus" mutes its audio and a
            # later re-offer of the same sentence is not announced twice.
            runtime.events.put(("say", result, owner.slug, {"turn_id": task_id}))

    try:
        runtime.threading.Thread(target=lambda: captured_context.run(work), daemon=True).start()
    except BaseException:
        runtime.requests_state.cancel(owner.slug, task_id)
        raise
    return f"{name} kişisine gönderiyorum: \"{text}\". Klavye ve fareye birkaç saniye dokunma."

def _macro_key(runtime, text: str) -> str:
    from modules import main_planner
    return main_planner._macro_key(runtime, text)

def _macro_run(runtime, cmd_lower: str) -> str | None:
    from modules import main_planner
    return main_planner._macro_run(runtime, cmd_lower)

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
