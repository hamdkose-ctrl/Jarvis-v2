"""Ses inerken çalan Windows oynatıcı (waveOut), winsound'un yerine değil yanına.

Neden: `winsound.PlaySound` bir dosyayı baştan sona ister, yani cevabın sesi
tamamen indirilmeden çalma başlamıyor. Ölçüm (21 Kasım): 12,5 saniyelik bir
cümlenin ilk sesi 2858 ms'de başlıyordu — sesin kendisi hazır olana kadar
beklendiği için. waveOut'a PCM parçaları yazmak, ilk ~150 ms ses geldiği anda
çalmayı başlatır.

Bu modül bilinçli olarak küçük: cihazı aç, tamamlanan tamponları yeniden
doldur, bitince kapat. Zamanlama cihaz saatinden gelir (winsound'da olduğu gibi),
CPU yükü çalmayı uzatmaz.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
import time

from modules.diagnostics import record_failure as _record_failure

_WAVE_MAPPER = ctypes.c_uint(-1)
_CALLBACK_NULL = 0
_WAVE_FORMAT_PCM = 1
_WHDR_DONE = 0x00000001
_MMSYSERR_NOERROR = 0


class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wt.WORD), ("nChannels", wt.WORD),
                ("nSamplesPerSec", wt.DWORD), ("nAvgBytesPerSec", wt.DWORD),
                ("nBlockAlign", wt.WORD), ("wBitsPerSample", wt.WORD),
                ("cbSize", wt.WORD)]


class _WAVEHDR(ctypes.Structure):
    _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wt.DWORD),
                ("dwBytesRecorded", wt.DWORD), ("dwUser", ctypes.c_void_p),
                ("dwFlags", wt.DWORD), ("dwLoops", wt.DWORD),
                ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_void_p)]


def _winmm():
    return ctypes.windll.winmm


class StreamPlayer:
    """PCM parçalarını sırayla çalar; ilk parça geldiği anda ses başlar."""

    def __init__(self, rate: int = 24000, channels: int = 1, width: int = 2,
                 buffer_ms: int = 100, buffers: int = 6):
        self.rate, self.channels, self.width = rate, channels, width
        self._handle = ctypes.c_void_p()
        self._format = _WAVEFORMATEX(
            _WAVE_FORMAT_PCM, channels, rate, rate * channels * width,
            channels * width, width * 8, 0)
        code = _winmm().waveOutOpen(ctypes.byref(self._handle), _WAVE_MAPPER,
                                    ctypes.byref(self._format), 0, 0, _CALLBACK_NULL)
        if code != _MMSYSERR_NOERROR:
            raise OSError(f"waveOutOpen başarısız (kod {code})")
        self._size = max(int(rate * buffer_ms / 1000) * channels * width, channels * width * 64)
        self._slots: list[dict] = [
            {"buf": ctypes.create_string_buffer(self._size), "hdr": _WAVEHDR(), "busy": False}
            for _ in range(buffers)
        ]
        self._lock = threading.Lock()
        self._closed = False
        self._started = False
        self._stopped = False
        self._cursor = 0
        self._pending = b""
        self.played_bytes = 0

    # --- iç -----------------------------------------------------------------
    def _free_slot(self):
        for slot in self._slots:
            if not slot["busy"]:
                return slot
            if slot["hdr"].dwFlags & _WHDR_DONE:
                _winmm().waveOutUnprepareHeader(self._handle, ctypes.byref(slot["hdr"]),
                                                ctypes.sizeof(_WAVEHDR))
                slot["busy"] = False
                return slot
        return None

    def _write(self, audio: bytes) -> bool:
        slot = None
        deadline = time.monotonic() + 5.0
        while slot is None and not self._stopped and time.monotonic() < deadline:
            slot = self._free_slot()
            if slot is None:
                time.sleep(0.002)
        if slot is None:
            return False
        ctypes.memmove(slot["buf"], audio, len(audio))
        slot["hdr"] = _WAVEHDR()
        slot["hdr"].lpData = ctypes.cast(slot["buf"], ctypes.c_void_p)
        slot["hdr"].dwBufferLength = len(audio)
        _winmm().waveOutPrepareHeader(self._handle, ctypes.byref(slot["hdr"]),
                                      ctypes.sizeof(_WAVEHDR))
        code = _winmm().waveOutWrite(self._handle, ctypes.byref(slot["hdr"]),
                                     ctypes.sizeof(_WAVEHDR))
        if code != _MMSYSERR_NOERROR:
            raise OSError(f"waveOutWrite başarısız (kod {code})")
        slot["busy"] = True
        return True

    # --- dışarıya açık ------------------------------------------------------
    def write(self, audio: bytes) -> None:
        """PCM parçası ekle; tamponlar dolduysa bekler."""
        if self._closed or self._stopped or not audio:
            return
        with self._lock:
            data = self._pending + audio
            step = self._size
            while len(data) >= step:
                if not self._write(data[:step]):
                    return
                self.played_bytes += step
                data = data[step:]
            self._pending = data

    def flush(self) -> None:
        """Kalan yarım tamponu yaz."""
        with self._lock:
            if self._pending and not self._stopped:
                self._write(self._pending)
                self.played_bytes += len(self._pending)
                self._pending = b""

    def drain(self, cancel=None, deadline: float = 120.0) -> None:
        """Cihaz tamponları boşalana kadar bekle (çalma gerçekten bitti)."""
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            if self._stopped or self._closed:
                return
            if cancel is not None and cancel.is_set():
                self.stop()
                return
            if all((not s["busy"]) or (s["hdr"].dwFlags & _WHDR_DONE) for s in self._slots):
                return
            time.sleep(0.005)

    def stop(self) -> None:
        """Sesi hemen kes (iptal). Cihaz saatini sıfırlar."""
        if self._closed or self._stopped:
            return
        self._stopped = True
        try:
            _winmm().waveOutReset(self._handle)
        except Exception:
            _record_failure("modules/voice_stream.py:reset")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.stop()
            for slot in self._slots:
                if slot["busy"]:
                    _winmm().waveOutUnprepareHeader(self._handle, ctypes.byref(slot["hdr"]),
                                                    ctypes.sizeof(_WAVEHDR))
            _winmm().waveOutClose(self._handle)
        except Exception:
            _record_failure("modules/voice_stream.py:close")
