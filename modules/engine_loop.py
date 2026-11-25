"""engine loop; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def _speech_blocks_mic(voice_session):
    """One speaker proof for manual listening and engine idle claims.

    A failed physical stop is still potentially audible even after the output
    queue became empty. Trust the already-installed VoiceSession gate when it
    exists; standalone engine test sessions may expose only the lane.
    """
    gate = getattr(voice_session, "speech_blocks_mic", None)
    if callable(gate):
        return bool(gate())
    lane = getattr(voice_session, "voice_lane", None)
    return bool(lane and (lane.is_busy()
                         or (callable(getattr(lane, "stop_unconfirmed", None))
                             and lane.stop_unconfirmed())))


def _speak_isolated(runtime, voice_session, text, **kwargs):
    """Quarantine TTS/device errors without cancelling Core or background work.

    Do not signal stop_event, cancel a GoalState or start a fallback voice.
    Unproven physical audio remains subject to the existing mic handoff gate.
    """
    if not runtime.flags.get("speak", True):
        return False
    try:
        voice_session.speak(text, **kwargs)
        return True
    except Exception:
        runtime._record_failure("modules/engine_loop.py:tts_isolation")
        voice_session.speak_enabled = False
        runtime.flags["speak"] = False
        try:
            from modules import voice_runtime
            voice_runtime.block_legacy_on_fault()
            voice_runtime.interrupt_active()  # speech only; never Core/task cancel
        except Exception:
            runtime._record_failure("modules/engine_loop.py:tts_stop")
        try:
            runtime.emit("system", "Ses çıkışı hata nedeniyle devre dışı. "
                         "Yazılı yanıtlar ve arka plan görevleri devam ediyor.")
        except Exception:
            runtime._record_failure("modules/engine_loop.py:tts_notice")
        return False


def _emit_idle_if_silent(runtime, voice_session):
    """Emit truthful idle only after the single speaker's physical stop proof."""
    try:
        silent = not _speech_blocks_mic(voice_session)
    except Exception:
        runtime._record_failure("modules/engine_loop.py:tts_idle_probe")
        # A broken audio-driver status query is not proof of silence.
        return
    if silent:
        runtime.emit("state", "idle")


def _prepare_manual_listen(runtime, voice_session):
    """Keep the engine alive, but fail closed if physical speech stop is unknown."""
    try:
        if not _speech_blocks_mic(voice_session):
            return True
        from modules import voice_runtime
        if voice_runtime.handoff_to_listen():
            return True
    except Exception:
        # This status probe runs outside the queued microphone capture's
        # exception handler. A broken TTS driver must not escape the engine loop.
        runtime._record_failure("modules/engine_loop.py:tts_mic_handoff")
        runtime.flags["speak"] = False
        voice_session.speak_enabled = False
        try:
            from modules import voice_runtime
            voice_runtime.block_legacy_on_fault()
            voice_runtime.interrupt_active()
        except Exception:
            runtime._record_failure("modules/engine_loop.py:tts_mic_stop")
    runtime.emit("system",
                 "Jarvis sesi henüz doğrulanmış biçimde durmadı; "
                 "mikrofon açılmadı. Yazılı yanıtlar devam ediyor.")
    return False


def _capture_manual_voice(runtime, voice_session):
    """Check the real speaker under the mic lock immediately before capture.

    A notice may start playing after the preliminary UI handoff. Never start a
    second physical stream over unconfirmed playback; the caller releases its
    pause claim and preserves the written/UI error through the existing path.
    """
    with runtime.audio_lock:
        if not runtime.flags.get("mic", True) or runtime.stop_event.is_set():
            raise ValueError("Mikrofon kapalı; ses kaydı başlatılmadı.")
        if _speech_blocks_mic(voice_session):
            raise ValueError("Jarvis konuşurken mikrofon açılmadı; sesi tekrar durdur.")
        runtime.emit("state", "listening")
        # Foreground push-to-talk is not a background listener: a queued notice waits
        # for this capture instead of cutting the user's own recording. Only the real
        # cancel signals abort it, so the one-physical-lock seal stays intact.
        return runtime.voice.capture(
            timeout=6, verbose=True, abort=runtime.mic_cancel,
            on_captured=(lambda: runtime.emit("state", "thinking"))
            if voice_session.manual_local_stt else None,
        )


def _deliver_verified_canonical_goal(runtime, owner, job_id, message):
    """Existing owner event sink for an already-reserved canonical event.

    Neither an arbitrary worker nor a model may choose the event identity,
    result authority or destination owner. Only the durable Core/ExecutionRecord
    adapter decides which question/completion may be sent.
    """
    from modules import canonical_goal_flow, event_channels
    kind, event_id, title = canonical_goal_flow.delivery_metadata(owner, job_id)
    result = event_channels.deliver(
        runtime, owner,
        {'source': 'canonical_goal', 'kind': kind,
         'payload': {'text': message, 'job_id': job_id, 'event_id': event_id}},
        title=title,
    )
    if result is None:
        raise PermissionError('Canonical result owner is not registered.')
    if canonical_goal_flow._accepted_user_channel(result) is None:
        raise RuntimeError('Canonical event was not accepted by an owner-facing channel.')
    return result


ASK_TEMPLATES = {
    "window": "Hangi pencerede yapayım?",
    "path": "Hangi klasör/dosya?",
    "text": "Ne yazayım?",
    "query": "Ekrandaki hangi yazıya basayım?",
    "name": "Dosya adı ne olsun?",
}


def _ask_for_slots(karar):
    """Eksik bilgiyi uydurmak yerine tek soru sor (yapmaz)."""
    missing = (karar.get("missing") or [None])[0]
    return ASK_TEMPLATES.get(missing, "Eksik bilgi var; biraz daha açık söyler misin?")


def _dispatch_fast(runtime, intent, args, cmd):
    from modules import engine_intents
    return engine_intents.dispatch(runtime, intent, args, cmd, cmd.casefold())


def _fast_command_turn(runtime, cmd):
    """Kapalı sözlükteki komutu model çağırmadan mevcut sahibinde çalıştırır.

    Canlı ölçüm: "saat kaç" gibi bir soru bile anlama modeline gidiyordu; hızlı
    yol eşleşmezse komut eskisi gibi Brain/Core yolundan gider. Burada karar,
    izin veya yeni bir etki sahibi yok: yalnız `engine_intents.dispatch` çağrılır.
    """
    from modules import engine_intents, fast_commands
    eslesme = fast_commands.resolve(cmd)
    if eslesme is None:
        # Serbest cümle: kalıp tutmadıysa **yetenek beyni** dener (katalog eşleşmesi).
        # Emin değilse iş yapmaz; eksik bilgi varsa tek soru sorar.
        from modules import capability_brain
        karar = capability_brain.resolve(cmd)
        if karar["status"] == "ok":
            runtime.log.info("hızlı yol: intent=%s (katalog)", karar["intent"])
            return _dispatch_fast(runtime, karar["intent"], karar["args"], cmd)
        if karar["status"] == "need":
            return _ask_for_slots(karar)
        # Selamlama/nezaket ("merhaba", "teşekkürler") bilgi sorusu değil: model
        # çağırmadan cevaplanır. Canlı kusur (23 Kasım): tüm sağlayıcılar düşükken
        # "merhaba" cevapsız kaldı.
        sohbet = fast_commands.chitchat(cmd)
        if sohbet:
            runtime.log.info("hızlı yol: intent=chitchat")
            return sohbet
        # Salt hesap ("25 çarpı 4") model istemez: yan etkisiz, yerel.
        hesap = fast_commands.compute(cmd)
        if hesap:
            runtime.log.info("hızlı yol: intent=fast_calc")
            return hesap
        return None
    intent, args = eslesme
    baslangic = runtime.time.time()
    try:
        metin = engine_intents.dispatch(runtime, intent, args, cmd, cmd.casefold())
    except Exception:
        # Hata yutulmaz: tur Brain/Core yolundan yeniden denenir.
        runtime._record_failure("modules/engine_loop.py:fast_command")
        return None
    if not metin:
        return None
    runtime.log.info("hızlı yol: intent=%s süre=%.0f ms", intent,
                     (runtime.time.time() - baslangic) * 1000)
    # `explicit_read` düz metin taşır; demet dönerse ekrana/sese ham tuple sızar
    # (canlı hata 11:39: "('Chrome penceresi açık...', None, None)").
    return str(metin)


def _log_core_feedback(runtime, entry):
    """Log the real Core outcome (failed/cancelled) that handoff correlated before re-raising.

    Returns that same BrainFeedback (or None) so the caller can ground its
    failure presentation in it instead of re-classifying the exception.
    """
    if entry is None:
        return None
    from modules import brain_entry, core_brain_adapter
    row = brain_entry.last_feedback()
    if row is not None and row.request_id == entry.request_id:
        runtime.log.info("Brain handoff: rid=%s stage=%s feedback=%s reason=%s",
                         entry.request_id, entry.stage, row.result_status, row.reason_code or "-")
        return row
    return None


def _mic_stays_listening(runtime) -> bool:
    """Tur sürerken mikrofon açık kalsın mı (varsayılan: evet).

    Kullanıcı Jarvis arkada çalışırken konuşmaya devam edebilmeli. Jarvis kendi
    sesini duymasın diye çalma sırasında dinleyici `speech_blocks_mic()` ile ayrıca
    duruyor, yani bu ayar yalnız "düşünürken/çalışırken sağır kalma" davranışını
    değiştirir. Ayar okunamazsa eski davranışa değil, kullanıcının istediği
    davranışa düşülür (mikrofon açık).
    """
    try:
        from config import load_settings
        return bool(load_settings().get("voice_mic_while_working", True))
    except Exception:
        runtime._record_failure("modules/engine_loop.py:mic_setting")
        return True


def _turn_with_listening_foreground(voice_session, invoke):
    """Run one engine turn without letting a provider wait close the microphone.

    `invoke()` may be the primary semantic Brain proposal or its later Core
    handoff. The owner identity lock, request fence, cancel checks and speech
    window remain exactly the caller's. The seam only tells `model_wait` that
    while THIS thread awaits a bounded provider answer, the interaction layer
    may take the microphone back. It does not transfer a long job to Scheduler.
    """
    hook = getattr(voice_session, "mic_open_during_model_wait", None)
    if hook is None:
        return invoke()           # a session without the seam runs exactly as before
    from modules import model_wait
    with model_wait.foreground(hook):
        return invoke()


def _queued_audio(runtime, event, voice_session=None):
    """Carry the accepted recording ID through transcription and command handoff."""
    _, aud_path, source, user, rid = (tuple(event) + (None,))[:5]
    owner = runtime.slugify(user or runtime.pc_profile().name)
    handed_off = False
    try:
        if not rid:
            raise ValueError("Ses kaydının istek kimliği yok; yeniden gönder.")
        with runtime.as_user(user), runtime.requests_state.activate(owner, rid, complete=False, foreground=True):
            runtime.emit("state", "thinking")
            runtime.requests_state.check()
            try:
                heard = runtime.llm_transcribe(aud_path).strip()
            except runtime.requests_state.Cancelled:
                raise
            except Exception as exc:
                runtime._record_failure('main.py:queued_audio')
                runtime.requests_state.check()
                from modules import failure_policy
                runtime.emit("assistant", "Sesi yazıya çeviremedim: " + failure_policy.user_message(exc))
                return
            runtime.requests_state.check()
            if heard:
                runtime.privacy.audit("ses kaydı", source)
                if runtime._tr_lower(heard).strip(" .!") in ("dur", "sus", "yeter", "stop"):
                    runtime.submit(heard, source, user, rid=rid)
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
        if voice_session is None:
            # Standalone helper callers do not have an active voice session.
            runtime.emit("state", "idle")
        else:
            _emit_idle_if_silent(runtime, voice_session)

def main(runtime, ui=None):
    from modules.engine_voice import VoiceSession
    voice_session = VoiceSession(runtime)
    pass  # Shared fields are held by the explicit engine context.
    runtime._ui = ui
    # Edge bağlantısı uygulama açılışında tazelenmeye başlar: ilk turda da sıcak
    # olsun (canlı 17:55'te ilk tur 'voice_warm miss' ile soğuk yola düşmüştü).
    try:
        if runtime.flags.get("speak", True):
            from modules import voice_edge_warm
            voice_edge_warm.start_keeper()
    except Exception:
        runtime._record_failure("modules/engine_loop.py:keeper_start")
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
    if voice_session.listening_enabled and not voice_session.manual_local_stt:
        runtime.threading.Thread(target=voice_session.listen_for_wake_word, daemon=True).start()
    runtime.threading.Thread(target=runtime._morning_brief, daemon=True).start()
    from modules import perf
    perf.start(runtime.stop_event)
    from modules import task_queue
    from modules import event_channels
    def queue_notice(owner,qid,state,job_id):
        from modules import task_agents
        try:job=task_agents._load(owner,job_id)
        except ValueError:job=None
        label={'done':'Zamanlanan görevin tamamlandı.','blocked':'Zamanlanan görev durdu.','cancelled':'Zamanlanan görev iptal edildi.'}.get(state,'Zamanlanan görev güncellendi.')
        text=label+'\n'+(task_agents.render_summary(job) if job else 'Görev sonuç kaydı oluşmadı; görev kuyruğu ile durumu kontrol edebilirsin.')
        event_channels.deliver(runtime,owner,{'source':'task_queue','kind':state,'payload':{'text':text,'queue_id':qid,'job_id':job_id}},
                               title='Jarvis zamanlanmış görev')
    def source_notice(owner,event_id,message):
        event_channels.deliver(runtime,owner,{'source':'source_watch','kind':'source_update','payload':{'text':message,'event_id':event_id}},
                               title='Jarvis kaynak takibi')
    def canonical_profile(owner):
        # An authenticated, registered profile is required for background
        # read-only work. Never borrow the mutable foreground runtime.profile.
        name = next((name for name in runtime.list_users()
                     if runtime.slugify(name) == owner), None)
        if name is None:
            raise PermissionError('Canonical Scheduler owner is not registered.')
        profile = runtime._get_profile(name)
        if profile.slug != owner or not profile.exists:
            raise PermissionError('Canonical Scheduler owner identity changed.')
        return profile

    def canonical_result_notice(owner, job_id):
        from modules import canonical_goal_flow
        canonical_goal_flow.complete_and_deliver(
            owner, job_id,
            lambda verified_owner, verified_job, text: _deliver_verified_canonical_goal(
                runtime, verified_owner, verified_job, text,
            ),
        )

    def canonical_plan_notice(owner, job_id, outcome):
        # No worker chooses its own UI recipient or arbitrary spoken content.
        # The engine delivers only one verified owner-bound Scheduler outcome.
        from modules import canonical_planning_queue
        current = canonical_planning_queue.status(owner, job_id)
        if current is None:
            return
        text = (f"Arka plan planı kabul edildi. Hedef {job_id} yürütülüyor."
                if outcome == "planned" else current)
        event_channels.deliver(
            runtime, owner,
            {'source': 'canonical_plan', 'kind': outcome,
             'payload': {'text': text, 'job_id': job_id,
                         'event_id': 'canonical-plan:' + job_id}},
            title='Jarvis arka plan planlaması')

    task_queue.start(runtime.stop_event,queue_notice,
                     lambda:{runtime._get_profile(name).slug for name in runtime.list_users()},
                     source_notify=source_notice,
                     canonical_profile_resolver=canonical_profile,
                     canonical_result_notify=canonical_result_notice,
                     canonical_plan_notify=canonical_plan_notice)
    from modules import webhook_server
    def webhook_event(owner,event):
        event_channels.deliver(runtime,owner,event,title='Jarvis olay')
    webhook_server.start(runtime.stop_event,lambda:{runtime._get_profile(name).slug for name in runtime.list_users()},event_notify=webhook_event)
    runtime._start_hang_watch()
    if ui is None:
        runtime.threading.Thread(target=voice_session.read_keyboard, daemon=True).start()
    if voice_session.listening_enabled and voice_session.manual_local_stt:
        from modules import local_stt
        local_stt.preload()
        print('Yerel ses hazır: bir komut için Konuş düğmesine bas. Hey Jarvis bu denemede kapalı.')
    elif voice_session.listening_enabled:
        print(f"Jarvis hazır (model: {runtime.MODEL}). Ses için '{runtime.WAKE_WORD}' de ya da komutunu yazıp Enter'a bas. "
              "Çıkış: \"Jarvis'i kapat\"")
    else:
        print(f"Jarvis hazır (model: {runtime.MODEL}), mikrofon kapalı. Komutunu yazıp Enter'a bas. Çıkış: \"Jarvis'i kapat\"")
    runtime.log.info("Jarvis başladı (pid %d): model=%s dinleme=%s ses=%s", runtime.os.getpid(), runtime.MODEL, voice_session.listening_enabled, voice_session.speak_enabled)
    runtime.threading.Thread(target=runtime._reminder_loop, daemon=True, name="hatirlatma").start()
    from modules import watcher
    runtime.threading.Thread(target=watcher.loop, args=(runtime,), daemon=True, name="klasor-izleme").start()
    # Otonomi saati: ana anahtar kapalıysa hiçbir şey yapmaz; yalnız verilen işleri
    # zamanı gelince çalıştırır (kendi kendine iş uydurmaz).
    from modules import pc_autonomy_queue
    runtime.threading.Thread(target=pc_autonomy_queue.tick_loop, args=(runtime.stop_event,),
                             daemon=True, name="otonomi-saati").start()
    import release_guard
    release_guard.ready("engine")
    try:
        while not runtime.stop_event.is_set():
            try:
                event = runtime.events.get(timeout=0.25)
            except runtime.queue.Empty:
                continue

            kind = event[0]
            runtime._cur_rid = None
            if kind == "status":
                print(f"[{event[1]}]")
                continue
            if kind in ("say", "say_slow"):
                if len(event) > 2 and event[2] != runtime.pc_profile().slug:
                    continue
                # A notice may name the result it announces: ('say', text, owner,
                # {event_id/goal_id/state_version/...}). Text without an owner is a
                # foreground answer of the current turn and stays identity-free.
                identity = event[3] if len(event) > 3 else None
                runtime.pause_listening.set()
                try:
                    with runtime.audio_lock:
                        _speak_isolated(runtime, voice_session, event[1], slow=(kind == "say_slow"),
                                            shown=len(event) > 2, identity=identity)
                finally:
                    runtime.time.sleep(0.3)
                    runtime.pause_listening.clear()
                    # The same device proof protects every idle claim and
                    # manual microphone handoff, not just queued notifications.
                    _emit_idle_if_silent(runtime, voice_session)
                continue

            if kind == "listen" and not runtime.flags.get("mic", True):
                _emit_idle_if_silent(runtime, voice_session)
                continue

            if kind == "listen":
                # A finished queue is not evidence of an audible output stop.
                # Both a live speaker and an unconfirmed stop require a verified
                # physical handoff before capture can own the device.
                if not _prepare_manual_listen(runtime, voice_session):
                    continue


            if kind == "listen":
                runtime.pause_listening.set()
                try:
                    raw = _capture_manual_voice(runtime, voice_session)
                    # The STT wait is not a reason to keep the only capture device:
                    # the stream is closed, so the lock is released before the text.
                    heard = runtime.voice.recognize(raw or b"", announce_fail=True,
                                                    local=voice_session.manual_local_stt)
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
                        _emit_idle_if_silent(runtime, voice_session)
                else:
                    runtime.pause_listening.clear()
                    _emit_idle_if_silent(runtime, voice_session)
                continue

            if kind == "audio":
                _queued_audio(runtime, event, voice_session)
                continue

            if kind == "photo":
                _, img_path, question, source, user, rid = (tuple(event) + (None, None))[:6]
                owner = runtime.slugify(user or runtime.pc_profile().name)
                runtime._cur_source = source
                runtime._cur_rid = rid
                if not rid or runtime.requests_state.is_cancelled(owner, rid):
                    runtime._reject_queued_input()
                    continue
                try:
                    with runtime.as_user(user), runtime.requests_state.activate(owner, rid, foreground=True):
                        from modules import brain_entry, core_brain_adapter
                        runtime.emit("user", "📷 Fotoğraf" + (f": {question}" if question else ""), source)
                        entry = None
                        awaiting_question = False
                        feedback = None
                        try:
                            kept = runtime._keep_photo(img_path)
                            artifact = brain_entry.photo_artifact(owner=owner, request_id=rid, path=kept)
                            entry = brain_entry.prepare(
                                runtime, owner=owner, request_id=rid,
                                text=question or "Fotoğraf", source=source, artifact=artifact,
                                model_understanding=bool(question),
                            )
                            clarification = brain_entry.clarification(entry)
                            if clarification is not None:
                                out = clarification
                            else:
                                from modules import developer
                                development = developer.status(runtime.profile.slug)
                                with brain_entry.bind(entry):
                                    if development['enabled'] and development['unlocked']:
                                        out = developer.handle(runtime.profile.slug, '"' + kept + '" ' + (question or 'Bu görseli geliştirme referansı olarak incele.'), runtime.emit)
                                    elif not question:
                                        awaiting_question = True
                                        runtime._pending_photo[runtime.profile.slug] = {
                                            "path": kept,
                                            "t": runtime.time.time(),
                                            "origin_request_id": rid,
                                        }
                                        out = ("Fotoğrafı aldım. Ne yapayım? “Analiz et”, “çevir”, “not olarak kaydet” de "
                                               "ya da fotoğrafla ilgili sorunu yaz.")
                                    else:
                                        runtime.emit("state", "thinking")
                                        from modules import brain_core_wire
                                        wire = core_brain_adapter.handoff_json(
                                            runtime, entry.to_handoff_json(), runtime.handle, question,
                                        )
                                        result = brain_core_wire.decode_result(
                                            wire, owner=owner, request_id=rid,
                                        )
                                        out, feedback = result["output"], result["feedback"]
                            fb = feedback or brain_entry.photo_feedback(entry, awaiting_question=awaiting_question)
                            fb_status = fb["result_status"] if isinstance(fb, dict) else fb.result_status
                            fb_reason = fb.get("reason_code") if isinstance(fb, dict) else fb.reason_code
                            runtime.log.info("Brain handoff: rid=%s stage=%s feedback=%s reason=%s", rid, entry.stage, fb_status, fb_reason or "-")
                        except Exception as exc:
                            runtime._record_failure('main.py:main')
                            from modules import failure_policy
                            message = failure_policy.user_message(exc)
                            if entry is not None:
                                fb = brain_entry.last_feedback()
                                if fb is None or fb.request_id != entry.request_id:
                                    fb = brain_entry.photo_feedback(entry, error=exc)
                                runtime.log.info("Brain handoff: rid=%s stage=%s feedback=%s reason=%s", rid, entry.stage, fb.result_status, fb.reason_code or "-")
                                from modules import brain_failure_synthesis
                                message = brain_failure_synthesis.synthesize(fb, exc)
                            out = "Fotoğrafı işleyemedim: " + message
                        out = runtime._finalize(out)
                        print("Jarvis:", out)
                        runtime.emit("assistant", out)
                        _emit_idle_if_silent(runtime, voice_session)
                except ValueError:
                    runtime._record_failure('main.py:queued_photo')
                    runtime._reject_queued_input()
                finally:
                    runtime._cur_source = ""
                    runtime._cur_rid = None
                continue

            _, cmd, source, user, runtime._cur_rid = (tuple(event) + (None, None))[:5]
            runtime._cur_source = source
            owner = runtime.slugify(user or runtime.pc_profile().name)
            if runtime.requests_state.is_cancelled(owner, runtime._cur_rid):
                # A request can expire while a different foreground turn
                # holds this one event loop. Previously it disappeared with
                # no owner-visible result. This branch has not executed any
                # tool or model; report non-execution without replay.
                if callable(getattr(runtime, 'as_user', None)):
                    try:
                        with runtime.as_user(user):
                            runtime._emit_for(
                                runtime.profile, 'assistant',
                                'Bu istek işlenmeden iptal edildi veya kuyrukta '
                                'bekleme süresi doldu. Hiçbir işlem başlatılmadı; '
                                'istersen yeniden gönderebilirsin.',
                                source, rid=runtime._cur_rid,
                            )
                    except (ValueError, PermissionError):
                        runtime._record_failure('main.py:expired_command_owner')
                runtime._cur_source = ""
                runtime._cur_rid = None
                runtime.pause_listening.clear()
                _emit_idle_if_silent(runtime, voice_session)
                continue
            try:
                with runtime.as_user(user), runtime.requests_state.activate(owner, runtime._cur_rid, foreground=True):
                    from modules import brain_entry, core_brain_adapter
                    print(f"Sen ({source}): {cmd}")
                    runtime.log.info("İşlem kaydı: %s", 'main.py:main')
                    runtime.emit("user", cmd, source)
                    # Bounded owner + 16-hex job-ID result read / pending-question
                    # answer. The answer writes only the existing ExecutionRecord;
                    # it cannot invoke Brain, model, worker or direct fanout.
                    from modules import canonical_goal_flow
                    explicit_read = canonical_goal_flow.read_result_command(owner, cmd)
                    if explicit_read is None:
                        # Exact user-confirmed foreground handoff for a task
                        # whose first canonical plan was unsupported. The
                        # background worker never executes an effect. Claim its
                        # one-shot identity BEFORE invoking the existing
                        # permissioned foreground goal executor.
                        from modules import canonical_planning_queue
                        try:
                            claimed = canonical_planning_queue.take_foreground(owner, cmd)
                        except (ValueError, PermissionError, OSError):
                            explicit_read = ('Bu hedef için güvenli ön plan devri yapılamadı; '
                                             'başka bir hedef veya worker başlatılmadı.')
                        else:
                            if claimed is not None:
                                explicit_read = ('__foreground_goal__', claimed[0], claimed[1])
                    entry = None
                    if explicit_read is None:
                        # Model gerektirmeyen komutlar (saat, ses, medya, bilinen
                        # uygulama) burada biter: anlama modeli hiç çağrılmaz.
                        explicit_read = _fast_command_turn(runtime, cmd)
                    if explicit_read is None:
                        # The primary semantic model may wait before handoff.
                        # Keep the same owner/request gates while that FIRST
                        # provider wait lends the microphone back to the listener.
                        # This is NOT a second execution thread or full §5
                        # background transfer; subsequent commands remain queued.
                        _t_anlama = runtime.time.time()
                        entry = _turn_with_listening_foreground(
                            voice_session,
                            lambda: brain_entry.prepare(
                                runtime, owner=owner, request_id=runtime._cur_rid,
                                text=cmd, source=source, model_understanding=True,
                            ),
                        )
                        # "Cevap hazırlama 1-27 sn" tek sayıydı; kayıp anlama mı
                        # eller mi, ölçülsün. Salt log: davranış değişmiyor.
                        runtime.log.info("Süre: anlama %.0f ms",
                                         (runtime.time.time() - _t_anlama) * 1000)
                        from modules import brain_echo
                        brain_echo.present(runtime, entry)

                    # Mikrofon tur boyunca KAPATILMAZ: kullanıcı Jarvis arkada
                    # çalışırken konuşmaya devam edebilmeli. Kendi sesini duymasın
                    # diye çalma sırasında dinleyici `speech_blocks_mic()` ile
                    # zaten duruyor; konuşma bitince kendiliğinden geri açılıyor.
                    # Ayar kapalıysa eski davranış (tur boyunca sessiz) korunur.
                    if _mic_stays_listening(runtime):
                        # `submit_voice` komutu kuyruğa alırken mikrofonu kapatmıştı;
                        # tur sürerken kullanıcı yine konuşabilsin diye burada açılır.
                        runtime.pause_listening.clear()
                    else:
                        runtime.pause_listening.set()
                    runtime.emit("state", "thinking")
                    # Edge bağlantısı düşünme sırasında açılır: el sıkışma
                    # ölçüldü 1337 ms, hazır bağlantıda ilk ses 414-481 ms.
                    # Cevap üretilene kadar bu süre zaten boşta geçiyor; ses
                    # yolunda ödemek yerine burada ödenir. Bağlantı kurulamazsa
                    # ses bugünkü yoldan çıkar (voice_edge sıcak soket yoksa
                    # edge_tts'e düşer), yani kaybedilecek bir şey yok.
                    try:
                        from modules import voice_edge_warm
                        if runtime.flags.get("speak", True):
                            # Tazeleyici, uyandırma anındaki soket bayatladığında
                            # yeniden açar (ölçüm: canlı 'voice_warm miss').
                            voice_edge_warm.start_keeper()
                            runtime.threading.Thread(
                                target=voice_edge_warm.prewarm, daemon=True,
                                name="jarvis-edge-prewarm").start()
                    except Exception:
                        runtime._record_failure("modules/engine_loop.py:prewarm")
                    try:
                        t_cmd = runtime.time.time()
                        if explicit_read is None:
                            runtime._llm.take_route()
                        try:
                            if isinstance(explicit_read, tuple) and explicit_read[0] == '__foreground_goal__':
                                from modules import goal_executor
                                out = _turn_with_listening_foreground(
                                    voice_session,
                                    lambda: goal_executor.run(runtime, explicit_read[2]),
                                )
                                brain_feedback, brain_job_id = None, None
                            elif explicit_read is not None:
                                out, brain_feedback, brain_job_id = explicit_read, None, None
                            else:
                                from modules import brain_core_wire
                                wire_result = _turn_with_listening_foreground(
                                    voice_session,
                                    lambda: core_brain_adapter.handoff_json(
                                        runtime, entry.to_handoff_json(), runtime.handle, cmd,
                                    ),
                                )
                                decoded = brain_core_wire.decode_result(
                                    wire_result, owner=owner, request_id=runtime._cur_rid,
                                )
                                out, brain_feedback, brain_job_id = (
                                    decoded["output"], decoded["feedback"], decoded["job_id"],
                                )
                                runtime.log.info(
                                    "Brain handoff: rid=%s stage=%s job=%s feedback=%s",
                                    runtime._cur_rid, entry.stage, brain_job_id or "-",
                                    brain_feedback["result_status"],
                                )
                            runtime.log.info("Süre: core eller %.0f ms",
                                             (runtime.time.time() - t_cmd) * 1000)
                            if not out and cmd == "PC rehberliği: otomatik kontrol":
                                continue
                        except runtime.requests_state.Cancelled as exc:
                            out = str(exc)
                            _log_core_feedback(runtime, entry)
                        except (FileNotFoundError, ValueError) as exc:
                            out = str(exc)
                            _log_core_feedback(runtime, entry)
                        except Exception as exc:
                            runtime._record_failure('main.py:main')
                            core_feedback = _log_core_feedback(runtime, entry)
                            print(f"[Hata] {type(exc).__name__}: {type(exc).__name__}")
                            runtime._record_failure('main.py:main')
                            try:
                                from modules import brain_failure_synthesis
                                if core_feedback is not None:
                                    out = brain_failure_synthesis.synthesize(core_feedback, exc)
                                else:
                                    from modules import diagnose
                                    out = diagnose.explain(exc)
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
                        # Yazı ekranda; ses hemen başlamalı. Mikrofon kilidi
                        # 2 sn'lik pencerelerle tutulduğu için önce dinlemeyi
                        # kesiyoruz, sonra kilidi alıyoruz (ölçüm: 5-10 sn gecikme).
                        speech_started_at = runtime.time.time()
                        runtime.speech_pending.set()
                        with runtime.audio_lock:
                            # Yazı ekranda; mikrofon kilidi ne kadar bekletti?
                            runtime.log.info("Ses kapısı: kilit beklemesi %.0f ms",
                                             (runtime.time.time() - speech_started_at) * 1000)
                            if source == "telefon":
                                runtime._session().speech_override = None
                            elif runtime._session().speech_override:
                                spoken, runtime._session().speech_override = runtime._session().speech_override, None
                                _speak_isolated(runtime, voice_session, spoken)
                            elif runtime._session().last_doc is not None and out.startswith(runtime._session().last_doc[0][:50]):
                                _speak_isolated(runtime, voice_session, runtime._doc_ready_line(runtime._session().last_doc[2], out))
                            else:
                                _speak_isolated(runtime, voice_session, runtime._short_for_speech(runtime.richtext.speakable(out)))
                    finally:
                        runtime.speech_pending.clear()
                        runtime._cur_source = ""
                        runtime._cur_rid = None
                        from config import load_settings as _ls
                        if source == "ses" and _ls().get("followup_no_wake"):
                            voice_session.state["awake_until"] = runtime.time.time() + runtime.SESSION_SECONDS
                        runtime.time.sleep(0.3)
                        runtime.pause_listening.clear()
                        _emit_idle_if_silent(runtime, voice_session)
            except runtime.requests_state.Cancelled:
                runtime._cur_source = ""
                runtime._cur_rid = None
                runtime.pause_listening.clear()
                _emit_idle_if_silent(runtime, voice_session)
                continue
            except ValueError:
                runtime._record_failure('main.py:queued_command')
                runtime._reject_queued_input()
                continue

    except KeyboardInterrupt:
        runtime.stop_event.set()
    finally:
        runtime.stop_event.set()
        # Sıcak Edge bağlantısı kapanışta bırakılır; soket ve oturum sahipsiz
        # kalırsa aiohttp kapanışta uyarı basar.
        try:
            from modules import voice_edge_warm
            voice_edge_warm.close()
        except Exception:
            runtime._record_failure("modules/engine_loop.py:warm_close")
        runtime._cur_source = ""
        runtime._cur_rid = None
        runtime.pause_listening.clear()
        runtime._prefetch_pool.shutdown(wait=False, cancel_futures=True)
        close_voice = getattr(voice_session, "close", None)
        if callable(close_voice):
            close_voice()
        print("Jarvis kapatıldı.")
        runtime.log.info("Jarvis kapatıldı.")
        runtime.emit("quit")
