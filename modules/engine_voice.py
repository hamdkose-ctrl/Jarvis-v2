"""engine voice; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib
import threading

def _physical_mic_claim():
    """One STT device identity shared by wake-word and ordinary capture.

    The engine's audio_lock still orders local recorder use. This adds the
    existing Scheduler/OS resource reservation while an actual wake stream is
    open, never while an STT network/provider wait is pending.
    """
    from modules import voice_runtime
    if voice_runtime.active() is None:
        return contextlib.nullcontext()
    from modules import interactive_resource_gate
    return interactive_resource_gate.claim("stt", owner="device")


def _pc_context(runtime, fn):
    from functools import wraps
    @wraps(fn)
    def wrapped(*args, **kwargs):
        owner = runtime.pc_profile().name
        pre_registered = None
        fn_name = getattr(fn, "__name__", getattr(getattr(fn, "func", None), "__name__", ""))
        if fn_name == "_live_command":
            owner_slug = runtime.slugify(owner)
            pre_registered = runtime.secrets.token_hex(16)
            if not runtime.requests_state.register(owner_slug, pre_registered):
                return "İstek kabul edilmedi; yeniden söyle."
            kwargs["_pre_registered_rid"] = pre_registered
            kwargs["_pre_registered_owner"] = owner_slug
        try:
            with runtime.as_user(owner):
                return fn(*args, **kwargs)
        except BaseException:
            if pre_registered:
                runtime.requests_state.cancel(runtime.slugify(owner), pre_registered)
            raise
    return wrapped


def _recent_turns(runtime, slug: str, hours: float = 2.0, limit: int = 12) -> list[tuple[str, str]]:
    """Kalıcı geçmişten (sesli + yazılı) son konuşmalar: [(rol, metin)], yalnızca son 'hours' saat."""
    cut = (runtime.datetime.now() - runtime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        from modules import conversation_reset
        rows = conversation_reset.recent(slug, runtime.history.read(slug, "", 80))
    except Exception:
        runtime._record_failure('main.py:_recent_turns')
        return []
    out = [(r["role"], " ".join(str(r.get("text", "")).split()))
           for r in rows if r.get("role") in ("user", "assistant") and str(r.get("ts", "")) >= cut]
    return out[-limit:]




def _sounds_like_wake(runtime, text: str) -> bool:
    """Duyulan cümlede uyandırma adına çok benzeyen bir kelime var mı (ad yanlış duyulmuş olabilir)."""
    import difflib
    names = [runtime._tr_lower(runtime.WAKE_WORD)] + [runtime._tr_lower(a) for a in runtime.WAKE_ALIASES]
    common = {"seni", "sen", "sene", "sana", "senin", "sıra", "sarı", "şiir", "seri", "sere"} - set(names)
    for w in runtime.re.findall(r"[\wçğıöşü]+", runtime._tr_lower(text))[:2]:      # ad genelde cümlenin başında söylenir
        if len(w) >= 3 and w not in common and any(difflib.SequenceMatcher(None, w, n).ratio() >= 0.7 for n in names):
            return True
    return False

def find_wake(runtime, text: str) -> int:
    """Uyandırma adını (config.WAKE_ALIASES ve benzer yazılışlarıyla) arar.

    Adın bittiği indeksi döndürür, bulunamazsa -1. 6 harften kısa adlarda bulanık eşleşme
    kapalıdır (yanlış tetiklemeyi önlemek için), yalnızca ad ve takma adlar kabul edilir.
    """
    names = [runtime._tr_lower(runtime.WAKE_WORD)] + [runtime._tr_lower(a) for a in runtime.WAKE_ALIASES]
    wake = names[0]
    fuzzy = len(wake) >= 6
    mishear = runtime._JARVIS_MISHEAR if runtime._is_jarvis_name() else set()
    for i, m in enumerate(runtime.re.finditer(r"\w+", text)):
        word = runtime._tr_lower(m.group())
        if word in names:
            return m.end()
        if i <= 1 and word in mishear:      # Google'ın "Jarvis"i yanlış yazdığı hâller: yalnızca cümle başında
            return m.end()
        if fuzzy and runtime.difflib.SequenceMatcher(None, word, wake).ratio() >= 0.75:
            return m.end()
    return -1

def _is_jarvis_name(runtime) -> bool:
    return runtime._tr_lower(runtime.WAKE_WORD).replace("hey", "").strip() == "jarvis"

def _strip_wake(runtime, text: str) -> str:
    """Komutun başındaki "hey", "Jarvis" ve yanlış duyulmuş hâllerini atar ("servis saat kaç" -> "saat kaç")."""
    t = (text or "").strip()
    for _ in range(3):
        m = runtime.re.match(r"\s*(\w+)[\s,.!?]*", t)
        if not m:
            break
        w = runtime._tr_lower(m.group(1))
        names = {runtime._tr_lower(runtime.WAKE_WORD), *(runtime._tr_lower(a) for a in runtime.WAKE_ALIASES), "hey", "hay", "hei"}
        if w in names or (runtime._is_jarvis_name() and (w in runtime._JARVIS_MISHEAR or w in runtime._LEAD_WORDS)):
            t = t[m.end():]
        else:
            break
    return t.strip(" ,.!?")

def list_input_devices(runtime) -> None:
    import sounddevice as sd
    print("Mikrofon cihazları (numara, ad, ses sürücüsü):")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            host = sd.query_hostapis(d["hostapi"])["name"]
            print(f"{i:3d}  {d['name']}  [{host}]")
    print("\nconfig.py içinde INPUT_DEVICE = \"ad parçası\" ya da cihaz numarası yazarak seçebilirsin.")

class VoiceSession:
    """Own the listening/playback lifecycle and its wake continuation state."""
    def __init__(self, runtime):
        self.runtime = runtime
        self.listening_enabled = "--text" not in runtime.sys.argv
        self.speak_enabled = "--mute" not in runtime.sys.argv
        from config import load_settings
        self.manual_local_stt = bool(load_settings().get('local_stt_enabled', False))
        runtime._manual_local_stt = self.manual_local_stt
        self.state = {"awake_until": 0.0}
        self.voice_lane = None
        self.voice_core_fault = None
        # Many queued utterances must share ONE barge-in watcher rather than
        # leaving a separate microphone contender alive for each speech receipt.
        self._barge_lock = threading.Lock()
        self._barge_thread = None
        self._barge_pending = None
        self._barge_closed = threading.Event()
        from modules import voice_runtime
        try:
            self.voice_lane, piper_enabled = voice_runtime.maybe_start(runtime)
        except ValueError:
            runtime._record_failure('modules/engine_voice.py:voice_core_setup')
            voice_runtime.block_legacy_on_fault()
            # An explicitly requested invalid configuration must never silently
            # fall back to Edge, SAPI or a different user's voice.
            self.voice_core_fault = "Voice Core yapılandırması hatalı. Ses değiştirilmedi; yanıt yazılı kalacak."
        if self.voice_lane is not None and piper_enabled:
            runtime.emit("system", "Yerel Voice Core etkin: ses arka planda oynatılır, seçili ses değişmez.")

    def close(self):
        closed = getattr(self, "_barge_closed", None)
        if closed is not None:
            closed.set()
        lane = getattr(self, "voice_lane", None)
        if lane is not None:
            lane.close()

    def _schedule_barge_watch(self, done: threading.Event) -> None:
        """At most one barge-in microphone contender for this VoiceSession.

        The newest queued receipt is remembered while the current speech is
        being watched. On a completed receipt, the SAME worker continues to
        the newest one. Never start N wakeword threads for N progress notices.
        """
        # Some standalone speech fixtures construct VoiceSession without the
        # engine __init__. Production always installs these fields in __init__;
        # the lazy branch preserves compatibility with those no-device callers.
        if not hasattr(self, "_barge_lock"):
            self._barge_lock = threading.Lock()
            self._barge_thread = None
            self._barge_pending = None
            self._barge_closed = threading.Event()
        with self._barge_lock:
            if self._barge_closed.is_set():
                return
            self._barge_pending = done
            if self._barge_thread is not None:
                return
            worker = self.runtime.threading.Thread(
                target=self._barge_watch_loop, daemon=True,
                name="jarvis-voice-barge",
            )
            self._barge_thread = worker
        try:
            worker.start()
        except Exception:
            with self._barge_lock:
                if self._barge_thread is worker:
                    self._barge_thread = None
                    self._barge_pending = None
            raise

    def _barge_watch_loop(self) -> None:
        """Coalesce queued speech events, keeping one physical wake claimant."""
        while True:
            with self._barge_lock:
                if self._barge_closed.is_set() or self.runtime.stop_event.is_set():
                    self._barge_thread = None
                    self._barge_pending = None
                    return
                target = self._barge_pending
            if target is not None:
                try:
                    self._barge_watch(target)
                except Exception:
                    self.runtime._record_failure('modules/engine_voice.py:barge_loop')
            with self._barge_lock:
                if target is self._barge_pending:
                    self._barge_thread = None
                    self._barge_pending = None
                    return

    def _idle_if_silent(self):
        """Never claim a quiet UI while the actual speaker cut is unconfirmed."""
        if not self.speech_blocks_mic():
            self.runtime.emit("state", "idle")

    def submit_voice(self, command: str) -> bool:
        """Only an accepted command leaves listening paused for the event loop."""
        runtime = self.runtime
        runtime.pause_listening.set()
        accepted = False
        try:
            accepted = runtime.submit(command, "ses")
            return accepted
        finally:
            if not accepted:
                runtime.pause_listening.clear()
                self._idle_if_silent()

    def speech_blocks_mic(self) -> bool:
        """True while this machine's speaker may still be carrying audio.

        `is_busy` means an utterance is handed to the one output owner; the
        unconfirmed cut means the device never admitted it stopped. The microphone
        handoff (`voice_runtime.handoff_to_listen`) and the UI idle claim already
        read both, so every gate that opens the microphone has to read the same
        proof. Otherwise the always-on wake-word listener transcribes Jarvis's own
        voice while push-to-talk stays protected, and the two paths disagree about
        the same speaker.
        """
        lane = getattr(self, "voice_lane", None)
        return lane is not None and (lane.is_busy() or lane.stop_unconfirmed())

    @contextlib.contextmanager
    def mic_open_during_model_wait(self):
        """VOICE P3: waiting on a provider is not a reason to be deaf.

        An engine turn holds `pause_listening` for its whole duration, so a bounded
        model wait (the canonical planner waits up to 60 s) closed the microphone even
        though the answer it produces tells the user to keep talking. Only this wait
        window re-opens the existing gate: the owner identity lock, the speech window,
        capture ownership and every cancel path are untouched, and the previous state
        is restored exactly when the wait ends.
        """
        runtime = self.runtime
        from config import load_settings
        if not self.listening_enabled or self.manual_local_stt or not runtime.flags["mic"] \
                or not load_settings().get("voice_mic_during_model_wait", True) \
                or self.speech_blocks_mic():
            yield
            return
        was_paused = runtime.pause_listening.is_set()
        runtime.pause_listening.clear()
        try:
            yield
        finally:
            if was_paused:
                runtime.pause_listening.set()

    def _barge_watch(self, done: threading.Event) -> None:
        runtime = self.runtime
        """Jarvis konuşurken "Hey Jarvis" denirse susup dinlemeye geçer (internetsiz dinleyici hazırsa)."""
        from modules import wakeword
        if self.manual_local_stt or not self.listening_enabled or not runtime.flags["mic"] or not wakeword.wanted(runtime.WAKE_WORD) or not wakeword.ready():
            return
        if done.wait(1.2):                 # konuşmanın ilk anı: hoparlör sesi yankı yapıp uyandırmasın
            return

        def stopped() -> bool:
            closed = getattr(self, "_barge_closed", None)
            return (done.is_set() or runtime.stop_event.is_set()
                    or (closed is not None and closed.is_set())
                    or not runtime.flags["mic"])

        # The wake microphone is the same capture device the recorder uses, and the
        # engine owns it under audio_lock. Opening this second stream outside that
        # lock let a background notice start capturing while a push-to-talk or web
        # recording was already running: two PortAudio streams on one device, with
        # the speaker feeding Jarvis's own wake model. Listening in short slices
        # keeps the handover bounded — wait returns within one frame of the stop
        # signal, the recorder wins the lock between slices, and the watch resumes.
        deadline = runtime.time.time() + 600
        hit = None
        try:
            while not stopped() and runtime.time.time() < deadline:
                with runtime.audio_lock:
                    if stopped():
                        break
                    with _physical_mic_claim():
                        hit = wakeword.wait(stopped, capture=False, max_seconds=2.0,
                                            min_threshold=0.65)  # kendi sesinden uyanmasın diye çok daha sıkı eşik
                if hit is not None:
                    break
        except Exception:
            runtime._record_failure('main.py:_barge_watch')
            return
        # A wake result delivered after shutdown/mic-off/receipt completion
        # must not stop the next owner's or next session's speech.
        if hit is not None and not stopped():
            runtime.voice.stop_speaking()
            self.state["awake_until"] = runtime.time.time() + runtime.SESSION_SECONDS   # şimdi söyleneni ad beklemeden dinle
            runtime.log.info("Konuşma kesildi: Hey Jarvis")

    def speak(self, text: str, slow: bool = False, shown: bool = False,
              identity: dict | None = None) -> None:
        """Say one utterance. `identity` is the result it presents, as Core named it.

        A background notice that knows which reminder/event/approval it announces
        passes turn/event/goal/version/artifact/approval ids here; the queue uses
        them for currency, duplicate delivery and explicit invalidation. Absent
        identity means an ordinary conversational answer and is never deduplicated.
        """
        runtime = self.runtime
        if not (self.speak_enabled and runtime.flags["speak"]):
            return
        if getattr(self, "voice_core_fault", None):
            runtime.emit("system", self.voice_core_fault)
            return
        lane = getattr(self, "voice_lane", None)
        if lane is None:
            # The single owner is absent only after a reported fault; never open
            # a second Edge/SAPI/Live speech path from here.
            return
        # Existing per-user voice preference is the only voice identity authority.
        # Enqueue returns immediately; Core work continues. A refusal is a typed
        # receipt with a written notice, not a fallback to another voice.
        prefs = runtime.profile.data["prefs"]
        voice_key = prefs.get("voice") or "tr_erkek"
        raw_rate = prefs.get("rate", 0)
        rate = raw_rate if type(raw_rate) is int and -40 <= raw_rate <= 40 else 0
        if slow:
            rate = min(rate, -15)
        # The producer names the result; the turn it belongs to is the engine's
        # current request id unless the notice already knows a better one.
        carried = dict(identity or {})
        kind = carried.pop("kind", "notice" if shown else "reply")
        turn_id = carried.pop("turn_id", None) or (getattr(runtime, "_cur_rid", None) or "")
        try:
            done = lane.say(runtime.profile.slug, voice_key, text,
                            background=shown, rate=rate, kind=kind,
                            turn_id=turn_id, **carried)
        except ValueError:
            runtime._record_failure('modules/engine_voice.py:voice_core_submit')
            runtime.emit("system", "Seçilen ses kullanılamıyor; başka ses kullanılmadı, yanıt yazılı korundu.")
            return
        if not done.is_set():
            # "speaking" is claimed by the lane at the real playback_started
            # boundary, not here at enqueue: synthesis/queue acceptance is not
            # audible speech. Barge-in watching still starts for the live utterance.
            self._schedule_barge_watch(done)

    def offline_wake_step(self) -> bool:
        runtime = self.runtime
        """İnternetsiz uyandırma ("Hey Jarvis"): bir tur dinler. Bu yöntem kullanılmıyorsa False döner."""
        from modules import wakeword
        if runtime.time.time() < self.state["awake_until"] or not wakeword.wanted(runtime.WAKE_WORD):
            return False                  # oturum açıkken ad gerekmez: eski yöntemle dinlenir
        if not wakeword.ready():
            st = wakeword.status()
            if st["state"] == "failed" and not self.state.get("wake_warned"):
                self.state["wake_warned"] = True
                msg = "İnternetsiz uyandırma çalışmıyor, Google yöntemiyle devam ediyorum. " + st["error"]
                print(f"[Uyarı] {msg}")
                runtime.emit("system", msg)
                runtime.log.warning(msg)
            return False                  # hazırlanırken / kurulamadıysa Google yöntemi

        def should_stop() -> bool:
            return runtime.stop_event.is_set() or runtime.pause_listening.is_set() or not runtime.flags["mic"] \
                or self.speech_blocks_mic() or not wakeword.wanted(runtime.WAKE_WORD)

        with runtime.audio_lock:
            if should_stop():
                return True
            with _physical_mic_claim():
                audio = wakeword.wait(should_stop, on_wake=lambda: runtime.emit("state", "listening"))
        if audio is None:
            return True                   # "Hey Jarvis" duyulmadı; döngü yeniden dinler
        cmd = runtime._strip_wake(runtime.voice.recognize(audio) or "") if audio else ""
        if should_stop():
            self._idle_if_silent()
            return True
        if not cmd and not runtime.flags.get("sleep") and not should_stop():
            # Komut duyulmadı ya da yalnızca "Jarvis"in sonu duyuldu ("servis"): sormadan bir kez daha dinle
            runtime.emit("state", "listening")
            with runtime.audio_lock:
                # A playback may begin after the pre-lock check. Never open
                # the follow-up microphone over Jarvis's own unconfirmed audio.
                if should_stop():
                    return True
                raw = runtime.voice.capture(timeout=5, abort=runtime._AnyAbort(runtime.pause_listening, runtime.mic_cancel))
            again = runtime.voice.recognize(raw or b"", announce_fail=False)
            cmd = runtime._strip_wake(again or "")
            audio = audio or (b"x" if again else b"")
        if should_stop():
            self._idle_if_silent()
            return True
        if runtime.flags.get("sleep"):            # hazırda bekle: yalnızca "Hey Jarvis, uyan"
            if runtime.re.search(r"uyan|kalk|devam|hazır|aç", runtime._tr_lower(cmd)):
                runtime.set_sleep(False)
            self._idle_if_silent()
            return True
        if not cmd:
            self.state["awake_until"] = runtime.time.time() + runtime.SESSION_SECONDS    # adı duydu, komutu bekliyor
            if audio:
                runtime.pause_listening.set()
                runtime.events.put(("say", "Anlayamadım, tekrar söyler misin?"))
            else:
                self._idle_if_silent()
            return True
        self.submit_voice(cmd)
        return True

    def listen_for_wake_word(self):
        runtime = self.runtime
        last_error = None
        silent_count = 0
        while not runtime.stop_event.is_set():
            lane = getattr(self, "voice_lane", None)
            if runtime.pause_listening.is_set() or not runtime.flags["mic"] \
                    or self.speech_blocks_mic():
                runtime.stop_event.wait(0.1)
                continue

            try:
                if self.offline_wake_step():
                    last_error = None
                    self.state["mic_errs"] = 0
                    continue
            except Exception as exc:
                runtime._record_failure('main.py:listen_for_wake_word')
                if runtime.stop_event.is_set():
                    break
                self.state["awake_until"] = 0
                mic_err = type(exc).__name__ == "PortAudioError" or "PaErrorCode" in str(exc)
                if mic_err:
                    # Mikrofon bir anlığına kayboldu (kulaklık takıldı/çıkarıldı, Windows cihazı değiştirdi):
                    # dinleyiciyi kapatma, birkaç saniye sonra mikrofonu yeniden açıp devam et.
                    self.state["mic_errs"] = self.state.get("mic_errs", 0) + 1
                    if self.state["mic_errs"] == 1:
                        runtime._record_failure('main.py:listen_for_wake_word')
                    if self.state["mic_errs"] == 5:
                        runtime.emit("system", "Mikrofona ulaşılamıyor. Mikrofon takılı mı? Windows ses ayarlarını kontrol et.")
                    runtime.stop_event.wait(min(2 * self.state["mic_errs"], 15))
                    continue
                runtime._record_failure('main.py:listen_for_wake_word')  # privacy-safe diagnostic is emitted at the catch boundary
                if str(exc) != last_error:
                    last_error = str(exc)
                    runtime.emit("system", f"İnternetsiz uyandırmada hata, Google yöntemiyle devam: {exc}")
                from modules import wakeword
                wakeword._set("failed", str(exc))      # bu oturumda tekrar deneme, eski yönteme dön
                continue

            try:
                with runtime.audio_lock:
                    if runtime.pause_listening.is_set() or not runtime.flags["mic"] \
                            or self.speech_blocks_mic():
                        continue
                    in_session = runtime.time.time() < self.state["awake_until"]
                    abort = runtime._AnyAbort(
                        runtime.pause_listening, runtime.mic_cancel,
                        *( (lane.busy_event,) if lane is not None else () ),
                    )
                    raw = runtime.voice.capture(timeout=2, abort=abort)
                # The recording is only bytes now, so the STT wait runs after the
                # capture lock instead of holding the microphone through a provider.
                heard = runtime.voice.recognize(raw or b"", announce_fail=False,
                                                cheap=not in_session,   # ad aranırken ücretsiz yöntem
                                                gate=in_session)        # sohbet sürerken gürültüyü komut sanma
            except Exception as exc:
                runtime._record_failure('main.py:listen_for_wake_word')
                if runtime.stop_event.is_set():
                    break                 # Jarvis kapanırken mikrofonun kapanması hata değil
                # PortAudio bazen cihaz geçişinde/başka ses işlemi stream'i kapattığında
                # "Stream is stopped" üretir. Bu kalıcı arıza değildir: yeni listen()
                # turu zaten yeni bir RawInputStream açar. Hata raporunu şişirmeden yeniden dene.
                msg = str(exc)
                transient_stream = "stream is stopped" in msg.casefold() or "stream is not active" in msg.casefold()
                if transient_stream:
                    if msg != last_error:
                        last_error = msg
                        runtime._record_failure('main.py:listen_for_wake_word')
                    runtime.stop_event.wait(0.35)
                    continue
                if msg != last_error:
                    last_error = msg
                    print(f"[Mikrofon hatası] {type(exc).__name__}")
                    runtime.emit("system", f"Mikrofon hatası: {exc}")
                    runtime._record_failure('main.py:listen_for_wake_word')
                runtime.stop_event.wait(1.0)
                continue
            last_error = None

            if runtime.stop_event.is_set() or runtime.pause_listening.is_set() or not runtime.flags["mic"] \
                    or self.speech_blocks_mic():
                continue  # Discard stale recognition after speaker/mute/shutdown.

            # Mikrofon tamamen sessizse (gürültü tam 0) kullanıcıyı bir kez uyar.
            if runtime.voice.last_noise == 0:
                silent_count += 1
                if silent_count == 5:
                    msg = ("[Uyarı] Mikrofon hiç ses vermiyor (gürültü: 0). Windows'ta Ayarlar > Gizlilik > "
                           "Mikrofon iznini kontrol et ya da 'python main.py --devices' ile cihazı seç.")
                    print(msg)
                    runtime.emit("system", msg)
                    runtime.log.warning(msg)
            else:
                silent_count = 0

            if not heard or not heard.strip():
                continue
            heard = heard.strip()

            wake_end = runtime.find_wake(heard)
            if runtime.flags.get("sleep"):            # hazırda bekle: yalnızca "<ad> uyan" dinlenir
                if wake_end >= 0 and runtime.re.search(r"uyan|kalk|devam|hazır|aç", runtime._tr_lower(heard[wake_end:])):
                    runtime.set_sleep(False)
                continue
            if wake_end >= 0:
                cmd = runtime._strip_wake(heard[wake_end:])
            elif runtime.time.time() < self.state["awake_until"]:
                cmd = runtime._strip_wake(heard)   # oturum açık: uyandırma adı gerekmez
            else:
                runtime.log.debug("Duyulan (uyandırma adı yok): %r", heard)
                # Ortamdaki konuşmalara karışma; yalnızca ada benzer bir şey duyulduysa (yanlış duyulmuş ad) "Anlamadım" de.
                if runtime.ANNOUNCE_UNKNOWN and runtime._sounds_like_wake(heard):
                    runtime.pause_listening.set()
                    runtime.events.put(("say", "Anlamadım, tekrar söyler misin?"))
                continue

            # Yalnızca ad söylendiyse komutu ayrıca dinle
            if not cmd:
                runtime.events.put(("status", "Komutunu dinliyorum..."))
                runtime.emit("state", "listening")
                try:
                    with runtime.audio_lock:
                        # An output notification can start between recognizing
                        # the wake name and opening the second capture stream.
                        # Check speaker proof with physical mic ownership held.
                        if runtime.pause_listening.is_set() or not runtime.flags["mic"] \
                                or self.speech_blocks_mic():
                            continue
                        raw = runtime.voice.capture(timeout=4, verbose=True, abort=runtime.mic_cancel)
                    cmd = runtime.voice.recognize(raw or b"", announce_fail=True)
                except Exception:
                    runtime._record_failure('main.py:listen_for_wake_word')
                    cmd = None
                if not cmd or not cmd.strip():
                    self.state["awake_until"] = runtime.time.time() + runtime.SESSION_SECONDS
                    continue
                cmd = cmd.strip()

            if runtime.stop_event.is_set() or runtime.pause_listening.is_set() or not runtime.flags["mic"] \
                    or self.speech_blocks_mic():
                continue

            self.submit_voice(cmd)

    def read_keyboard(self):
        runtime = self.runtime
        while not runtime.stop_event.is_set():
            try:
                text = input("> ").strip()
            except EOFError:
                break               # klavye yoksa yalnızca ses çalışmaya devam eder
            except KeyboardInterrupt:
                runtime.stop_event.set()
                break
            if text:
                # The keyboard is not a second cancel authority: engine_queue owns the
                # vocabulary, so a typed "dur" keeps the Core cancellation the same word
                # has from the UI and the phone, while "sus" alone stays speech-only.
                # The private shortcut here used to make both words mean "stop talking".
                runtime.submit(text, "yazı")
