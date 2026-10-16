"""Execute classified intents with the caller's explicit EngineContext.

Fast paths and pending conversation handling remain in engine_commands.
This dispatcher does not classify again or create a new request identity.
"""
from __future__ import annotations


def dispatch(runtime, intent: str, a: dict, command: str, cmd_lower: str) -> str:
    from modules import app_actions, requests_state
    requests_state.check()
    match intent:
        case "app_action":
            result=app_actions.voice(a, runtime._session(), runtime.profile, runtime.emit, command)
            if 'bu işlem kayıtlı değil' in str(result).casefold():
                from modules import goal_executor
                if not goal_executor.active():return goal_executor.run(runtime,command,initial_failure=str(result))
            return result
        case "code":
            import re
            if re.search(r'\b(?:test|dosya|kaydet|çalıştır|calistir|doğrula|dogrula)\w*',command.casefold()):
                from modules import goal_executor
                return goal_executor.run(runtime,command)
            return runtime.codegen.generate(a.get("task") or command, a.get("language", "python"))
        case "doc_summary":
            path, folder_reply = runtime._resolve_doc(a.get("path"), command)
            if folder_reply:
                return folder_reply
            if not path:
                if runtime.re.search(r"konuşma|sohbet|yazışma|söylediklerimiz", cmd_lower):
                    return runtime._summarize_chat()
                study_reply = runtime._study_answer(command, cmd_lower)
                if study_reply:
                    return study_reply
                return ("Hangi dosyayı kastettiğini bulamadım. Sohbet çubuğundaki ataçla dosyayı ekle ya da "
                        "Dosyalar sayfasında dosyayı seçip işlem düğmesine bas.")
            result = runtime.docs.summarize(path)
            runtime._session().last_doc = (result, path, "ozet")
            fmt = runtime._explicit_output_format(cmd_lower)
            if fmt:
                saved = runtime.output.save_text_result(result, path, "ozet", preferred=fmt)
                return f"Özeti hazırladım ve kaydettim: {saved}" if saved else result
            return result + "\n\nDosya olarak almak istersen çıktı al de."

        case "doc_insight":
            path, folder_reply = runtime._resolve_doc(a.get("path"), command)
            if folder_reply:
                return folder_reply
            if not path:
                if runtime.re.search(r"konuşma|sohbet|yazışma|söylediklerimiz", cmd_lower):
                    return runtime._summarize_chat()
                study_reply = runtime._study_answer(command, cmd_lower)
                if study_reply:
                    return study_reply
                return ("Hangi dosyayı kastettiğini bulamadım. Sohbet çubuğundaki ataçla dosyayı ekle ya da "
                        "Dosyalar sayfasında dosyayı seçip işlem düğmesine bas.")
            result = runtime.docs.insights(path, a.get("question", ""))
            runtime._session().last_doc = (result, path, "analiz")
            fmt = runtime._explicit_output_format(cmd_lower)
            if fmt:
                saved = runtime.output.save_text_result(result, path, "analiz", preferred=fmt)
                return f"Analizi hazırladım ve kaydettim: {saved}" if saved else result
            return result + "\n\nDosya olarak almak istersen çıktı al de."

        case "doc_convert":
            path, folder_reply = runtime._resolve_doc(a.get("path"), command)
            if folder_reply:
                return folder_reply
            if not path:
                if runtime.re.search(r"konuşma|sohbet|yazışma|söylediklerimiz", cmd_lower):
                    return runtime._summarize_chat()
                study_reply = runtime._study_answer(command, cmd_lower)
                if study_reply:
                    return study_reply
                return ("Hangi dosyayı kastettiğini bulamadım. Sohbet çubuğundaki ataçla dosyayı ekle ya da "
                        "Dosyalar sayfasında dosyayı seçip işlem düğmesine bas.")
            fmt = str(a.get("format") or "").lower().lstrip(".")
            fmt = {"excel": "xlsx", "word": "docx"}.get(fmt, fmt)
            if fmt not in {"xlsx", "docx", "pdf"}:
                return "Çıktı formatını Excel, Word veya PDF olarak belirt."
            saved = runtime.output.convert_document(path, fmt)
            return (f"Dosyayı {fmt.upper()} formatında kaydettim: {saved['path']}" + ('\n' + saved['note'] if saved['note'] else '')) if saved else "Dönüştürme iptal edildi."

        case "doc_translate":
            path, folder_reply = runtime._resolve_doc(a.get("path"), command)
            if folder_reply:
                return folder_reply
            if not path:
                if runtime.re.search(r"konuşma|sohbet|yazışma|söylediklerimiz", cmd_lower):
                    return runtime._summarize_chat()
                study_reply = runtime._study_answer(command, cmd_lower)
                if study_reply:
                    return study_reply
                return ("Hangi dosyayı kastettiğini bulamadım. Sohbet çubuğundaki ataçla dosyayı ekle ya da "
                        "Dosyalar sayfasında dosyayı seçip işlem düğmesine bas.")
            target = runtime.tr.target_from_command(command) or str(a.get("target") or "").strip()
            if not target:
                return "Komutta hedef dili belirt. Örneğin: 'Dosyayı İngilizceye çevir.'"
            return runtime._translate_file(path, target)

        case "translate":
            text = str(a.get("text") or "").strip()
            target = str(a.get("target") or "").strip() or "Kaynak Türkçe ise İngilizce; diğer dillerde Türkçe"
            if not text:
                return "Çevirmemi istediğin metni sohbet alanına yaz."
            result = runtime.tr.translate(text, target)
            runtime._session().last_doc = (result, "", "ceviri")
            runtime._session().speech_override = "Çeviri hazır, sohbet ekranına yazdım."
            return result

        case "open_app":
            name = str(a.get("name") or "").strip()
            if not name:
                return "Hangi uygulamayı açayım?"
            if runtime.re.fullmatch(r"(?:g?mail|e-?posta|eposta)\w*", runtime._tr_lower(name).replace("'", "")):
                if runtime.re.search(r"\b(?:iş|şirket|ofis)\b", cmd_lower):
                    from modules import outlook
                    return outlook.unread_mail()
                return runtime.google_api.unread_mail()   # "maili aç / kontrol et": uygulama değil, Gmail'e bak
            from modules.command_execution import open_app
            return open_app(runtime, name)
        case "clarify":
            question = str(a.get('question') or 'Hangi uygulama, dosya veya iş üzerinde ne yapmamı istiyorsun?')
            runtime._session().pending_request = {'command': command, 'question': question}
            return question
        case "task":
            from modules import brain_delegate, goal_executor
            # The specialist bridge is currently non-durable. Only replay-safe plans may enter it
            # automatically; effectful/approval work stays in the durable goal journal.
            try:
                delegated=brain_delegate.try_run(runtime,command)
            except requests_state.Cancelled:
                raise
            except Exception:
                delegated=None
            if delegated is not None:return delegated
            return goal_executor.run(runtime,command)
        case "desktop_task":
            from modules import desktop_agent
            target, goal = str(a.get('target') or '').strip(), str(a.get('goal') or '').strip()
            if not target or not goal or '|' in target or '|' in goal:
                return 'Hangi açık uygulamada ne yapmamı istiyorsun?'
            result = desktop_agent.handle(runtime.profile.slug, 'PC görevi: '+target+' | '+goal,
                runtime.emit, current=lambda: runtime.pc_profile().slug, source=runtime._cur_source)
            runtime._session().pending_desktop = True if desktop_agent.awaiting(runtime.profile.slug) else None
            return result
        case "open_url":
            url = str(a.get("url") or "").strip()
            if not url:
                return "Hangi adresi açayım?"
            if (msg := runtime.privacy.blocked("web")):
                return msg
            runtime.privacy.audit("site açma", url)
            if not runtime.re.match(r"https?://", url):
                url = "https://" + url.lstrip("/")
            runtime.system_control.open_new_tab(url)
            return f"{url} adresini yeni sekmede açıyorum."
        case "status":
            return runtime.desktop.system_status()
        case "screenshot":
            return runtime.desktop.screenshot()
        case "volume":
            return runtime.desktop.volume(int(a.get("delta", 2)))
        case "brightness":
            try:
                level = max(0, min(100, int(str(a.get("level")))))
            except ValueError:   # None -> "None" -> ValueError
                return "Parlaklığı yüzde kaç yapayım?"
            if runtime.system_control.set_brightness(level):
                return f"Ekran parlaklığını yüzde {level} olarak ayarladım."
            return "Ekran parlaklığını ayarlayamadım."
        case "media":
            if runtime.system_control.media_control(str(a.get("action") or "play_pause")):
                return "Medya komutunu uyguladım."
            return "Bu medya komutunu tanımadım."
        case "pc_control":
            action = a.get("action")
            if action == "shutdown":
                runtime._session().pending_confirm = "shutdown"
                return "Bilgisayarı kapatmamı onaylıyor musun? Evet ya da hayır de."
            if action == "cancel":
                runtime.system_control.cancel_shutdown()
                return "Zamanlanmış bilgisayar kapatma işlemini iptal ettim."
            return "Bu bilgisayar komutunu tanımadım."
        case "screen_analyze":
            if (msg := runtime.privacy.blocked("screen")):
                return msg
            # Analiz için geçici dosya kullanılır; kullanıcının kendi ekran görüntülerine dokunulmaz.
            image_path = runtime.os.path.join(runtime.tempfile.gettempdir(), "jarvis_screen.png")
            try:
                if runtime.vision.mode() == "camera":
                    image_path = runtime.vision.snapshot_path() or image_path   # kamera açıksa kameraya bak
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
                return f"Ekran resmi işlenirken hata oluştu: {e}"
            finally:
                try:
                    runtime.os.remove(image_path)
                except OSError:
                    pass
        case "feedback":
            runtime.profile.feedback(a.get("positive", True), command)
            return "Teşekkürler, not aldım."
        case "work":
            from modules import worktrack
            kind = str(a.get("kind") or "status")
            proj = str(a.get("project") or "").strip().upper() or None
            return worktrack.report(kind if kind in ("status", "reply", "dated", "priority", "weekly") else "status", proj)
        case "send_phone":
            from modules import filesend
            what = str(a.get("file") or "").strip()      # dosya söylenmediyse SOR: en son indirileni kendiliğinden gönderme
            if not what:
                return filesend.ASK
            return filesend.handle(f"{what} telefonuma gönder") or filesend.ASK
        case "close_app":
            name = str(a.get("name") or "").strip()
            if not name:
                return "Hangi uygulamayı kapatayım?"
            return runtime.system_control.close_application(name) or f"'{name}' adında açık bir uygulama bulamadım."
        case "handoff":
            from modules import handoff
            text = runtime._plain(str(a.get("text") or ""))
            where = "is" if str(a.get("where") or "").lower().startswith(("is", "iş")) else "ev"
            if not text:
                return "Neyi listeye ekleyeyim?"
            try:
                handoff.add(text, where, handoff.due(str(a.get("when") or "").lower()))
            except Exception as e:
                runtime._record_failure('main.py:handle')
                return handoff.explain_error(e)
            return f"{handoff.NAME[where].capitalize()} listesine ekledim: {text}"
        case "note":
            text = runtime._plain(str(a.get("text") or ""))
            if not text:
                return "Neyi not edeyim?"
            runtime._add_note(text)
            return f"Not aldım: {text}"
        case "mail":
            which = str(a.get("which") or "hepsi").lower()
            from modules import outlook
            if which.startswith("is") or which.startswith("iş") or "outlook" in which:
                return outlook.unread_mail()
            if which == "gmail" or not outlook.installed():
                return runtime.google_api.unread_mail()
            return "Gmail: " + runtime.google_api.unread_mail() + " İş (Outlook): " + outlook.unread_mail()
        case "weather":
            location = str(a.get("location") or "").strip()
            return runtime._weather(location or None)
        case _:
            if runtime.vision.mode():   # paylaşım açık: soruyu o anki görüntüyle birlikte sor
                shot = None
                try:
                    shot = runtime.vision.snapshot_path()
                    if shot:
                        return runtime.ask_image(shot, command, runtime.profile.system_prompt())
                except Exception as e:
                    runtime._record_failure('main.py:handle')
                    return f"Görüntüyü işleyemedim: {e}"
                finally:
                    if shot:
                        try:
                            runtime.os.remove(shot)
                        except OSError:
                            pass
            return runtime.chat(command, runtime._sys_prompt(command), user=runtime.profile.slug)

