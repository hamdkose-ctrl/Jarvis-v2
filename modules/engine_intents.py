"""Execute classified intents with the caller's explicit EngineContext.

Fast paths and pending conversation handling remain in engine_commands.
This dispatcher does not classify again or create a new request identity.
"""
from __future__ import annotations


class ActionOutcome(str):
    """A domain result with an explicit success signal, retaining the string interface."""

    def __new__(cls, message: str, ok: bool):
        value = super().__new__(cls, message)
        value.ok = ok
        return value

def _remember(runtime, name: str) -> None:
    from modules import session_state
    session_state.remember_property(runtime._session(), name)


def _result_or_file(runtime, result: str, path: str, label: str, noun: str, fmt: object) -> str:
    """Core'un doğruladığı açık biçet istendiyse aynı turda kaydet; değilse çıktı önerisini bırak."""
    if fmt:
        saved = runtime.output.save_text_result(result, path, label, preferred=str(fmt))
        return f"{noun} hazırladım ve kaydettim: {saved}" if saved else result
    return result + "\n\nDosya olarak almak istersen çıktı al de."

def organize_preview_question(label: str, plan: list) -> str:
    """Bekleyen düzenlemenin tek önizleme cümlesi; onay metnini iki yüzey de buradan alır."""
    from modules import files as domain
    return (f"{label} klasöründeki {len(plan)} dosyayı klasörlere taşıyayım mı? ({domain.summary(plan)}) "
            "Kısayollar ve geçici dosyalar yerinde kalır, istersen “düzenlemeyi geri al” diyebilirsin. Evet mi?")


def organize_preview(runtime, folder: str) -> str:
    """Kanonical düzenleme önizlemesinin tek sahibi: planı doğrulanmış klasörde kurar.

    Anahtar `files.ORGANIZE_FOLDERS` kapalı kümesinden çözülür; klasör gerçek değilse hiçbir plan
    kurulmaz. Bu fonksiyon dosyaları taşımaz — taşıma yalnız kullanıcının kendi "evet" cevabıyla,
    `engine_commands` onay kolunda ve o anda tazelenen planla olur."""
    resolved = runtime.files.organize_folder(folder)
    if resolved is None:
        return "Düzenlenecek klasörü güvenli biçimde doğrulayamadım; işlem başlatılmadı."
    path, label = resolved
    plan = runtime.files.plan_organize(path)
    if not plan:
        runtime._session().pending_organize = None
        return f"{label} klasöründe düzenlenecek dosya yok."
    runtime._session().pending_organize = {"folder": path, "key": folder, "label": label, "plan": plan,
                                           "stamp": runtime.files.plan_stamp(plan)}
    return organize_preview_question(label, plan)


def dispatch(runtime, intent: str, a: dict, command: str, cmd_lower: str) -> str:
    from modules import app_actions, requests_state
    requests_state.check()
    match intent:
        case "document_export":
            from pathlib import Path
            from modules.brain_context import document_fingerprint
            document = runtime._session().last_doc
            if isinstance(document, (tuple, list)):
                document = tuple(document)
            if (a.get("document_owner") != runtime.profile.slug
                    or not a.get("document_digest")
                    or document_fingerprint(document) != a["document_digest"]):
                return "Kaydedilecek çıktı değişti; önce güncel çıktıyı seçelim."
            # Capture the validated tuple; the dialog cannot switch to a different result.
            text, source, label = document
            saved = runtime.output.save_text_result(text, source, label)
            if not saved:
                return "Kaydetme iptal edildi."
            if not Path(saved).is_file() or Path(saved).stat().st_size == 0:
                return "Kayıt dosyasını doğrulayamadım; kaydedildi demiyorum."
            return f"Çıktıyı kaydettim: {saved}"
        case "system_diagnose":
            from modules import diagnose
            return diagnose.summary(diagnose.run(speak_flag=False, user_slug=runtime.profile.slug))
        case "user_manage":
            from modules import user_command_domain
            return user_command_domain.user_manage(runtime, a)
        case "macro_teach":
            from modules import user_command_domain
            return user_command_domain.macro_teach(runtime, a)
        case "macro_manage":
            from modules import user_command_domain
            return user_command_domain.macro_manage(runtime, a)
        case "learning_manage":
            from modules import learning
            return learning.execute_typed(runtime.profile, a)
        case "git_publish":
            # Exact admin protocol is a domain safety boundary, not an intent recognizer.
            from modules import git_publish
            import updater
            if not git_publish.requested(command):
                return "GitHub yayını için açık ve tam ‘git yükle’ komutunu yaz."
            try:
                verified = updater.verify_sync()
                if verified.get("sync_state") in ("diverged", "unknown", "offline"):
                    return "GitHub'a yüklemedim: " + str(verified.get("sync_msg") or "durum güvenli değil")
                return git_publish.publish_worktree("kullanıcının onaylı GitHub yayın isteği")
            except Exception as exc:
                runtime._record_failure("modules.engine_intents:git_publish")
                return f"GitHub'a yükleyemedim: {exc}"
        case "system_update":
            # The check/install spelling is still an exact updater-owned protocol.  The model
            # proposes only the capability; it cannot turn a paraphrase into an installation.
            import updater
            action = updater.command_request(command)
            if action is None:
                return "Güncelleme için açık ve tam bir kontrol ya da kurulum komutu yaz."
            try:
                note = (updater.install_latest() if action == "install"
                        else updater.check(apply_now=False, force=True))
                if note:
                    return note + (" Jarvis'i kapatıp açınca devreye girer." if action == "install"
                                   else " Kurmak için açıkça ‘güncellemeyi kur’ de.")
                status = updater.status()
                if status["error"] and not status["sha"]:
                    return "Güncellemeye bakamadım: " + status["error"].split(" ", 2)[-1]
                return "Zaten en güncel sürümdesin." + (f" ({status['msg']})" if status["msg"] else "")
            except Exception as exc:
                runtime._record_failure("modules.engine_intents:system_update")
                return f"Güncellemeye bakamadım: {exc}"
        case "app_action":
            result=app_actions.voice(a, runtime._session(), runtime.profile, runtime.emit, command)
            if 'bu işlem kayıtlı değil' in str(result).casefold():
                from modules import goal_executor
                if not goal_executor.active():return goal_executor.run(runtime,command,initial_failure=str(result))
            return result
        case "app_open":
            # Target came from a typed clarify proposal and was re-validated by brain_core_map.
            from modules.command_execution import open_app
            return open_app(runtime, str(a.get("name") or ""))
        case "app_close":
            # Only opens the existing confirmation; close_application runs after approval.
            from modules.command_execution import request_close_app
            return request_close_app(runtime, str(a.get("name") or "")) or "Uygulama adı doğrulanamadı; kapatma işlemi başlatılmadı."
        case "file_action":
            from pathlib import Path
            from modules import nxapi
            operation = str(a.get("operation") or "")
            if operation == "list":
                rows = nxapi.list_files(limit=25).get("files", [])
                if not rows:
                    return "İzinli klasörlerinde dosya bulamadım."
                return "Dosyalar:\n" + "\n".join(
                    f"- {row.get('name') or Path(str(row.get('path') or '')).name} — {row.get('where') or row.get('folder') or ''}".rstrip(" —")
                    for row in rows
                )

            def exact(value):
                if not isinstance(value, str):
                    return None
                checked = nxapi.allowed(value)
                return checked if checked is not None and checked.is_file() else None

            if operation == "compare":
                raw_paths = a.get("paths")
                if not isinstance(raw_paths, (list, tuple)):
                    return "Karşılaştırılacak dosyalar doğrulanamadı."
                paths = [exact(value) for value in raw_paths]
                if any(value is None for value in paths):
                    return "Karşılaştırılacak dosyalardan biri artık erişilebilir değil."
                from modules import workbench
                return workbench.handle(runtime.profile.slug, [str(value) for value in paths], "karşılaştır")

            path = exact(a.get("path"))
            if path is None:
                return "Bu dosyaya artık erişemiyorum; işlem başlatılmadı."
            path_s = str(path)
            if operation == "summarize":
                result = runtime.docs.summarize(path_s)
                runtime._session().last_doc = (result, path_s, "ozet")
                return _result_or_file(runtime, result, path_s, "ozet", "Özeti", a.get("format"))
            if operation == "analyze":
                result = runtime.docs.insights(path_s, "")
                runtime._session().last_doc = (result, path_s, "analiz")
                return _result_or_file(runtime, result, path_s, "analiz", "Analizi", a.get("format"))
            if operation == "open":
                nxapi.open_path(path_s)
                return f"{path.name} dosyasını açtım."
            if operation == "locate":
                row = nxapi.describe_file(path_s) or {}
                where = row.get("where") or row.get("folder") or str(path.parent)
                return f"{path.name} — {where}"
            if operation == "translate":
                return runtime._translate_file(path_s, str(a.get("target") or ""))
            if operation == "convert":
                fmt = str(a.get("format") or "")
                saved = runtime.output.convert_document(path_s, fmt)
                return (f"Dosyayı {fmt.upper()} formatında kaydettim: {saved['path']}" + ('\n' + saved['note'] if saved['note'] else '')) if saved else "Dönüştürme iptal edildi."
            return "Bu dosya işlemi Core tarafından doğrulanmadı."

        case "file_mutate":
            # Natural-language parsing is already complete; only the typed Core payload reaches the executor.
            from modules import file_ops
            return file_ops.execute_typed(
                str(a.get("operation") or ""),
                owner=runtime.profile.slug,
                path=str(a.get("path") or ""),
                folder=str(a.get("folder") or ""),
                name=str(a.get("name") or ""),
                content=str(a.get("content") or ""),
            )

        case "file_organize":
            # Önizleme tek sahibinden: plan gerçek klasörde kurulur, burada HİÇBİR dosya taşınmaz.
            return organize_preview(runtime, str(a.get("folder") or ""))

        case "folder_analyze":
            # PR3C-4: kanonical anahtarlar burada gerçek klasör kimliğine çözülür; salt-okuma + KB
            # dizine ekleme + en çok bir model çağrısı yürütücünün kendi sınırlarıdır.
            from modules import folder_analysis
            return folder_analysis.analyze_turn(runtime.profile, a, command)

        case "watcher_manage":
            # Typed Brain/Core operation enters the domain adapter; no raw utterance is re-parsed.
            from modules import watcher
            return watcher.apply(runtime.profile.slug, a.get("watcher"))

        case "translate":
            text = str(a.get("text") or "").strip()
            target = str(a.get("target") or "").strip() or "Kaynak Türkçe ise İngilizce; diğer dillerde Türkçe"
            if not text:
                return "Çevirmemi istediğin metni sohbet alanına yaz."
            result = runtime.tr.translate(text, target)
            runtime._session().last_doc = (result, "", "ceviri")
            runtime._session().speech_override = "Çeviri hazır, sohbet ekranına yazdım."
            return result

        case "clarify":
            from modules import app_actions
            question = str(a.get('question') or 'Hangi uygulama, dosya veya iş üzerinde ne yapmamı istiyorsun?')
            return app_actions.ask_clarification(runtime._session(), command, question, runtime.profile)
        case "task":
            from modules import goal_executor
            return goal_executor.run(runtime,command)
        case "level_set":
            runtime._session().pending_level = None   # yeni açık istek eski "ses mi parlaklık mı?" sorusunu geçersiz kılar
            level = max(0, min(100, int(a["level"])))
            if a["property"] == "volume":
                if runtime.system_control.set_volume(level):
                    _remember(runtime, "volume")
                    return ActionOutcome(f"Ses seviyesini yüzde {level} yaptım.", True)
                return ActionOutcome("Ses seviyesini ayarlayamadım.", False)
            if runtime.system_control.set_brightness_verified(level):
                _remember(runtime, "brightness")
                return ActionOutcome(f"Ekran parlaklığını yüzde {level} olarak ayarladım.", True)
            return ActionOutcome("Ekran parlaklığını doğrulayamadım.", False)
        case "audio_action":
            # Eski ham "ses" dallarının tek sahibi: durum tersine çevrilmez, seviye adımı aynı owner'da.
            control = runtime.system_control
            action = str(a.get("action") or "")
            if action == "mute":
                if control.is_muted():
                    return ActionOutcome("Ses zaten kapalı (sessizde).", True)
                ok = bool(control.set_mute(True))
                return ActionOutcome("Sesi kapattım, bilgisayar sessizde." if ok else "Sesi kapatamadım.", ok)
            if action == "unmute":
                if not control.set_mute(False):
                    return ActionOutcome("Sesi açamadım.", False)
                lvl = control.current_volume()
                return ActionOutcome("Sessizi kaldırdım." + (f" Ses yüzde {lvl}." if lvl is not None else ""), True)
            if action == "open":
                if control.is_muted():
                    control.set_mute(False)   # sessizdeyken "sesi aç": önce sessizi kaldır, seviye aynı kalsın
                    lvl = control.current_volume()
                    return "Sessizi kaldırdım." + (f" Ses yüzde {lvl}." if lvl is not None else "")
                return runtime._volume_step(15, "arttırdım")
            if action == "volume_up":
                return runtime._volume_step(15, "arttırdım")
            if action == "lower":
                return runtime._volume_step(-10, "kıstım")
            return "Ses isteği Core tarafından doğrulanmadı."
        case "media_action":
            action = str(a.get("action") or "")
            if action not in {"next", "prev", "play_pause"}:
                return "Medya isteği Core tarafından doğrulanmadı."
            runtime.system_control.media_control(action)
            if action == "next":
                return "Sonraki şarkıya geçiliyor."
            if action == "prev":
                return "Önceki şarkıya dönülüyor."
            return "Medya oynatıcısı tetiklendi."
        case "visual_create":
            # Visual kind is a closed Brain proposal revalidated by Core; this opens only the source question.
            from modules import visual_chat
            return visual_chat.begin(runtime, command, str(a.get("kind") or ""))
        case "screen_capture":
            return runtime.desktop.screenshot()
        case "shutdown_request":
            runtime._session().pending_confirm = "shutdown"
            return "Bilgisayarı kapatmamı onaylıyor musun? Evet ya da hayır de."
        case "shutdown_cancel":
            if runtime.system_control.cancel_shutdown() is False:
                return ActionOutcome("Kapatma iptal komutu kabul edilmedi; iptal edildi demiyorum.", False)
            return ActionOutcome("Zamanlanmış bilgisayar kapatma işlemini iptal ettim.", True)
        case "fast_time":
            return "Saat " + runtime.time.strftime("%H:%M")
        case "fast_date":
            return runtime.time.strftime("Bugün %d.%m.%Y, ") + runtime._DAYS[runtime.time.localtime().tm_wday]
        case "fast_system_status":
            return runtime.desktop.system_status()
        case "fast_speech_stop":
            requests_state.cancel(runtime.profile.slug)
            runtime.voice.stop_speaking()
            return "Konuşmayı durdurdum."
        case "screen_analyze":
            if (msg := runtime.privacy.blocked("screen")):
                return msg
            image_path = runtime.os.path.join(runtime.tempfile.gettempdir(), "jarvis_screen.png")
            try:
                if runtime.vision.mode() == "camera":
                    image_path = runtime.vision.snapshot_path() or image_path
                else:
                    runtime.desktop.screenshot(image_path)
                question = str(a.get("question") or "").strip() or (
                    "Ekran görüntüsünü gerçekten görsel olarak analiz et. Önce aktif/öne çıkan pencere veya uygulamanın ne olduğunu, "
                    "sonra görünen ana içerikleri, okunabilen önemli metinleri, uyarı/hata varsa onu anlat. Jarvis'in kendi "
                    "panelindeki CPU, RAM, servis veya sistem durumu kutularını kullanıcı özellikle sistem durumunu sormadıysa "
                    "cevabın ana konusu yapma. Görüntüde ne olduğunu kısa ve somut Türkçe anlat; görüntüde olmayan bilgi uydurma."
                )
                return runtime.ask_image(image_path, question, runtime.profile.system_prompt())
            except Exception as e:
                runtime._record_failure('main.py:handle')
                from modules import failure_policy
                return "Ekran resmi işlenemedi: " + failure_policy.user_message(e)
            finally:
                try:
                    runtime.os.remove(image_path)
                except OSError:
                    pass
        case "reminder":
            from modules import main_planner
            return main_planner.reminder_core(runtime, a, command, cmd_lower)
        case "notes_read":
            if a.get("which") == "search":
                from modules import main_planner
                return main_planner.notes_search(runtime, str(a.get("query") or ""), a.get("window"))
            if a.get("which") == "summary":
                from modules import main_planner
                return main_planner.notes_summary(runtime, a.get("id"))
            if a.get("which") == "one":
                note = next((n for n in runtime.profile.data["items"] if str(n.get("id")) == str(a.get("id"))), None)
                return f"Notun: {note['text']}" if note else "Bu notu bulamadım."
            return runtime._notes_text()
        case "notes_write":
            note = next((n for n in runtime.profile.data["items"] if str(n.get("id")) == str(a.get("id"))), None)
            if note is None:
                return "Bu notu bulamadım."
            if a.get("operation") == "delete":
                old = str(note.get("text") or "")
                runtime.profile.delete_note_item(note["id"])
                return f"Notu sildim: {old}"
            if a.get("operation") == "update":
                note["text"] = str(a.get("text") or "")
                runtime.profile.save()
                return f"Düzelttim: {note['text']}"
            return "Bu not işlemi Core tarafından doğrulanmadı."
        case "weather":
            location = str(a.get("location") or "").strip()
            return runtime._weather(location or None)
        case "city_set":
            # BRAIN-03 dilim 1: hedef Brain'in önerisi, biçim Core'un hükmü; burası tek yazma yeri.
            city = str(a.get("location") or "")
            runtime.profile.set_pref("city", city)
            return f"Şehrini {city} olarak kaydettim; hava durumuna bu şehre göre bakacağım."
        case "city_reset":
            runtime.profile.data["prefs"].pop("city", None)
            runtime.profile.save()
            return "Kayıtlı şehrini sildim; artık bulunduğun konuma göre bakacağım."
        case "message_send":
            # BRAIN-03 dilim 2: alıcı/gövde Core'da doğrulandı; oturum ve gönderim onayı mevcut
            # `pending_msg` protokolünde kalır. Onay kullanıcının KENDİ cevabıdır; burada
            # gönderim başlamaz, gönderim onayı olmadan hiçbir efekt yürümez.
            runtime._session().pending_msg = {"to": str(a.get("recipient") or ""),
                                             "text": str(a.get("body") or ""), "stage": "to"}
            return runtime._message_step(None, "") or "Mesaj isteğini anlayamadım; alıcıyı ve metni söyler misin?"
        case "contacts_manage":
            # Kişi defteri yalnız ETKİN kullanıcının profilidir; numara Core'da normalleşti.
            contacts = runtime.profile.data.setdefault("contacts", {})
            if a.get("operation") == "list":
                return ("Kayıtlı kişiler: " + ", ".join(contacts) + "." if contacts
                        else "Kayıtlı kişi yok. \"kişi ekle Ahmet 0532 123 45 67\" diyebilirsin.")
            name, phone = str(a.get("name") or ""), str(a.get("phone") or "")
            if not name or not phone:
                return "Kişi kaydı doğrulanamadı; defter değişmedi."
            contacts[name] = phone
            runtime.profile.save()
            return f"{name} kişisini kaydettim. Artık WhatsApp mesajları daha güvenilir gider."
        case "finance_read":
            # Core yalnız biçim hükmü verdi; veri çekme ve biçimlendirme finans domain'inindir.
            from modules import finance
            return finance.answer_request(finance.request_from_slots(a)) or ""
        case "photo_action":
            # Operation and path are Core-validated; the domain executor only applies them.
            from modules import main_documents
            path = str(a.get("photo") or "")
            result = main_documents._photo_action(
                runtime, path, str(a.get("operation") or ""),
                question=str(a.get("question") or ""),
                target=str(a.get("target") or ""),
                note_text=str(a.get("note_text") or ""),
            )
            pending = getattr(runtime, "_pending_photo", {}).get(runtime.profile.slug)
            if isinstance(pending, dict) and str(pending.get("path") or "") == path:
                runtime._pending_photo.pop(runtime.profile.slug, None)
            return result
        case _:
            # Direct feedback about Jarvis' own response style is durable user intent,
            # not just another chat sentence. Capture it before building the system prompt
            # so the newly learned rule can affect this response and future responses.
            try:
                from modules import learning_feedback
                learning_feedback.capture(runtime.profile,command)
            except Exception:
                runtime._record_failure('modules/engine_intents.py:learning_feedback')
            if runtime.vision.mode():
                shot = None
                try:
                    shot = runtime.vision.snapshot_path()
                    if shot:
                        return runtime.ask_image(shot, command, runtime.profile.system_prompt())
                except Exception as e:
                    runtime._record_failure('main.py:handle')
                    from modules import failure_policy
                    return "Görüntüyü işleyemedim: " + failure_policy.user_message(e)
                finally:
                    if shot:
                        try:
                            runtime.os.remove(shot)
                        except OSError:
                            pass
            raw = runtime.chat(command, runtime._sys_prompt(command), user=runtime.profile.slug)
            from config import load_settings
            from modules import advisory_router
            return advisory_router.finalize(command, raw, settings=load_settings())
