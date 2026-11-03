"""Execute classified intents with the caller's explicit EngineContext.

Fast paths and pending conversation handling remain in engine_commands.
This dispatcher does not classify again or create a new request identity.
"""
from __future__ import annotations



def _remember(runtime, name: str) -> None:
    from modules import session_state
    session_state.remember_property(runtime._session(), name)


def _result_or_file(runtime, result: str, path: str, label: str, noun: str, fmt: object) -> str:
    """Core'un doğruladığı açık biçet istendiyse aynı turda kaydet; değilse çıktı önerisini bırak."""
    if fmt:
        saved = runtime.output.save_text_result(result, path, label, preferred=str(fmt))
        return f"{noun} hazırladım ve kaydettim: {saved}" if saved else result
    return result + "\n\nDosya olarak almak istersen çıktı al de."

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
                    return f"Ses seviyesini yüzde {level} yaptım."
                return "Ses seviyesini ayarlayamadım."
            if runtime.system_control.set_brightness_verified(level):
                _remember(runtime, "brightness")
                return f"Ekran parlaklığını yüzde {level} olarak ayarladım."
            return "Ekran parlaklığını doğrulayamadım."
        case "audio_action":
            # Eski ham "ses" dallarının tek sahibi: durum tersine çevrilmez, seviye adımı aynı owner'da.
            control = runtime.system_control
            action = str(a.get("action") or "")
            if action == "mute":
                if control.is_muted():
                    return "Ses zaten kapalı (sessizde)."
                return "Sesi kapattım, bilgisayar sessizde." if control.set_mute(True) else "Sesi kapatamadım."
            if action == "unmute":
                if not control.set_mute(False):
                    return "Sesi açamadım."
                lvl = control.current_volume()
                return "Sessizi kaldırdım." + (f" Ses yüzde {lvl}." if lvl is not None else "")
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
        case "screen_capture":
            return runtime.desktop.screenshot()
        case "shutdown_request":
            runtime._session().pending_confirm = "shutdown"
            return "Bilgisayarı kapatmamı onaylıyor musun? Evet ya da hayır de."
        case "shutdown_cancel":
            if runtime.system_control.cancel_shutdown() is False:
                return "Kapatma iptal komutu kabul edilmedi; iptal edildi demiyorum."
            return "Zamanlanmış bilgisayar kapatma işlemini iptal ettim."
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