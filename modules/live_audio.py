"""Streaming filters and playback, separated from provider/session coordination."""
from modules.diagnostics import record_failure as _record_failure
import logging
import queue
import threading
import time
import numpy as np
log = logging.getLogger('jarvis.live.audio')
SEND_RATE = 16000

class _Resampler:
    """Mikrofonun kendi hızındaki sesi (44,1/48 kHz) 16 kHz'e düzgünce çevirir (akış hâlinde, kareler arası kesintisiz).
    Önce 7 kHz'te alçak geçiren filtre (pencereli sinc, örtüşme/bulanıklık olmasın), sonra hedef örnek noktalarında
    doğrusal ara değer. Windows'un eski (MME) 16 kHz dönüştürmesi sesi boğuklaştırıyordu."""

    def __init__(self, src: int, dst: int = SEND_RATE, taps: int = 63) -> None:
        self.src, self.dst = int(src), int(dst)
        self.step = self.src / self.dst
        n = np.arange(taps) - (taps - 1) / 2
        fc = 7000.0 / self.src
        h = 2 * fc * np.sinc(2 * fc * n) * np.blackman(taps)
        self.h = (h / h.sum()).astype(np.float64)
        self.tail = np.zeros(taps - 1)
        self.pos = 0.0                                   # bir sonraki çıktı örneğinin, filtrelenmiş akıştaki yeri

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.src == self.dst:
            return x.astype(np.int16)
        buf = np.concatenate([self.tail, x.astype(np.float64)])
        y = np.convolve(buf, self.h, mode="valid")     # len(y) == len(x)
        self.tail = buf[-(len(self.h) - 1):]
        idx = np.arange(self.pos, len(y) - 1, self.step)
        out = np.interp(idx, np.arange(len(y)), y) if len(idx) else np.zeros(0)
        self.pos = (idx[-1] + self.step - len(y)) if len(idx) else self.pos - len(y)
        return np.clip(np.round(out), -32768, 32767).astype(np.int16)


class _HighPass:
    """80 Hz altını kesen 2. dereceden filtre (Butterworth). Fan/masa uğultusu ve mikrofon titreşimi gibi alçak
    gürültüyü atar; konuşmaya dokunmaz (120 Hz'de kayıp %9, 200 Hz üstünde yok). 10 sn ses için ~2-3 ms işlem."""

    def __init__(self, f0: float = 80.0, fs: int = SEND_RATE, q: float = 0.7071) -> None:
        import math
        w = 2 * math.pi * f0 / fs
        al, c = math.sin(w) / (2 * q), math.cos(w)
        a0 = 1 + al
        self.b = ((1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0)
        self.a = (-2 * c / a0, (1 - al) / a0)
        self.z1 = self.z2 = 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        b0, b1, b2 = self.b
        a1, a2 = self.a
        z1, z2 = self.z1, self.z2
        out = [0.0] * len(x)
        for i, v in enumerate(x.tolist()):
            y = b0 * v + z1
            z1 = b1 * v - a1 * y + z2
            z2 = b2 * v - a2 * y
            out[i] = y
        self.z1, self.z2 = z1, z2
        return np.clip(np.round(out), -32768, 32767).astype(np.int16)


def _soft_limit(v: np.ndarray) -> np.ndarray:
    """Yükseltilmiş sesi patlatmadan sınırlar: 24000'e kadar olduğu gibi, üstünü yumuşakça 32767'ye bastırır."""
    a = np.abs(v)
    over = a > 24000
    if over.any():
        v = v.copy()
        v[over] = np.sign(v[over]) * (24000 + 8767 * np.tanh((a[over] - 24000) / 8767))
    return v


class _Player:
    """Modelden gelen sesi (24 kHz, 16 bit) çalar. clear() ile anında susturulabilir."""

    def __init__(self, runtime=None) -> None:
        if runtime is None:
            from modules import live as runtime
        self.runtime = runtime
        self.q: queue.Queue = queue.Queue()
        self.last_end = 0.0
        self.latency = 0.1
        self._busy = False
        self._stream = None
        self._vol_ok = False          # Python'un uygulama sesi %100'e çekildi mi
        self._vol_tries = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True, name="canli-hoparlor").start()

    def feed(self, pcm: bytes) -> None:
        step = 4800                                  # 100 ms'lik parçalar: clear() hemen etki etsin
        for i in range(0, len(pcm), step):
            self.q.put(pcm[i:i + step])
        self._busy = True

    def feed_now(self, pcm: bytes) -> None:
        """Ön tamponsuz, konuşma sayılmadan çalar (uyanma sesi)."""
        self.q.put(("now", pcm))

    def clear(self) -> None:
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def busy(self) -> bool:
        """Jarvis konuşuyor mu? Kuyruktaki uyanma sesi (feed_now) konuşma sayılmaz: mikrofon onun için kapanmasın."""
        if self._busy:
            return True
        with self.q.mutex:
            return any(not isinstance(c, tuple) for c in self.q.queue)

    def _open(self):
        import sounddevice as sd
        dev = self.runtime._cfg("output_device", None)
        if isinstance(dev, str) and dev.strip().isdigit():
            dev = int(dev)
        for d in (dev, None) if dev is not None else (None,):
            try:
                # latency="high": cihaz tamponu büyük olur, ağdan gelen sesin küçük gecikmeleri kesinti yapmaz
                st = sd.RawOutputStream(samplerate=self.runtime.RECV_RATE, channels=1, dtype="int16", device=d, latency="high")
                st.start()
                try:
                    self.latency = float(st.latency or 0.1)
                except (TypeError, ValueError):
                    pass
                return st
            except Exception:                         # noqa: BLE001  seçili hoparlör açılmazsa varsayılana dön
                _record_failure('modules/live_audio.py:_open')
        return None

    def _write(self, data: bytes, speech: bool = True) -> None:
        if not self.runtime.speak_allowed():                       # susturma açık: Gemini'nin sesi hoparlöre verilmez (yazı yine gelir)
            time.sleep(len(data) / (self.runtime.RECV_RATE * 2))   # zamanlama bozulmasın diye sesin süresi kadar bekle
            return
        try:
            if self._stream is None:
                self._stream = self._open()
            if self._stream is not None:
                self._stream.write(data)
                if speech and getattr(self, 'on_play', None):
                    try:
                        self.on_play()
                    except Exception:
                        _record_failure('modules/live_audio.py:play_timing')
                if not self._vol_ok and self._vol_tries < 20:
                    # ses oturumu Windows'ta ancak ses çalınmaya başlayınca görünür: ilk yazmadan SONRA dene
                    self._vol_tries += 1
                    self._vol_ok = self.runtime._own_volume_up()
        except Exception:                             # noqa: BLE001
            _record_failure('modules/live_audio.py:_write')
            self._stream = None
            time.sleep(0.5)

    def _run(self) -> None:
        """Her cümlenin başında kısa bir ön tampon (self.runtime.PREBUFFER sn) biriktirir: Gemini sesi düzensiz paketler halinde
        yollar; hemen çalmaya başlarsak paketler arası boşluk "kesik kesik" ses olur."""
        hold = bytearray()
        first = 0.0
        playing = False
        last_chunk = 0.0
        need = int(self.runtime.RECV_RATE * 2 * self.runtime.PREBUFFER)
        while True:
            try:
                chunk = self.q.get(timeout=0.05)
            except queue.Empty:
                now = time.monotonic()
                if hold and now - first > self.runtime.PREBUFFER_MAX:      # cümle kısaysa daha fazla bekleme
                    self._write(bytes(hold))
                    hold.clear()
                    playing, last_chunk = True, now
                elif playing and now - last_chunk > 0.25 and not hold:
                    playing = False                           # sessizlik: cümle bitti
                    self._busy = False
                    self.last_end = now
                continue
            if isinstance(chunk, tuple):
                self._write(chunk[1], speech=False)
                continue
            last_chunk = time.monotonic()
            if playing:
                self._write(chunk)
                continue
            if not hold:
                first = last_chunk
            hold.extend(chunk)
            if len(hold) >= need:
                self._write(bytes(hold))
                hold.clear()
                playing = True


