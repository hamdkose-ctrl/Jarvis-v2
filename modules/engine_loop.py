"""engine loop; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def _queued_audio(runtime, event):
    """Carry the accepted recording ID through transcription and command handoff."""
    _, aud_path, source, user, rid = (tuple(event) + (None,))[:5]
    owner = runtime.slugify(user or runtime.pc_profile().name)
    handed_off = False
    try:
        if not rid:
            raise ValueError("Ses kaydının istek kimliği yok; yeniden gönder.")
        with runtime.as_user(user), runtime.requests_state.activate(owner, rid, complete=False):
            runtime.emit("state", "thinking")
            runtime.requests_state.check()
            try:
                heard = runtime.llm_transcribe(aud_path).strip()
            except runtime.requests_state.Cancelled:
                raise
            except Exception as exc:
                runtime._record_failure('main.py:queued_audio')
                runtime.requests_state.check()
                runtime.emit("assistant", f"Sesi yazıya çeviremedim: {exc}")
                return
            runtime.requests_state.check()
            if heard:
                runtime.privacy.audit("ses kaydı", source)
                if runtime._tr_lower(heard).strip(" .!") in ("dur", "sus", "yeter", "stop"):
                    runtime.submit(heard, source, user)
                else:
                    runtime.requests_state.check()
                    runtime.events.put(("command", heard, source, user, rid))
                    handed_off = True
            else:
                runtime.emit("assistant", "Seni duyamadım, bir daha söyler misin?")
    except runtime.requests_state.Cancelled:
        pass
    except ValueError:
        runtime._record_failure('main.py:queued_audio')
        runtime._reject_queued_input()
    finally:
        if rid and not handed_off:
            runtime.requests_state.cancel(owner, rid)
        try:
            runtime.os.remove(aud_path)
        except (OSError, TypeError):
            pass
        runtime.emit("state", "idle")

def main(runtime, ui=None):
    from modules.engine_voice import VoiceSession
    voice_session = VoiceSession(runtime)
    pass  # Shared fields are held by the explicit engine context.
    runtime._ui = ui
    try:                                   # yazılı sohbet hafızası kalıcı geçmişten başlasın (bağlam kopmasın)
        runtime._llm.set_history_seed(lambda user: runtime._recent_turns(user, hours=2, limit=16))
    except Exception:
        runtime._record_failure('main.py:main')
    try:                                   # Mevcut kopya varsa çık; çalışan süreci kapatma.
        import instance
        instance.take_over()
    except Exception:
        runtime._record_failure('main.py:main')
        raise SystemExit(1)
    try:                                   # ses tanımaya özel adlar: kullanıcılar, kişiler, projeler
        runtime.voice.HINTS[:] = []                # yalnızca kullanıcının "Özel kelimeler"e yazdıkları kullanılır
    except Exception:
        runtime._record_failure('main.py:main')
    try:                                   # dışarıdan bırakılmış notlar: ~/.jarvis/ice_aktar/<kullanıcı>.json -> not defterine
        inbox = runtime.DATA_DIR / "ice_aktar"
        for f in (inbox.glob("*.json") if inbox.is_dir() else []):
            notes = runtime.json.loads(f.read_text(encoding="utf-8"))
            p_ = runtime._get_profile(f.stem)
            if p_.exists:
                for t in notes if isinstance(notes, list) else []:
                    if str(t).strip():
                        p_.add_note_item(str(t).strip())
                f.unlink()
                runtime.log.info("%d not içeri alındı: %s", len(notes), p_.name)
                from modules.deferred import start
                start(5.0, lambda n=len(notes), who=p_.name: runtime.emit(
                    "system", f"{n} not not defterine eklendi ({who})."), timer_factory=runtime.threading.Timer)
    except Exception:
        runtime._record_failure('main.py:main')
    runtime.threading.Thread(target=runtime._handoff_notice, daemon=True).start()
    runtime.threading.Thread(target=runtime._learning_notice, daemon=True).start()
    runtime.threading.Thread(target=runtime._google_health, daemon=True).start()
    try:                                   # son uygulanmış güncellemenin bildirimi (bir kez)
        import updater
        note = updater.pop_notice()
        if note:
            runtime.log.info(note)
            from modules.deferred import start
            start(4.0, lambda: runtime.emit("system", note), timer_factory=runtime.threading.Timer)
    except Exception:
        runtime._record_failure('main.py:main')
        pass
    if "--phone" in runtime.sys.argv:
        from modules.phone import PhoneServer
        print("Telefon erişimi açık. Telefonda (aynı Wi-Fi) şu adresi aç:", PhoneServer(runtime).start())
    if voice_session.live_on:
        from modules.engine_voice import prepare_live_tool
        runtime.live.set_speak_check(lambda: runtime.flags["speak"])   # susturma düğmesi canlı modun sesini de keser
        runtime.live.start(runtime._live_command, runtime.emit, runtime._live_prompt, mic_on=lambda: runtime.flags["mic"],
                   wants_sleep=lambda: runtime.flags["sleep"], stop_event=runtime.stop_event, vocab=runtime._live_vocab,
                   on_session_end=runtime._live_session_end,
                   prepare_tool=lambda fn, *args: prepare_live_tool(runtime, fn, *args))
    if voice_session.listening_enabled and not voice_session.manual_local_stt:
        runtime.threading.Thread(target=voice_session.listen_for_wake_word, daemon=True).start()
    runtime.threading.Thread(target=runtime._morning_brief, daemon=True).start()
    from modules import perf
    perf.start(runtime.stop_event)
    from modules import task_queue
    def queue_notice(owner,qid,state,job_id):
        for name in runtime.list_users():
            profile=runtime._get_profile(name)
            if profile.slug==owner:
                from modules import task_agents
                try:job=task_agents._load(owner,job_id)
                except ValueError:job=None
                label={'done':'Zamanlanan görevin tamamlandı.','blocked':'Zamanlanan görev durdu.','cancelled':'Zamanlanan görev iptal edildi.'}.get(state,'Zamanlanan görev güncellendi.')
                runtime._emit_for(profile,'assistant',label+'\n'+(task_agents.render_summary(job) if job else 'Görev sonuç kaydı oluşmadı; görev kuyruğu ile durumu kontrol edebilirsin.'))
                break
    task_queue.start(runtime.stop_event,queue_notice,
                     lambda:{runtime._get_profile(name).slug for name in runtime.list_users()})
    from modules import webhook_server
    def webhook_notice(owner,stored):
        for name in runtime.list_users():
            profile=runtime._get_profile(name)
            if profile.slug==owner:
                runtime._emit_for(profile,'assistant','WhatsApp: '+str(stored['messages'])+' yeni mesaj, '+str(stored['deliveries'])+' teslim kaydı. Gelen kutusu görevden okunabilir.')
                break
    webhook_server.start(runtime.stop_event,lambda:{runtime._get_profile(name).slug for name in runtime.list_users()},notify=webhook_notice)
    runtime._start_hang_watch()
    if ui is None:
        runtime.threading.Thread(target=voice_session.read_keyboard, daemon=True).start()
    if voice_session.listening_enabled and voice_session.manual_local_stt:
        from modules import local_stt
        local_stt.preload()      # inmiş modeli arka planda yükle; ilk Konuş basışı beklemesin (indirme/ağ yok)
        print('Yerel ses hazır: bir komut için Konuş düğmesine bas. Hey Jarvis bu denemede kapalı.')
    elif voice_session.listening_enabled:
        print(f"Jarvis hazır (model: {runtime.MODEL}). Ses için '{runtime.WAKE_WORD}' de ya da komutunu yazıp Enter'a bas. "
              "Çıkış: 'kapat'")
    else:
        print(f"Jarvis hazır (model: {runtime.MODEL}), mikrofon kapalı. Komutunu yazıp Enter'a bas. Çıkış: 'kapat'")
    runtime.log.info("Jarvis başladı (pid %d): model=%s dinleme=%s ses=%s canlı=%s", runtime.os.getpid(), runtime.MODEL, voice_session.listening_enabled, voice_session.speak_enabled, voice_session.live_on)
    runtime.threading.Thread(target=runtime._reminder_loop, daemon=True, name="hatirlatma").start()
    from modules import watcher
    runtime.threading.Thread(target=watcher.loop, args=(runtime,), daemon=True, name="klasor-izleme").start()
    import release_guard
    release_guard.ready("engine")
    try:
        while not runtime.stop_event.is_set():
            try:
                event = runtime.events.get(timeout=0.25)
            except runtime.queue.Empty:
                continue

            kind = event[0]
            runtime._cur_rid = None                 # önceki sorunun kimliği sonraki olaylara (hatırlatma vb.) taşınmasın
            if kind == "status":
                print(f"[{event[1]}]")
                continue
            if kind in ("say", "say_slow"):
                if len(event) > 2 and event[2] != runtime.pc_profile().slug:
                    continue
                runtime.pause_listening.set()
                try:
                    with runtime.audio_lock:
                        voice_session.speak(event[1], slow=(kind == "say_slow"))
                finally:
                    runtime.time.sleep(0.3)
                    runtime.pause_listening.clear()
                    runtime.emit("state", "idle")
                continue

            if kind == "listen" and not runtime.flags.get("mic", True):
                runtime.emit("state", "idle")
                continue

            if kind == "listen" and voice_session.live_on and runtime.live.get() is not None and runtime.live.enabled():   # arayüzde "Konuş" düğmesi: canlı oturumu hemen aç
                runtime.live.get().wake()
                continue

            if kind == "listen":      # arayüzde "Konuş" düğmesine basıldı: uyandırma adı beklemeden bir komut dinle
                runtime.pause_listening.set()
                runtime.emit("state", "listening")
                try:
                    with runtime.audio_lock:
                        heard = runtime.voice.listen(timeout=6, announce_fail=True, verbose=True, abort=runtime.mic_cancel,
                                                     local=voice_session.manual_local_stt,
                                                     on_captured=(lambda: runtime.emit("state", "thinking"))
                                                     if voice_session.manual_local_stt else None)
                except ValueError as exc:
                    runtime.emit('system', str(exc))
                    heard = None
                except Exception:
                    runtime._record_failure('main.py:main')
                    if voice_session.manual_local_stt:
                        runtime.emit('system', 'Yerel ses tanıma çalışmadı. Ses buluta gönderilmedi; yazıyla devam edebilirsin.')
                    heard = None
                if heard and heard.strip():
                    if not runtime.stop_event.is_set() and runtime.flags.get("mic", True):
                        voice_session.submit_voice(heard.strip())
                    else:
                        runtime.pause_listening.clear()
                        runtime.emit("state", "idle")
                else:
                    runtime.pause_listening.clear()
                    runtime.emit("state", "idle")
                continue

            if kind == "audio":
                _queued_audio(runtime, event)
                continue

            if kind == "photo":
                _, img_path, question, source, user = (tuple(event) + (None,))[:5]
                try:
                    with runtime.as_user(user):
                        runtime.emit("user", "📷 Fotoğraf" + (f": {question}" if question else ""), source)
                        try:
                            kept = runtime._keep_photo(img_path)
                            from modules import developer
                            development = developer.status(runtime.profile.slug)
                            if development['enabled'] and development['unlocked']:
                                out = developer.handle(runtime.profile.slug, '"' + kept + '" ' + (question or 'Bu görseli geliştirme referansı olarak incele.'), runtime.emit)
                            elif not question:
                                runtime._pending_photo[runtime.profile.slug] = {"path": kept, "t": runtime.time.time()}
                                out = ("Fotoğrafı aldım. Ne yapayım? “Analiz et”, “çevir”, “not olarak kaydet” de "
                                       "ya da fotoğrafla ilgili sorunu yaz.")
                            else:
                                runtime.emit("state", "thinking")
                                out = runtime._photo_action(kept, question)
                        except Exception as exc:
                            runtime._record_failure('main.py:main')
                            out = f"Fotoğrafı işleyemedim: {exc}"
                        out = runtime._finalize(out)
                        print("Jarvis:", out)
                        runtime.emit("assistant", out)
                        runtime.emit("state", "idle")
                except ValueError:
                    runtime._record_failure('main.py:queued_photo')
                    runtime._reject_queued_input()
                continue

            _, cmd, source, user, runtime._cur_rid = (tuple(event) + (None, None))[:5]
            runtime._cur_source = source
            if runtime.requests_state.is_cancelled(runtime.slugify(user or runtime.pc_profile().name), runtime._cur_rid):
                runtime._cur_source = ""
                runtime._cur_rid = None
                runtime.pause_listening.clear()
                runtime.emit("state", "idle")
                continue
            try:
                with runtime.as_user(user), runtime.requests_state.activate(runtime.slugify(user or runtime.pc_profile().name), runtime._cur_rid):
                    print(f"Sen ({source}): {cmd}")
                    runtime.log.info("İşlem kaydı: %s", 'main.py:main')
                    runtime.emit("user", cmd, source)

                    if runtime._tr_lower(cmd).strip(" .!") in ("kapat", "çık") and source != "telefon":
                        runtime.stop_event.set()      # telefondan Jarvis kapatılamaz
                        break

                    # Yanıt sırasında mikrofonun Jarvis'in sesini komut sanmasını önle
                    runtime.pause_listening.set()
                    runtime.emit("state", "thinking")
                    try:
                        t_cmd = runtime.time.time()
                        runtime._llm.take_route()   # önceki istekten kalan model izi bu cevaba karışmasın
                        try:
                            out = runtime.handle(cmd)
                            if not out and cmd == "PC rehberliği: otomatik kontrol":
                                continue  # unchanged screen: no repeated instruction or synthetic error
                        except runtime.requests_state.Cancelled as exc:
                            out = str(exc)
                        except (FileNotFoundError, ValueError) as exc:
                            out = str(exc)   # dosya yok / desteklenmeyen tür: nedeni olduğu gibi söyle
                        except Exception as exc:
                            runtime._record_failure('main.py:main')
                            print(f"[Hata] {type(exc).__name__}: {type(exc).__name__}")
                            runtime._record_failure('main.py:main')  # privacy-safe diagnostic is emitted at the catch boundary
                            try:
                                from modules import diagnose
                                out = diagnose.explain(exc)     # "internete ulaşamıyorum", "kota doldu" gibi açık sebep
                            except Exception:
                                runtime._record_failure('main.py:main')
                                out = "Şu anda yanıt veremiyorum, biraz sonra tekrar dener misiniz?"

                        try:
                            runtime.profile.log_agent(runtime.agents.classify(runtime._tr_lower(cmd)))
                        except Exception:
                            runtime._record_failure('main.py:main')
                        out = str(out).strip() if out else ""
                        runtime.log.info("Süre: cevap hazırlama %.1f sn", runtime.time.time() - t_cmd)
                        if not out:
                            out = "Bir yanıt alamadım."
                        out = runtime._finalize(out)
                        runtime._emit_route()

                        print("Jarvis:", out)
                        runtime.emit("assistant", out)
                        with runtime.audio_lock:
                            if source == "telefon":
                                runtime._session().speech_override = None  # Never reuse the phone's short reply on PC.
                            elif runtime._session().speech_override:
                                spoken, runtime._session().speech_override = runtime._session().speech_override, None
                                voice_session.speak(spoken)   # yabancı dildeki çeviriyi Türkçe sesle okumak anlamsız
                            elif runtime._session().last_doc is not None and out.startswith(runtime._session().last_doc[0][:50]):
                                # analiz/özet uzun: tamamını sesli okumak yerine ekrana yazılır, kısaca haber verilir
                                voice_session.speak(runtime._doc_ready_line(runtime._session().last_doc[2], out))
                            else:
                                voice_session.speak(runtime._short_for_speech(runtime.richtext.speakable(out)))
                    finally:
                        runtime._cur_source = ""
                        runtime._cur_rid = None
                        # Cevaptan sonra "Hey Jarvis" demeden devam: varsayılan KAPALI (TV/YouTube sesini komut sanıyordu)
                        from config import load_settings as _ls
                        if source == "ses" and _ls().get("followup_no_wake"):
                            voice_session.state["awake_until"] = runtime.time.time() + runtime.SESSION_SECONDS
                        runtime.time.sleep(0.3)   # hoparlörün son sesi mikrofona karışmasın
                        runtime.pause_listening.clear()
                        runtime.emit("state", "idle")
            except runtime.requests_state.Cancelled:
                runtime._cur_source = ""
                runtime._cur_rid = None
                runtime.pause_listening.clear()
                runtime.emit("state", "idle")
                continue
            except ValueError:
                runtime._record_failure('main.py:queued_command')
                runtime._reject_queued_input()
                continue

    except KeyboardInterrupt:
        runtime.stop_event.set()
    finally:
        runtime.stop_event.set()
        runtime._cur_source = ""
        runtime._cur_rid = None
        runtime.pause_listening.clear()
        runtime._prefetch_pool.shutdown(wait=False, cancel_futures=True)
        print("Jarvis kapatıldı.")
        runtime.log.info("Jarvis kapatıldı.")
        runtime.emit("quit")
