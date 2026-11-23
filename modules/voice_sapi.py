"""Windows SAPI (yerel) ses motoru — internet gerekmez.

Neden: Jarvis'in sesi Edge (çevrimiçi). Ağ kopunca ya da gizlilik modu "yerel"
seçiliyken ses hiç çıkmıyordu. Windows'ta konuşma motoru zaten kurulu; bu modül
onu Voice Core hattına `sapi` arka ucu olarak bağlar.

Sınırlar (dürüst):
* Kalite, Windows'a kurulu ses paketine bağlıdır. Türkçe paket yoksa İngilizce
  ses Türkçe metni okur — anlaşılır ama aksanlı. Kurulu sesler arayüzde adıyla
  görünür, kimlik sessizce değiştirilmez.
* SAPI yalnız Windows'ta vardır; başka platformda `installed_voices()` boş döner
  ve hat Edge'de kalır.
* Metin hiçbir yere gönderilmez: ses dosyası yerelde üretilir.
"""
from __future__ import annotations

import re
import sys
import tempfile
import threading
from pathlib import Path

from modules.diagnostics import record_failure as _record_failure
from modules.voice_offline import OfflineVoiceUnavailable

MAX_CHARS = 4_000
TR_LCID = 0x41F          # 1055 = Türkçe (Türkiye)

_VOICE_PREFIX = "win_"


def _comtypes():
    """comtypes yoksa None (SAPI yalnız Windows'ta, bu yüzden sessiz dönüş)."""
    try:
        import comtypes  # noqa: F401
        from comtypes.client import CreateObject  # noqa: F401
    except Exception:
        _record_failure("modules/voice_sapi.py:comtypes_import")
        return None
    return True


def _split_description(text: str) -> tuple[str, str]:
    """'Microsoft Tolga - Turkish (Turkey)' → ('Tolga', 'Türkçe').

    Ad arayüzde kısa görünsün; dil etiketi kullanıcıya hangi dilde konuşulacağını
    söylesin (Türkçe paket yoksa bu uyarı olur)."""
    body = str(text or "").strip()
    name, _, lang = body.partition(" - ")
    name = re.sub(r"^Microsoft\s+", "", name).strip() or body or "Windows sesi"
    lang = lang.strip()
    if "Turkish" in lang:
        lang = "Türkçe"
    elif "English" in lang:
        lang = "İngilizce"
    return name, lang


def _key(name: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or f"ses{index}"
    return f"{_VOICE_PREFIX}{slug}"[:40]


def installed_voices() -> list[tuple[str, str, str]]:
    """Kurulu SAPI sesleri: [(anahtar, etiket, SAPI adı)].

    SAPI yoksa, Windows değilse ya da hiç ses yoksa boş liste döner; çağıran
    hat Edge'de kalır (sessizce başka ses uydurulmaz).
    """
    if sys.platform != "win32" or not _comtypes():
        return []
    try:
        import comtypes
        from comtypes.client import CreateObject
    except Exception:
        _record_failure("modules/voice_sapi.py:comtypes_import")
        return []
    initialized = False
    out: list[tuple[str, str, str]] = []
    try:
        comtypes.CoInitialize()
        initialized = True
        collection = CreateObject("SAPI.SpVoice").GetVoices()
        for index in range(collection.Count):
            item = collection.Item(index)
            description = str(item.GetDescription() or "").strip()
            if not description:
                continue
            name, lang = _split_description(description)
            label = f"Windows · {name}" + (f" ({lang})" if lang else "")
            out.append((_key(name, index), label, description))
    except Exception:
        _record_failure("modules/voice_sapi.py:installed_voices")
        return []
    finally:
        if initialized:
            try:
                comtypes.CoUninitialize()
            except Exception:
                _record_failure("modules/voice_sapi.py:co_uninit")
    return out


def _speak_to_file(voice_name: str, text: str, path: Path) -> None:
    """SAPI ile metni WAV dosyasına yaz (hoparlöre değil)."""
    import comtypes
    from comtypes.client import CreateObject
    initialized = False
    stream = None
    try:
        comtypes.CoInitialize()
        initialized = True
        stream = CreateObject("SAPI.SpFileStream")
        stream.Open(str(path), 3, False)          # 3 = SSFMCreateForWrite
        voice = CreateObject("SAPI.SpVoice")
        voice.AudioOutputStream = stream
        if voice_name:
            collection = voice.GetVoices()
            for index in range(collection.Count):
                item = collection.Item(index)
                if str(item.GetDescription() or "").strip() == voice_name:
                    voice.Voice = item
                    break
        voice.Speak(text, 16)                     # SPF_IS_NOT_XML: metin asla kod/SSML değil
    finally:
        if stream is not None:
            try:
                stream.Close()
            except Exception:
                _record_failure("modules/voice_sapi.py:close")
        if initialized:
            try:
                comtypes.CoUninitialize()
            except Exception:
                _record_failure("modules/voice_sapi.py:co_uninit")


class SapiSynthesizer:
    """Bir parçayı yerelde WAV'a çevirir; Voice Core'un beklediği baytları döndürür."""

    def __init__(self, timeout_seconds: float = 45.0):
        if not 0 < timeout_seconds <= 180:
            raise ValueError("SAPI süre sınırı kabul edilen aralıkta değil.")
        self.timeout_seconds = timeout_seconds

    def __call__(self, spec, text: str, cancel: threading.Event) -> bytes:
        if getattr(spec, "backend", "") != "sapi":
            raise OfflineVoiceUnavailable("SAPI hattı yalnız 'sapi' sesi üretir.")
        if cancel.is_set():
            return b""
        body = str(text or "").strip()
        if not body:
            return b""
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS]
        if not _comtypes():
            raise OfflineVoiceUnavailable("Windows konuşma motoru (SAPI) bu makinede yok.")
        with tempfile.TemporaryDirectory(prefix="jarvis-sapi-") as folder:
            path = Path(folder) / "chunk.wav"
            try:
                _speak_to_file(str(getattr(spec, "asset_id", "") or ""), body, path)
            except Exception as exc:
                _record_failure("modules/voice_sapi.py:synthesize")
                raise OfflineVoiceUnavailable("Windows yerel sesi üretilemedi.") from exc
            if cancel.is_set():
                return b""
            if not path.is_file() or path.stat().st_size <= 44:
                raise OfflineVoiceUnavailable("Windows yerel sesi boş döndü.")
            data = path.read_bytes()
        if not data.startswith(b"RIFF"):
            raise OfflineVoiceUnavailable("Windows yerel ses çıktısı WAV değil.")
        return data

    def preload_all(self) -> int:
        """Arayüz aynı adı bekliyor: yüklenecek model yok, kurulu ses sayısını döndür."""
        return len(installed_voices())
