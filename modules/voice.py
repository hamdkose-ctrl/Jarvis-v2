from modules.diagnostics import record_failure as _record_failure
import array
import asyncio
import collections
import ctypes
import logging
import os
import queue
import re
import tempfile
import threading
import time

import edge_tts
import pyttsx3
import sounddevice as sd
import speech_recognition as sr

import config
from modules import privacy

LANGUAGE = config.LANGUAGE
INPUT_DEVICE = getattr(config, "INPUT_DEVICE", None)

RATE = 16000
CHUNK = 1024  # ~64 ms

TTS_VOICE = "tr-TR-AhmetNeural"   # erkek; kadın için: "tr-TR-EmelNeural"
TTS_RATE = "-8%"                  # varsayılan hız (sakin); kullanıcı kendi hızını profilinde ayarlar
# Kullanıcıların seçebildiği sesler: anahtar -> (konuşmada söylenen ad, edge-tts ses adı)
VOICES = {
    "tr_erkek": ("Kerem · Türkçe", "tr-TR-AhmetNeural"),
    "tr_kadin": ("Defne · Türkçe", "tr-TR-EmelNeural"),
    "ml_erkek": ("Liam · English", "en-US-AndrewMultilingualNeural"),   # Türkçe + İngilizce okur
    "ml_kadin": ("Olivia · English", "en-US-AvaMultilingualNeural"),
    "ml_erkek2": ("Noah · English", "en-US-BrianMultilingualNeural"),
    "ml_kadin2": ("Mia · English", "en-US-EmmaMultilingualNeural"),
}
PAUSE = 0.0                      # cümleler arası bekleme (saniye)

_rec = sr.Recognizer()
_fallback = None  # internet yoksa kullanılacak yerel ses
_stop_flag = threading.Event()   # stop_speaking() çağrıldı mı
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


def listen(timeout: int = 6, phrase_limit: int = 12, announce_fail: bool = False,
           verbose: bool = False, abort=None, cheap: bool = False, gate: bool = False,
           local: bool = False, on_captured=None) -> str | None:
    """Mikrofonu dinler, konuşma bitince metne çevirir. Anlaşılmazsa None.
    abort: threading.Event; kurulursa dinleme hemen bırakılır (Jarvis konuşmaya başlayacağı zaman)."""
    global last_noise
    pre = collections.deque(maxlen=5)   # konuşma başlamadan önceki ~0.3 sn
    frames, started, silent = [], False, 0
    max_silent = int(1.0 * RATE / CHUNK)   # 1 sn sessizlik = cümle bitti (kısa duraksamada kesmesin)

    with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=CHUNK,
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
    return recognize(b"".join(frames), announce_fail, cheap=cheap, gate=gate, local=local)


HINTS: list[str] = []          # main.py doldurur: asistanın adı, kullanıcılar, kişiler, sık kelimeler
DEFAULT_HINTS: list[str] = []   # hazır liste yok: Gemini gürültüden listedeki kelimeleri uyduruyordu
last_speech_end = 0.0          # kullanıcının konuşmasının bittiği an (gecikme ölçümü için)
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


def _off_notice(announce: bool) -> None:
    """Kapalı modda sesli komut gelince kullanıcıya (en fazla dakikada bir) neden duyulmadığını söyler."""
    global _last_off_notice
    if not announce or time.time() - _last_off_notice < 60:
        return
    _last_off_notice = time.time()
    m = "Yalnızca yerel" if privacy.mode() == "yerel" else "Gizli"
    try:
        speak(f"{m} modda sesin dışarı gitmemesi için sesli komut kapalı. Lütfen yazarak söyle.")
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
    global last_speech_end
    if not raw:
        return None
    last_speech_end = time.time()
    if local:
        from modules import local_stt
        # A local error propagates to the button handler, never to cloud fallback.
        text = _guarded(local_stt.transcribe(raw))
        if not text and announce_fail:
            speak("Anlayamadım, tekrar söyler misin?")
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
                speak("Anlayamadım, tekrar söyler misin?")
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
            speak("Anlayamadım, tekrar söyler misiniz?")
        return None
    except sr.RequestError as e:
        print(f"Ses tanıma servisine ulaşılamadı: {e}")
        return None


def _play_mp3(path: str):
    """Play one downloaded audio file; Windows MCI failures must not look successful."""
    mci = ctypes.windll.winmm.mciSendStringW
    mci("close jarvis_tts", None, 0, 0)  # best-effort stale alias cleanup
    opened = False
    try:
        code = mci(f'open "{path}" type mpegvideo alias jarvis_tts', None, 0, 0)
        if code:
            raise OSError(f"Windows ses çalma başlatılamadı (MCI hata kodu: {code}).")
        opened = True
        code = mci("play jarvis_tts wait", None, 0, 0)
        if code:
            raise OSError(f"Windows ses oynatma başarısız (MCI hata kodu: {code}).")
    finally:
        if opened:
            mci("close jarvis_tts", None, 0, 0)


def _clean(text: str) -> str:
    text = re.sub(r"[*#`_>]", "", text)
    text = re.sub(r"[,;:.]+(?=\s|$)", " ", text)   # cümle içi noktalamayı sil; 3.5 gibi sayılara dokunma
    return re.sub(r"\s+", " ", text).strip()


def stop_speaking():
    """Okunmakta olan sesi hemen keser (başka thread'den çağrılabilir)."""
    _stop_flag.set()
    try:
        from modules import live
        live.stop_playback()                 # canlı konuşma modunun sesini de keser
    except Exception:
        _record_failure('modules/voice.py:stop_speaking')
        pass
    try:
        ctypes.windll.winmm.mciSendStringW("stop jarvis_tts", None, 0, 0)
    except Exception:
        _record_failure('modules/voice.py:stop_speaking')
        pass
    if _fallback is not None:
        try:
            _fallback.stop()
        except Exception:
            _record_failure('modules/voice.py:stop_speaking')
            pass


def _chunks(text: str) -> list[str]:
    """Metni seslendirme parçalarına böler: ilk parça kısa (hemen konuşmaya başlansın), sonrakiler daha uzun."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+|\n+", text) if p.strip()]
    out: list[str] = []
    cur = ""
    for p in parts:
        cur = f"{cur} {p}".strip()
        if len(cur) >= (40 if not out else 220):
            out.append(cur)
            cur = ""
    if cur:
        if out and len(cur) < 30:
            out[-1] += " " + cur
        else:
            out.append(cur)
    return out


def _local_say(text: str) -> None:
    global _fallback
    if _fallback is None:
        _fallback = pyttsx3.init()
        _fallback.setProperty("rate", 135)
    _fallback.say(text)
    _fallback.runAndWait()


_seq = 0


def speak(text: str, voice: str | None = None, rate: int | None = None) -> str | None:
    """voice: edge-tts ses adı (yoksa varsayılan), rate: yüzde hız farkı, örn. 5 ya da -10.

    Hız için metin parça parça seslendirilir: ilk cümle hazır olunca hemen okunur, o okunurken sonraki parça hazırlanır."""
    global _seq
    _stop_flag.clear()
    raw = (text or "").strip()
    if not _clean(raw):
        return
    from modules import stt_guard
    stt_guard.note_said(_clean(raw))     # mikrofona geri dönerse komut sanılmasın
    if privacy.mode() == "yerel":
        _local_say(_clean(raw))     # Edge sesleri çevrimiçi: yalnızca yerel modda doğrudan Windows sesi kullanılır
        return
    voice = voice or TTS_VOICE
    rate_str = TTS_RATE if rate is None else f"{rate:+d}%"
    names = [voice, voice]  # Retry only the selected voice; never change it mid-answer.
    chunks = [c for c in (_clean(x) for x in _chunks(raw)) if c] or [_clean(raw)]
    _seq += 1
    tag = _seq
    q: queue.Queue = queue.Queue()
    finished = threading.Event()
    delivery_lock = threading.Lock()

    def cancelled():
        return finished.is_set() or _stop_flag.is_set() or _seq != tag

    def produce() -> None:
        for i, c in enumerate(chunks):
            if cancelled():     # susturuldu ya da yeni bir konuşma başladı
                break
            path = os.path.join(tempfile.gettempdir(), f"jarvis_tts_{tag}_{i}.mp3")
            err = None
            for name in names:
                if cancelled():
                    break
                try:
                    asyncio.run(edge_tts.Communicate(c, name, rate=rate_str).save(path))
                    err = None
                    break
                except Exception as e:      # noqa: BLE001
                    _record_failure('modules/voice.py:produce')
                    err = e
                    time.sleep(0.5)
            with delivery_lock:
                if cancelled() or err is not None:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    if err is not None and not cancelled():
                        q.put(("fail", " ".join(chunks[i:]), err))
                    break
                q.put(("play", path, None))
        q.put(("end", None, None))

    threading.Thread(target=produce, daemon=True).start()
    deadline = time.monotonic() + 45
    try:
        while True:
            if cancelled():
                break
            try:
                kind, val, err = q.get(timeout=0.1)
            except queue.Empty:
                if time.monotonic() >= deadline:
                    message = "Seçilen ses servisi yanıt vermedi; ses tercihin korundu. Yanıtı ekrandan okuyabilirsin."
                    print(message)
                    return message
                continue
            deadline = time.monotonic() + 45
            if kind == "end":
                break
            if kind == "fail":
                if not cancelled():
                    message = "Seçilen ses şu anda kullanılamadı; ses tercihin korundu. Yanıtı ekrandan okuyabilirsin."
                    print(message)
                    return message
                break
            try:
                if not cancelled():     # indirirken 'dur' denmişse çalma
                    global last_speech_end
                    if last_speech_end and time.time() - last_speech_end < 60:
                        _log.info("Süre: konuşman bittikten sonra cevabın sesi %.1f sn'de başladı",
                                  time.time() - last_speech_end)
                        last_speech_end = 0.0
                    try:
                        _play_mp3(val)
                    except OSError:
                        _record_failure('modules/voice.py:playback')
                        message = "Windows ses oynatıcısı sesi çalamadı. Windows çıkış cihazını, ses düzeyini ve Jarvis Konuşma ayarını kontrol et."
                        print(message)
                        return message
            finally:
                try:
                    os.remove(val)
                except OSError:
                    pass
            if cancelled():
                break
    finally:
        # Mark consumption complete before draining; a late download cannot publish
        # a file after cleanup and must remove its own temporary file instead.
        with delivery_lock:
            finished.set()
        while not q.empty():                    # susturulduysa hazırlanmış ama okunmamış parçaları temizle
            try:
                kind, val, _e = q.get_nowait()
            except queue.Empty:
                break
            if kind == "play":
                try:
                    os.remove(val)
                except OSError:
                    pass
