"""Edge TTS bağlantısını düşünme sırasında açık tutan küçük yönetici.

Ölçüm (21 Kasım, bu makine):

    bağlantı kurma (WS + imzalı jeton)   1337 ms
    hazır bağlantıda ilk ses              414-481 ms
    24 sn boşta kalmış bağlantıda ilk ses 1437 ms   (jeton/socket tazeleniyor)

Yani Jarvis her cevapta ~1,3 saniyeyi yalnızca el sıkışmaya veriyor. Bağlantı,
kullanıcının komutu yazıya çevrildiği anda açılırsa bu süre modelin düşünme
zamanının içinde kaybolur ve ilk ses ~0,5 saniyede başlar.

Bu modül tek bir arka plan iş parçacığında kendi olay döngüsünü tutar (edge_tts
çağrı başına `asyncio.run` kullanıyor, sıcak bir soket orada yaşayamaz) ve:

- `warm()`     : bağlantıyı (gerekirse) açar, TTL içinde yeniden kullanır
- `synthesize()`: metni sıcak soketten üretir; herhangi bir aksaklıkta `None`
                  döner ve çağıran bugünkü edge_tts yoluna düşer

Sıcak yolun bozulması sesi düşürmez: geri dönüş yolu aynen duruyor.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid

from modules.diagnostics import record_failure as _record_failure

# Bağlantı bu süreden uzun boşta kalırsa tazelenir; 24 sn sonra ölçülen 1437 ms
# tam olarak bunun cezasıydı.
WARM_TTL = 8.0
_AUDIO_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
_OPEN_TIMEOUT = 8.0
_TURN_TIMEOUT = 30.0


def split_binary(message: bytes) -> tuple[dict[bytes, bytes], bytes]:
    """Edge'in ikili mesajını (başlık, ses verisi) olarak ayırır.

    İlk iki bayt başlığın uzunluğudur; sonrası MP3. Ayırmadan çözücüye vermek
    her parçanın başında çöp üretiyor — kullanıcı bunu "bozuk ses" olarak duydu.
    """
    if len(message) < 2:
        raise ValueError("binary message missing header length")
    header_length = int.from_bytes(message[:2], "big")
    if header_length > len(message):
        raise ValueError("header length beyond message")
    headers: dict[bytes, bytes] = {}
    for line in message[:header_length].split(b"\r\n"):
        if b":" in line:
            name, _, value = line.partition(b":")
            headers[name.strip()] = value.strip()
    return headers, message[header_length + 2:]


def ssml(text: str, voice: str, rate: str, pitch: str) -> str:
    """Edge'in beklediği SSML. Metin kaçışlanır: seslendirme metni değiştirmez."""
    safe = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
        f"<voice name='{voice}'>"
        f"<prosody pitch='{pitch}' rate='{rate}' volume='+0%'>{safe}</prosody>"
        "</voice></speak>"
    )


class _Warm:
    """Tek arka plan döngüsü + en çok bir sıcak bağlantı."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session = None
        self._ws = None
        self._used_at = 0.0
        self._closed = False
        # Tek soket, tek tur: iki cümle aynı anda gönderilirse Edge'in tur
        # sınırları karışıyor ve istek RuntimeError ile düşüyor (ölçüldü).
        self._turn_lock: asyncio.Lock | None = None

    # --- altyapı ---------------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop | None:
        with self._lock:
            if self._closed:
                return None
            if self._loop is not None and not self._loop.is_closed():
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=self._serve, args=(loop,), daemon=True,
                                      name="jarvis-edge-warm")
            self._loop = loop
            self._thread = thread
        try:
            thread.start()
        except Exception:
            _record_failure("modules/voice_edge_warm.py:thread")
            return None
        return loop

    @staticmethod
    def _serve(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _run(self, coro, timeout: float):
        loop = self._ensure_loop()
        if loop is None:
            return None
        try:
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)
        except Exception:
            # Zaman aşımı/iş parçacığı hatası: çağıran bugünkü yola düşer.
            _record_failure("modules/voice_edge_warm.py:run")
            return None

    async def _drop(self) -> None:
        ws, session = self._ws, self._session
        self._ws = self._session = None
        for closable in (ws, session):
            if closable is None:
                continue
            try:
                await closable.close()
            except Exception:
                # Kapanmayan soket zaten işe yaramaz; yenisi açılır.
                _record_failure("modules/voice_edge_warm.py:close_one")

    # --- sıcak bağlantı --------------------------------------------------
    async def _connect(self):
        from edge_tts.communicate import connect_id
        from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
        from edge_tts.drm import DRM
        import aiohttp

        url = (f"{WSS_URL}&ConnectionId={connect_id()}"
               f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
               f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}")
        session = aiohttp.ClientSession(trust_env=True)
        try:
            ws = await session.ws_connect(url, compress=15,
                                          headers=DRM.headers_with_muid(WSS_HEADERS),
                                          max_msg_size=0)
        except Exception:
            # Bağlantı kurulamadı: oturumu kapat, çağıran sıcak yolu bırakır.
            _record_failure("modules/voice_edge_warm.py:ws_connect")
            await session.close()
            raise
        self._session, self._ws = session, ws
        self._used_at = time.monotonic()

    async def _ensure_open(self) -> bool:
        if self._ws is not None and not getattr(self._ws, "closed", False):
            if time.monotonic() - self._used_at <= WARM_TTL:
                return True
            await self._drop()
        await self._connect()
        return True

    async def _turn(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        if self._turn_lock is None:
            self._turn_lock = asyncio.Lock()
        async with self._turn_lock:
            return await self._turn_locked(text, voice, rate, pitch)

    async def _turn_locked(self, text: str, voice: str, rate: str, pitch: str) -> bytes:
        request_id = uuid.uuid4().hex
        stamp = time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)",
                              time.gmtime())
        config = {"context": {"synthesis": {"audio": {
            "metadataoptions": {"sentenceBoundaryEnabled": "false",
                                "wordBoundaryEnabled": "false"},
            "outputFormat": _AUDIO_FORMAT}}}}
        await self._ws.send_str(
            f"X-Timestamp:{stamp}\r\nContent-Type:application/json; charset=utf-8\r\n"
            f"Path:speech.config\r\n\r\n" + json.dumps(config))
        await self._ws.send_str(
            f"X-RequestId:{request_id}\r\nContent-Type:application/ssml+xml\r\n"
            f"X-Timestamp:{stamp}Z\r\nPath:ssml\r\n\r\n"
            + ssml(text, voice, rate, pitch))
        audio = bytearray()
        import aiohttp
        while True:
            message = await asyncio.wait_for(self._ws.receive(), timeout=_TURN_TIMEOUT)
            if message.type is aiohttp.WSMsgType.BINARY:
                headers, data = split_binary(message.data)
                if headers.get(b"Path") == b"audio" and data:
                    audio.extend(data)
            elif message.type is aiohttp.WSMsgType.TEXT:
                if "Path:turn.end" in message.data:
                    break
            else:
                raise RuntimeError("warm socket closed")
        self._used_at = time.monotonic()
        return bytes(audio)

    # --- dışarıya açık ---------------------------------------------------
    def warm(self) -> bool:
        """Bağlantıyı şimdi aç (düşünme sırasında). Hatasız dönerse sıcak."""
        if self._closed:
            return False
        return self._run(self._warm_once(), _OPEN_TIMEOUT) is True

    async def _warm_once(self) -> bool:
        try:
            return await self._ensure_open()
        except Exception:
            _record_failure("modules/voice_edge_warm.py:connect")
            await self._drop()
            return False

    def is_warm(self) -> bool:
        """Soket açık ve taze mi — bağlantı kurma maliyeti ses yolunda ödenmez."""
        ws = self._ws
        return (ws is not None and not getattr(ws, "closed", False)
                and time.monotonic() - self._used_at <= WARM_TTL)

    def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> bytes | None:
        """Sıcak soketten üret; aksaklıkta None (çağıran edge_tts yoluna düşer).

        Zaten sıcak bir bağlantı yoksa hiç bağlanmayı denemez: niyeti el sıkışmayı
        ses yolundan çıkarmaktır, oraya taşımak değil.
        """
        if self._closed or not self.is_warm():
            return None
        return self._run(self._synth_once(text, voice, rate, pitch), _TURN_TIMEOUT)

    async def _synth_once(self, text: str, voice: str, rate: str, pitch: str) -> bytes | None:
        try:
            if not await self._ensure_open():
                return None
            audio = await self._turn(text, voice, rate, pitch)
            return audio or None
        except Exception:
            _record_failure("modules/voice_edge_warm.py:turn")
            try:
                await self._drop()
            except Exception:
                _record_failure("modules/voice_edge_warm.py:drop")
            return None

    def close(self) -> None:
        self._closed = True
        loop, thread = self._loop, self._thread
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._drop(), loop).result(5)
        except Exception:
            _record_failure("modules/voice_edge_warm.py:close")
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            _record_failure("modules/voice_edge_warm.py:stop")
        if thread is not None:
            thread.join(3)


_WARM = _Warm()


def prewarm() -> bool:
    """Konuşma hattı dışından çağrılır: sonraki cevabın bağlantısı hazır olsun."""
    return _WARM.warm()


def synthesize(text: str, voice: str, rate: str, pitch: str) -> bytes | None:
    return _WARM.synthesize(text, voice, rate, pitch)


def close() -> None:
    _WARM.close()
