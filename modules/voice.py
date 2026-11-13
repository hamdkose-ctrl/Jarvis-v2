from modules.diagnostics import record_failure as _record_failure
import array
import collections
import logging
import re
import time

import sounddevice as sd
import speech_recognition as sr

import config
from modules import privacy

LANGUAGE = config.LANGUAGE
INPUT_DEVICE = getattr(config, "INPUT_DEVICE", None)

RATE = 16000
CHUNK = 1024  # ~64 ms

# Kullanıcıların seçebildiği sesler: anahtar -> (konuşmada söylenen ad, edge-tts ses adı)
VOICES = {
    "tr_erkek": ("Kerem · Türkçe", "tr-TR-AhmetNeural"),
    "tr_kadin": ("Defne · Türkçe", "tr-TR-EmelNeural"),
    "ml_erkek": ("Liam · English", "en-US-AndrewMultilingualNeural"),   # Türkçe + İngilizce okur
    "ml_kadin": ("Olivia · English", "en-US-AvaMultilingualNeural"),
    "ml_erkek2": ("Noah · English", "en-US-BrianMultilingualNeural"),
    "ml_kadin2": ("Mia · English", "en-US-EmmaMultilingualNeural"),
}

_rec = sr.Recognizer()
# The Google web service used to be awaited with no bound at all: a hung request
# kept the engine loop (and, until the capture lock was narrowed, the microphone)
# waiting for as long as the server kept the socket open. `urlopen` raises the
# `RequestError` that `recognize` already reports as "service unreachable".
_rec.operation_timeout = 12
last_noise: float | None = None   # son dinlemedeki ortam gürültüsü (main.py sessiz mikrofonu algılamak için)


def _level(data: bytes) -> float:
    samples = array.array("h", data)
    return sum(abs(s) for s in samples) / max(len(samples), 1)


_warned_device = False


def _input_device():
    """config.INPUT_DEVICE: None (varsayılan), cihaz numarası ya da ad parçası."""
    global _warned_device
    dev = INPUT_DEVICE
    if dev is None or isinstance(dev, int):
        return dev
    matches = [(i, d) for i, d in enumerate(sd.query_devices())
               if d["max_input_channels"] > 0 and str(dev).casefold() in d["name"].casefold()]
    # MME ses sürücüsü 16 kHz'i sorunsuz kabul eder, önce onu dene
    matches.sort(key=lambda m: sd.query_hostapis(m[1]["hostapi"])["name"] != "MME")
    if not matches:
        if not _warned_device:
            print(f"[Uyarı] '{dev}' adlı mikrofon bulunamadı, varsayılan kullanılıyor.")
            _warned_device = True
        return None
    return matches[0][0]


def capture(timeout: int = 6, phrase_limit: int = 12, verbose: bool = False,
            abort=None, on_captured=None) -> bytes | None:
    """Record one utterance from the physical microphone and hand back its PCM.

    The stream is closed when this returns, so the device is free while the
    recording is still only bytes. Turning those bytes into text is `recognize`,
    a model or network wait, so the callers that own `runtime.audio_lock` keep it
    over this call and release it before that one instead of holding the only
    capture device for as long as a provider takes to answer. None means nothing
    was heard or the wait was aborted.
    """
    global last_noise
    pre = collections.deque(maxlen=5)   # konuşma başlamadan önceki ~0.3 sn
    frames, started, silent = [], False, 0
    max_silent = int(1.0 * RATE / CHUNK)   # 1 sn sessizlik = cümle bitti (kısa duraksamada kesmesin)

    # Actual PortAudio capture only: recognition waits never own the mic lease.
    # Unit/synthetic captures without a registered hardware VoiceLane retain
    # their existing no-device-lease behavior.
    from contextlib import nullcontext
    from modules import voice_runtime
    resource_scope = nullcontext()
    if voice_runtime.active() is not None:
        from modules import interactive_resource_gate
        resource_scope = interactive_resource_gate.claim("stt", owner="device")
    with resource_scope, sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK,
                                           device=_input_device()) as stream:
        noise = [_level(bytes(stream.read(CHUNK)[0])) for _ in range(3)]   # ~0.2 sn
        noise_avg = min(sum(noise) / len(noise), 600)   # konuşma hemen başlasa da eşik şişmesin
        threshold = max(noise_avg * 2.5, 400)
        last_noise = noise_avg
        if verbose:
            print(f"🎤 Dinliyorum... (gürültü: {noise_avg:.0f}, eşik: {threshold:.0f})", flush=True)
        start = time.time()

        while True:
            if abort is not None and abort.is_set():
                return None
            data = bytes(stream.read(CHUNK)[0])
            lvl = _level(data)
            if not started:
                pre.append(data)
                if lvl > threshold:
                    started = True
                    frames.extend(pre)
                elif time.time() - start > timeout:
                    return None
            else:
                frames.append(data)
                silent = silent + 1 if lvl < threshold else 0
                if silent >= max_silent or len(frames) * CHUNK / RATE > phrase_limit:
                    break

    if abort is not None and abort.is_set():
        return None
    if on_captured is not None:             # kayıt bitti, yazıya çevrilirken arayüz "dinliyorum"da kalmasın
        on_captured()
    return b"".join(frames)


def listen(timeout: int = 6, phrase_limit: int = 12, announce_fail: bool = False,
           verbose: bool = False, abort=None, cheap: bool = False, gate: bool = False,
           local: bool = False, on_captured=None) -> str | None:
    """Mikrofonu dinler, konuşma bitince metne çevirir. Anlaşılmazsa None.
    abort: threading.Event; kurulursa dinleme hemen bırakılır (Jarvis konuşmaya başlayacağı zaman)."""
    raw = capture(timeout=timeout, phrase_limit=phrase_limit, verbose=verbose,
                  abort=abort, on_captured=on_captured)
    if raw is None:
        return None
    return recognize(raw, announce_fail, cheap=cheap, gate=gate, local=local)


HINTS: list[str] = []          # main.py doldurur: asistanın adı, kullanıcılar, kişiler, sık kelimeler
DEFAULT_HINTS: list[str] = []   # hazır liste yok: Gemini gürültüden listedeki kelimeleri uyduruyordu
_log = logging.getLogger("jarvis")


def _google_text(audio) -> str:
    """Google'ın ücretsiz tanıması; konuşma yoksa boş döner (gürültü süzgeci olarak da kullanılır)."""
    if privacy.mode() in ("gizli", "yerel"):
        return ""
    try:
        return _rec.recognize_google(audio, language=LANGUAGE) or ""   # type: ignore[reportAttributeAccessIssue]
    except sr.UnknownValueError:
        return ""


def _engine() -> str:
    """Yazıya çevirme: 'gemini' (isabetli, varsayılan), 'google' (eski, ücretsiz web servisi) ya da 'off'.

    Gizli ve yalnızca-yerel modda ses HİÇBİR servise gönderilmez ('off'): bu bilgisayarda çevrimdışı ses tanıma
    olmadığı için sesli komut bu modlarda kapalıdır, komutlar yazıyla verilir. (Eskiden bu modlarda Google'ın
    web servisine geçiliyordu; yani "buluta hiçbir şey gitmez" denirken ses Google'a gidiyordu.)"""
    if privacy.mode() in ("gizli", "yerel"):
        return "off"
    from modules import llm
    if not llm.gemini_aux_allowed():
        return 'google'
    e = str(config.load_settings().get("stt_engine") or "gemini")
    return "google" if e == "google" else "gemini"


_last_off_notice = 0.0


def _say_feedback(text: str) -> None:
    """STT spoken feedback uses the single voice owner, never a local player."""
    from modules import voice_runtime
    voice_runtime.announce_active(text, background=False)


def _off_notice(announce: bool) -> None:
    """Kapalı modda sesli komut gelince kullanıcıya (en fazla dakikada bir) neden duyulmadığını söyler."""
    global _last_off_notice
    if not announce or time.time() - _last_off_notice < 60:
        return
    _last_off_notice = time.time()
    m = "Yalnızca yerel" if privacy.mode() == "yerel" else "Gizli"
    try:
        message = f"{m} modda sesin dışarı gitmemesi için sesli komut kapalı. Lütfen yazarak söyle."
        from modules import voice_runtime
        voice_runtime.announce_active(message)
    except Exception:   # noqa: BLE001
        _record_failure('modules/voice.py:_off_notice')
        pass


def _guarded(text: str | None) -> str | None:
    """Yabancı/uydurma söz ya da Jarvis'in kendi sesinin yankısı ise None (işlem yapılmaz, tekrar istenir)."""
    if not text:
        return text
    from modules import stt_guard
    why = stt_guard.reject(text)
    if why:
        _log.info("Duyulan söz atıldı (%s): %d karakter", "yabancı/gürültü" if why == "foreign" else "yankı", len(text))
        return None
    return text


def recognize(raw: bytes, announce_fail: bool = False, cheap: bool = False, gate: bool = False,
              local: bool = False) -> str | None:
    """gate=True: "Hey Jarvis" denmeden dinlenen seslerde (sohbet devam ederken) önce gerçekten konuşma var mı diye bakılır;
    gürültü Gemini'ye "Hitachi" gibi uydurma bir komut olarak yazdırılmasın."""
    """Kaydedilmiş sesi (16 kHz, 16 bit) yazıya çevirir: önce Gemini (kelime ipuçlarıyla), olmazsa Google. Anlaşılmazsa None."""
    if not raw:
        return None
    if local:
        from modules import local_stt
        # A local error propagates to the button handler, never to cloud fallback.
        text = _guarded(local_stt.transcribe(raw))
        if not text and announce_fail:
            _say_feedback("Anlayamadım, tekrar söyler misin?")
        return text
    if _engine() == "off":                       # gizli / yalnızca-yerel: ses hiçbir servise gönderilmez
        _log.info("Ses yazıya çevrilmedi: %s modda ses dışarı gönderilmez", privacy.mode())
        _off_notice(not cheap)
        return None
    audio = sr.AudioData(raw, RATE, 2)
    if _engine() == "gemini" and not cheap:     # cheap: ortamda ad aranırken (her ses Gemini'ye gitmesin)
        google_future = None
        if gate:                                 # Google'ın gürültü süzgeci, Gemini ile aynı anda (bekleme eklemez)
            import concurrent.futures as cf
            google_future = cf.ThreadPoolExecutor(max_workers=1).submit(_google_text, audio)
        try:
            from modules import llm
            name = str(getattr(config, "ASSISTANT_NAME", "Jarvis")).lower()
            words = list(dict.fromkeys([h for h in HINTS if h.lower() != name] + DEFAULT_HINTS + [w.strip() for w in str(
                config.load_settings().get("stt_words") or "").split(",") if w.strip()]))
            t0 = time.time()
            text = llm.transcribe(data=audio.get_wav_data(), hints=words).strip().strip('"“”')
            _log.info("İşlem kaydı: %s", 'modules/voice.py:recognize')
            if google_future is not None:
                try:
                    heard = google_future.result(timeout=6)
                except Exception:   # noqa: BLE001
                    _record_failure('modules/voice.py:recognize')
                    heard = "?"                  # Google'a ulaşılamadı: süzgeçsiz devam
                if not heard:
                    _log.info("İşlem kaydı: %s", 'modules/voice.py:recognize')
                    return None
            if text and not re.fullmatch(r"[\W_]*", text) and _guarded(text):
                return text
            print("(ses anlaşılamadı)")
            if announce_fail:
                _say_feedback("Anlayamadım, tekrar söyler misin?")
            return None
        except Exception as e:  # noqa: BLE001 - kota/internet: eski yönteme düş
            _record_failure('modules/voice.py:recognize')
    try:
        t0 = time.time()
        text = _rec.recognize_google(audio, language=LANGUAGE)  # type: ignore[reportAttributeAccessIssue]
        _log.info("İşlem kaydı: %s", 'modules/voice.py:recognize')
        if not _guarded(text):
            raise sr.UnknownValueError()
        return text
    except sr.UnknownValueError:
        print("(ses anlaşılamadı)")
        if announce_fail:
            _say_feedback("Anlayamadım, tekrar söyler misiniz?")
        return None
    except sr.RequestError as e:
        print(f"Ses tanıma servisine ulaşılamadı: {e}")
        return None


def stop_speaking():
    """Okunmakta olan sesi hemen keser (başka thread'den çağrılabilir).

    Tek ses sahibi (Voice Core) üzerinden keser; web susturma, acil durum, PC rehberi
    ve sesli komutların ortak girişidir. İkinci bir oynatıcı açmaz veya seçmez ve
    hiçbir Core işini/goal'ünü iptal etmez; explicit dur/stop ayrı Core komutudur.
    """
    try:
        from modules import voice_runtime
        voice_runtime.interrupt_active()
    except Exception:
        _record_failure('modules/voice.py:stop_voice_core')
