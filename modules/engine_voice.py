"""engine voice; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations
import contextlib

def prepare_live_tool(runtime, fn, *args):
    """Register before executor/PC-lock waiting, keeping the captured PC owner."""
    owner = runtime.pc_profile()
    rid = runtime.secrets.token_hex(16)
    if not runtime.requests_state.register(owner.slug, rid):
        raise ValueError("İstek kabul edilmedi; yeniden söyle.")
    def run():
        try:
            with runtime.as_user(owner.name), runtime.requests_state.activate(owner.slug, rid):
                previous = (runtime._cur_source, runtime._cur_rid)
                runtime._cur_source, runtime._cur_rid = "ses", rid
                try:
                    runtime.requests_state.check()
                    result = fn(*args)
                    runtime.requests_state.check()
                    return result
                finally:
                    runtime._cur_source, runtime._cur_rid = previous
        except BaseException:
            runtime.requests_state.cancel(owner.slug, rid)
            raise
    return run

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

def _live_prompt(runtime) -> str:
    """Canlı oturum talimatının kalıcı bağlamı (uzunluk tercihi, aktif modlar, onay bekleyenler).

    Bellek/geçmiş seçimi burada yapılmaz. Bu fonksiyon bağlantı anında bir kez çağrılır,
    o yüzden elinde çözülecek bir soru yoktur; soru-bağımlı ilgi seçimi her turda canonical
    yoldan gelir (runtime.handle → profile.system_prompt(soru) → ilgili bilgi ve kural).
    Assembly salt-okunurdur: profil yazan hiçbir şey çağrılmaz.
    """
    d = runtime.profile.data
    parts = []
    parts.append("Kullanıcı bilgisayarda bir işi nasıl yapacağını adım adım öğrenmek istediğinde komut aracına 'PC yardımı: <kullanıcının amacı>' ilet. PC rehberliği açıkken 'yaptım', 'anlamadım', 'hangi düğme', 'devam et' ve 'dur' sözlerini komut aracına 'PC rehberliği: <kullanıcının sözü>' olarak ilet; ekrana bakmadan kendin adım veya hedef uydurma. Panel sonucu tek adımdır; kısaca seslendir.")
    from modules import pc_guide
    if pc_guide.active(runtime.profile.slug):
        parts.append("PC rehberliği şu an açık; bu işe ilişkin bütün takip isteklerini PC rehberliği komutuna ilet.")
    from modules import developer
    if developer.status(runtime.profile.slug)['enabled']:
        parts.append("Geliştirme modu açık. Proje, kod, tasarım, görsel ve bunları değiştiren takip isteklerini kullanıcının sözüyle komut aracına ilet. Sonucun tamamı sohbette gösterilir; yalnız kısa sonucu seslendir.")
    if d["prefs"].get("verbosity", "orta") == "uzun":
        parts.append("Kullanıcı ayrıntılı cevap sevdiğini söyledi; gerektiğinde daha uzun anlat.")
    from modules import learning
    pending = learning.pending_prompt(runtime.profile)
    if pending:
        parts.append(pending)
    from config import load_settings
    words = [w.strip() for w in (load_settings().get("stt_words") or "").split(",") if w.strip()]
    words += runtime._live_vocab()[:25]
    if words:
        parts.append("Kullanıcının sık söylediği özel ad ve terimler (bunları doğru anla ve doğru yaz): "
                     + ", ".join(dict.fromkeys(words)) + ".")
    assistant_name = str(load_settings().get("assistant_name") or runtime.ASSISTANT_NAME).strip() or "Jarvis"
    return runtime.live.build_prompt(assistant_name, runtime.profile.name, "\n".join(parts))

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

def live_session_opened(runtime) -> None:
    """Oturum açma olayı: onay sorusu bu oturumda sorulacaksa zamanını işaretler.

    Yazma burada, talimat kurulurken değil: assembly salt-okunur kalır, olayın sahibi yazar.
    """
    from modules import learning
    owner = runtime.pc_profile()
    if learning.pending_ask_due(owner):
        learning.mark_pending_ask(owner)

def _live_session_end(runtime, convo: list[tuple[str, str]]) -> None:
    """Canlı konuşma bitince: kalıcı bilgi adaylarını çıkar, onaya koy (onaysız hafızaya yazılmaz)."""
    from modules import learning
    owner = runtime.pc_profile()
    if not learning.enabled(owner): return
    added = []
    for role, text in convo:
        if role == "user": added.extend(learning.observe(owner, text))
    if added:
        runtime.emit("system", f"Konuşmadan {len(added)} yeni şey öğrendim: " + "; ".join(added)
                  + ". Hafıza sayfasından onaylayabilir ya da “öğrendiklerini kaydet” diyebilirsin.")

def _live_vocab(runtime) -> list[str]:
    """Ses tanımanın doğru yazması gereken çevre adları: kişiler, projeler, kullanıcılar, şehir, sık uygulamalar."""
    words: list[str] = []
    try:
        d = runtime.profile.data
        words += list((d.get("contacts") or {}).keys())
        city = d["prefs"].get("city")
        if city:
            words.append(str(city))
        words += [u for u in runtime.list_users()]
        from modules import worktrack
        st = worktrack.settings()
        words += list(st.get("vip") or []) + list(st.get("projects") or [])
        apps = [a for a in runtime.system_control.installed_apps() if 3 <= len(a) <= 20 and not runtime.re.search(r"uninstall|update|setup|redist|runtime", a)]
        words += [a.title() for a in apps[:15]]
    except Exception:
        runtime._record_failure('main.py:_live_vocab')
    return [w.strip() for w in dict.fromkeys(words) if isinstance(w, str) and 2 <= len(w.strip()) <= 30]

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
        self.live_on = self.listening_enabled and not self.manual_local_stt and runtime.live.enabled()
        self.state = {"awake_until": 0.0}
        self.voice_lane = None
        self.voice_core_fault = None
        from modules import voice_runtime
        try:
            self.voice_lane, _enabled = voice_runtime.maybe_start(runtime)
        except ValueError:
            runtime._record_failure('modules/engine_voice.py:voice_core_setup')
            voice_runtime.block_legacy_on_fault()
            # An explicitly requested invalid configuration must never silently
            # fall back to Edge, SAPI or a different user's voice.
            self.voice_core_fault = "Voice Core yapılandırması hatalı. Ses değiştirilmedi; yanıt yazılı kalacak."
        if self.voice_lane is not None:
            runtime.emit("system", "Yerel Voice Core etkin: ses arka planda oynatılır, seçili ses değişmez.")

    def close(self):
        lane = getattr(self, "voice_lane", None)
        if lane is not None:
            lane.close()

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
                runtime.emit("state", "idle")

    def _barge_watch(self, done: threading.Event) -> None:
        runtime = self.runtime
        """Jarvis konuşurken "Hey Jarvis" denirse susup dinlemeye geçer (internetsiz dinleyici hazırsa)."""
        from modules import wakeword
        if self.manual_local_stt or not self.listening_enabled or not runtime.flags["mic"] or not wakeword.wanted(runtime.WAKE_WORD) or not wakeword.ready():
            return
        if done.wait(1.2):                 # konuşmanın ilk anı: hoparlör sesi yankı yapıp uyandırmasın
            return
        try:
            hit = wakeword.wait(lambda: done.is_set() or runtime.stop_event.is_set() or not runtime.flags["mic"], capture=False, max_seconds=600,
                                min_threshold=0.65)  # kendi sesinden uyanmasın diye çok daha sıkı eşik
        except Exception:
            runtime._record_failure('main.py:_barge_watch')
            return
        if hit is not None and not done.is_set():
            runtime.voice.stop_speaking()
            self.state["awake_until"] = runtime.time.time() + runtime.SESSION_SECONDS   # şimdi söyleneni ad beklemeden dinle
            runtime.log.info("Konuşma kesildi: Hey Jarvis")

    def speak(self, text: str, slow: bool = False, shown: bool = False) -> None:
        runtime = self.runtime
        if self.speak_enabled and runtime.flags["speak"]:
            if getattr(self, "voice_core_fault", None):
                runtime.emit("system", self.voice_core_fault)
                return
            lane = getattr(self, "voice_lane", None)
            if lane is not None:
                # Existing per-user voice preference is the only voice identity
                # authority. Do not reuse Edge/SAPI when an exact Piper model is
                # absent. Enqueue returns immediately; Core work continues.
                prefs = runtime.profile.data["prefs"]
                voice_key = prefs.get("voice") or "tr_erkek"
                try:
                    done = lane.say(runtime.profile.slug, voice_key, text,
                                    background=shown)
                except ValueError:
                    runtime._record_failure('modules/engine_voice.py:voice_core_submit')
                    runtime.emit("system", "Seçilen yerel ses kullanılamıyor veya kuyruk dolu; başka ses kullanılmadı.")
                    return
                if not done.is_set():
                    runtime.emit("state", "speaking")
                    runtime.threading.Thread(
                        target=self._barge_watch, args=(done,), daemon=True,
                    ).start()
                return
            # Canlı mod açıksa TÜM PC sesli yanıtlarını aynı Gemini Live sesiyle okut.
            # Yazı/web cevabı zaten arayüze bir kez yazıldığı için Live transkriptinin ikinci kez
            # sohbet geçmişine düşmesini `suppress_ui=True` ile engelliyoruz.
            # shown=True: arka plan iletisi (sabah özeti, hatırlatma, Google izni) `_emit_for` ile zaten yazıldı.
            if self.live_on and runtime.live.get() is not None and runtime.live.enabled():
                runtime.live.get().say(text, suppress_ui=shown or (runtime._cur_source in ("yazı", "web")) or slow, exact=True, slow=slow)
                return
            runtime.emit("state", "speaking")
            done = runtime.threading.Event()
            runtime.threading.Thread(target=self._barge_watch, args=(done,), daemon=True).start()
            opts = runtime._voice_opts()
            if slow:
                opts["rate"] = min(opts.get("rate", -8), -15)   # ders anlatımı: daha da yavaş
            try:
                error = runtime.voice.speak(text, **opts)
                if isinstance(error, str):
                    runtime.emit("system", error)
            finally:
                done.set()

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
            lane = getattr(self, "voice_lane", None)
            return runtime.stop_event.is_set() or runtime.pause_listening.is_set() or not runtime.flags["mic"] \
                or (lane is not None and lane.is_busy()) or not wakeword.wanted(runtime.WAKE_WORD)

        with runtime.audio_lock:
            if should_stop():
                return True
            audio = wakeword.wait(should_stop, on_wake=lambda: runtime.emit("state", "listening"))
        if audio is None:
            return True                   # "Hey Jarvis" duyulmadı; döngü yeniden dinler
        cmd = runtime._strip_wake(runtime.voice.recognize(audio) or "") if audio else ""
        if should_stop():
            runtime.emit("state", "idle")
            return True
        if not cmd and not runtime.flags.get("sleep") and not should_stop():
            # Komut duyulmadı ya da yalnızca "Jarvis"in sonu duyuldu ("servis"): sormadan bir kez daha dinle
            runtime.emit("state", "listening")
            with runtime.audio_lock:
                again = runtime.voice.listen(timeout=5, announce_fail=False, abort=runtime._AnyAbort(runtime.pause_listening, runtime.mic_cancel))
            cmd = runtime._strip_wake(again or "")
            audio = audio or (b"x" if again else b"")
        if should_stop():
            runtime.emit("state", "idle")
            return True
        if runtime.flags.get("sleep"):            # hazırda bekle: yalnızca "Hey Jarvis, uyan"
            if runtime.re.search(r"uyan|kalk|devam|hazır|aç", runtime._tr_lower(cmd)):
                runtime.set_sleep(False)
            runtime.emit("state", "idle")
            return True
        if not cmd:
            self.state["awake_until"] = runtime.time.time() + runtime.SESSION_SECONDS    # adı duydu, komutu bekliyor
            if audio:
                runtime.pause_listening.set()
                runtime.events.put(("say", "Anlayamadım, tekrar söyler misin?"))
            else:
                runtime.emit("state", "idle")
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
                    or (lane is not None and lane.is_busy()) \
                    or (runtime.live.get() is not None and runtime.live.enabled()):
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
                            or (lane is not None and lane.is_busy()) \
                            or (runtime.live.get() is not None and runtime.live.enabled()):
                        continue
                    in_session = runtime.time.time() < self.state["awake_until"]
                    abort = runtime._AnyAbort(
                        runtime.pause_listening, runtime.mic_cancel,
                        *( (lane.busy_event,) if lane is not None else () ),
                    )
                    heard = runtime.voice.listen(timeout=2, announce_fail=False, abort=abort,
                                         cheap=not in_session,      # ad aranırken ücretsiz yöntem
                                         gate=in_session)           # sohbet sürerken gürültüyü komut sanma
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

            if runtime.stop_event.is_set() or runtime.pause_listening.is_set() or not runtime.flags["mic"]:
                continue  # Discard recognition completed after shutdown/mute.

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
                        cmd = runtime.voice.listen(timeout=4, announce_fail=True, verbose=True, abort=runtime.mic_cancel)
                except Exception:
                    runtime._record_failure('main.py:listen_for_wake_word')
                    cmd = None
                if not cmd or not cmd.strip():
                    self.state["awake_until"] = runtime.time.time() + runtime.SESSION_SECONDS
                    continue
                cmd = cmd.strip()

            if runtime.stop_event.is_set() or runtime.pause_listening.is_set() or not runtime.flags["mic"]:
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
                if runtime._tr_lower(text).strip(" .!") in ("dur", "sus", "yeter", "stop"):
                    runtime.voice.stop_speaking()   # okunan yanıtı hemen keser
                    continue
                runtime.submit(text, "yazı")
