"""İnternetsiz uyandırma: "Hey Jarvis" bilgisayarın kendisinde (openWakeWord) algılanır.

Ortamdaki konuşmalar internete gönderilmez; yalnızca "Hey Jarvis"ten sonra söylenen komut yazıya çevrilmek için gider.
Ayarlar → Ses → "Uyandırma yöntemi":
  auto    : ad "Jarvis" ise internetsiz, başka bir ad verildiyse Google (önerilen)
  offline : her zaman internetsiz ("Hey Jarvis")
  google  : eski yöntem, her ses Google'da yazıya çevrilip ad aranır
Gerekli parça kurulamazsa ya da çalışmazsa Jarvis kendiliğinden Google yöntemine döner.
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import collections
import logging

try:
    import numpy as np
except ImportError:                           # numpy yoksa dinleyici zaten çalışmaz (status: failed)
    np = None
import threading
import time

from config import load_settings

RATE = 16000
FRAME = 1280                 # 80 ms: openWakeWord'ün beklediği parça
THRESHOLD = 0.5              # algılama eşiği (0-1); yükseldikçe yanlış uyanma azalır, kaçırma artar
MODES = ("auto", "offline", "google")

_model = None
_state = "off"               # off | loading | ready | failed
_error = ""
_lock = threading.Lock()
log = logging.getLogger("jarvis")


def mode() -> str:
    m = str(load_settings().get("wake_engine") or "auto")
    return m if m in MODES else "auto"


def _is_jarvis(wake_word: str) -> bool:
    w = " ".join((wake_word or "").lower().replace(",", " ").split())
    return w in ("jarvis", "hey jarvis", "hei jarvis", "hay jarvis")


def wanted(wake_word: str) -> bool:
    """Ayarlara göre internetsiz dinleyici kullanılmalı mı?"""
    m = mode()
    if m == "google":
        return False
    return m == "offline" or _is_jarvis(wake_word)


def ready() -> bool:
    """Dinleyici hazırsa True. Hazır değilse arka planda yüklemeyi başlatır (bu arada Google yöntemi kullanılır)."""
    if _state == "ready":
        return True
    if _state == "off":
        with _lock:
            if _state == "off":
                _set("loading")
                threading.Thread(target=_load, daemon=True, name="uyandirma-yukle").start()
    return False


def _set(state: str, err: str = "") -> None:
    global _state, _error
    _state, _error = state, err
    log.info("“Hey Jarvis” dinleyicisi: %s%s", state, f" ({err})" if err else "")


def _load() -> None:
    global _model
    try:
        import openwakeword
        import openwakeword.utils
        from openwakeword.model import Model
    except Exception as e:      # noqa: BLE001
        _record_failure('modules/wakeword.py:_load')
        _set("failed", "Gerekli parça kurulu değil; Jarvis klasöründeki kurulum.bat'ı bir kez çalıştır. "
                       f"({type(e).__name__}: {e})")
        return
    prepared = ""
    try:
        try:
            from modules.wakeword_models import ensure_models
            ensure_models()
        except Exception as e:       # noqa: BLE001
            _record_failure('modules/wakeword.py:_load')
            # Yok sayılan bu neden daha önce yalnız "dinleyici başlatılamadı" olarak
            # görünüyordu: ağ yok, klasör yazılamıyor ve bozuk dosya aynı mesajı
            # veriyordu. Modeller zaten inmişse yükleme yine de başarılı olur, o
            # yüzden neden ancak Model de kurulamazsa gösterilir. Anahtar, token ya
            # da kullanıcı metni bu metnin parçası değildir.
            prepared = f"Model hazırlanamadı ({type(e).__name__}: {str(e)[:120]}). "
        _model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        _set("ready")
    except Exception as e:      # noqa: BLE001
        _record_failure('modules/wakeword.py:_load')
        _set("failed", prepared + f"İnternetsiz dinleyici başlatılamadı ({type(e).__name__}: {e})")


def status() -> dict:
    return {"mode": mode(), "state": _state, "error": _error}


def _rms(x) -> float:
    import numpy as np
    return float(np.abs(x.astype(np.int32)).mean()) if len(x) else 0.0


# openWakeWord skoru mikrofona/odaya göre değişiyor. Yakın testte 0.22 ile 6/10, biraz uzaktan
# 4/10 görüldü. Dengeli seviye 0.18'e çekildi. Tek çok düşük kareyle yanlış uyanmak yerine
# art arda iki "yakın skor" da kabul edilir (aşağıda soft_hits); kullanıcı 1-5 ayarlayabilir.
SENSITIVITY = {1: 0.55, 2: 0.36, 3: 0.18, 4: 0.14, 5: 0.10}   # 1: zor uyanır … 5: çok kolay uyanır


def sensitivity_threshold() -> float:
    try:
        lvl = int(load_settings().get("wake_sensitivity") or 3)
    except (TypeError, ValueError):
        lvl = 3
    return SENSITIVITY.get(min(5, max(1, lvl)), 0.18)


def score(frame) -> float:
    """Tek bir 80 ms'lik karede (1280 örnek, 16 kHz, int16) "Hey Jarvis" olasılığı. Hazır değilse 0."""
    if _state != "ready" or _model is None:
        return 0.0
    return max(_model.predict(frame).values(), default=0.0)


def reset() -> None:
    """Aynı "Hey Jarvis" iki kez sayılmasın."""
    if _model is not None:
        _model.reset()


def wait(should_stop, on_wake=None, max_seconds: float = 20.0, capture: bool = True, min_threshold: float = 0.0):
    """Mikrofonu dinler, "Hey Jarvis" duyulana kadar bekler.

    Dönüş: None -> duyulmadı (süre doldu ya da should_stop() doğru oldu; çağıran döngü yeniden çağırır)
           bytes -> uyandı; ardından söylenen komutun sesi (16 kHz, 16 bit). Komut söylenmediyse b"".
    Ses bu fonksiyonda bilgisayardan çıkmaz; komut sesini yazıya çevirmek çağıranın işidir.
    """
    import numpy as np
    import sounddevice as sd

    from modules import voice

    levels: collections.deque = collections.deque(maxlen=40)       # son ~3 sn'nin ses seviyeleri (gürültü tahmini)
    threshold = max(sensitivity_threshold(), min_threshold)
    soft_threshold = max(0.08, threshold * 0.68)
    soft_hits = 0
    end = time.time() + max_seconds
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME,
                        device=voice._input_device()) as stream:
        while time.time() < end:
            if should_stop():
                return None
            data, _ = stream.read(FRAME)
            x = np.asarray(data).reshape(-1)
            levels.append(_rms(x))
            voice.last_noise = min(levels)        # sessiz mikrofon uyarısı için (main.py)
            scores = _model.predict(x)
            sc = max(scores.values(), default=0.0)
            soft_hits = soft_hits + 1 if sc >= soft_threshold else 0
            if sc < threshold and soft_hits < 2:
                continue
            soft_hits = 0
            _model.reset()                        # aynı "Hey Jarvis" iki kez sayılmasın
            if on_wake:
                try:
                    on_wake()
                except Exception:   # noqa: BLE001
                    _record_failure('modules/wakeword.py:wait')
                    pass
            _beep()
            if not capture:
                return b""                        # yalnızca uyandı mı (konuşurken söz kesme için)
            _skip_wake_tail(stream, levels)       # "Jarvis"in sonu ve bip kayda girmesin
            return _capture(stream, levels, should_stop)
    return None


def _skip_wake_tail(stream, levels) -> None:
    """Uyanma bazen "Jarvis" bitmeden olur. Sözün sonu (kısa bir sessizlik) gelene kadar, en fazla ~1 sn, atla."""
    srt = sorted(levels) or [0.0]
    quiet = max(min(srt[len(srt) // 5], 600) * 2.5, 400)
    calm = 0
    for i in range(13):                       # 13 x 80 ms ≈ 1 sn
        data, _ = stream.read(FRAME)
        lvl = _rms(np.asarray(data).reshape(-1))
        if i >= 3:                            # bip sesi (~0,1 sn) ve ilk kısım her zaman atlanır
            calm = calm + 1 if lvl < quiet else 0
            if calm >= 2:                     # ~160 ms sessizlik: uyanma sözü bitti
                return
        if lvl >= quiet and i >= 6:
            return                            # duraksamadan komuta geçti: komutu kaçırmamak için hemen kaydet


def _beep() -> None:
    """Kısa "dıt": Jarvis'in uyandığını ve komutu dinlediğini duyarsın.

    Ayarlar › Ses › Uyanma sesi (`wake_beep`) bunu kapatırsa hiçbir ses çalmaz;
    varsayılan açıktır. Bip kaçırılırsa dinleme yine başlar — bildirim, iş değil.
    """
    if load_settings().get("wake_beep", True) is False:
        return
    try:
        import winsound
        winsound.Beep(1200, 90)
    except Exception:       # noqa: BLE001
        _record_failure('modules/wakeword.py:_beep')
        pass


def _capture(stream, levels, should_stop, start_timeout: float = 6.0, phrase_limit: float = 12.0) -> bytes:
    """Uyandıktan sonra komutu aynı mikrofon akışından kaydeder (komutun başı kaçmasın), sessizlikte durur."""
    import numpy as np
    srt = sorted(levels) or [0.0]
    noise = min(srt[len(srt) // 5], 600)
    threshold = max(noise * 2.5, 400)
    frames: list[bytes] = []
    started, silent, waited = False, 0, 0.0
    max_silent = int(1.0 * RATE / FRAME) + 1          # ~1 sn sessizlik = komut bitti (kısa duraksamada kesmesin)
    while True:
        if should_stop():
            return b""
        data, _ = stream.read(FRAME)
        x = np.asarray(data).reshape(-1)
        lvl = _rms(x)
        if not started:
            frames = (frames + [x.tobytes()])[-3:]     # konuşma başlamadan önceki ~0,25 sn de kayda girsin
            if lvl > threshold:
                started = True
            else:
                waited += FRAME / RATE
                if waited > start_timeout:
                    return b""
            continue
        frames.append(x.tobytes())
        silent = silent + 1 if lvl < threshold else 0
        if silent >= max_silent or len(frames) * FRAME / RATE > phrase_limit:
            return b"".join(frames)
