"""VOICE-02A: explicitly enabled, single-owner Piper speech route for engine.

The user's existing per-profile voice key remains authoritative. All synthesis
and playback runs in VoiceCoordinator's foreground lane; no LLM/Ollama,
automatic model installation, network fallback, or alternate voice selection.
This is a gated integration, not evidence of human-audible Windows output.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import threading

from modules.diagnostics import record_failure as _record_failure
from modules.voice_core import SpeechRequest, VoiceCatalog, VoiceCoordinator, VoiceSpec
from modules.voice_offline import OfflineVoiceUnavailable, PiperSynthesizer, WavePlayer


CONFIG_NAME = "voice_core.json"
_ALLOWED_VOICES = frozenset({
    "tr_erkek", "tr_kadin", "ml_erkek", "ml_kadin", "ml_erkek2", "ml_kadin2",
})
_ACTIVE_LOCK = threading.Lock()
_ACTIVE = None
_BLOCK_LEGACY = False  # explicit configuration fault must not trigger a second voice


class VoiceConfigurationError(ValueError):
    pass


def _read_config(path: Path):
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise VoiceConfigurationError("Voice Core yapılandırma dosyası okunamadı.") from exc
    if size > 32_768:
        raise VoiceConfigurationError("Voice Core yapılandırması çok büyük.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VoiceConfigurationError("Voice Core yapılandırması okunamadı.") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema", "enabled", "voices"}:
        raise VoiceConfigurationError("Voice Core yapılandırma şeması geçersiz.")
    if raw["schema"] != "voice_core.config.v1" or type(raw["enabled"]) is not bool:
        raise VoiceConfigurationError("Voice Core yapılandırma sürümü veya enabled geçersiz.")
    if not raw["enabled"]:
        return None
    voices = raw["voices"]
    if not isinstance(voices, dict) or not voices or len(voices) > len(_ALLOWED_VOICES):
        raise VoiceConfigurationError("Voice Core ses listesi boş veya geçersiz.")
    specs = []
    for key, entry in voices.items():
        if key not in _ALLOWED_VOICES or not isinstance(entry, dict) or set(entry) != {"label", "model"}:
            raise VoiceConfigurationError("Voice Core bilinmeyen ses veya katalog alanı.")
        label, model = entry["label"], entry["model"]
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise VoiceConfigurationError("Voice Core ses etiketi geçersiz.")
        if not isinstance(model, str) or not model or len(model) > 200:
            raise VoiceConfigurationError("Voice Core model yolu geçersiz.")
        asset = Path(model)
        if asset.is_absolute() or ".." in asset.parts or asset.suffix.lower() != ".onnx":
            raise VoiceConfigurationError("Voice Core yalnız yerel .onnx model yolu kabul eder.")
        # PiperSynthesizer revalidates path confinement and regular files on
        # each request, also preventing model replacement via symlink.
        specs.append(VoiceSpec(key, label, "piper", model))
    return VoiceCatalog(tuple(specs))


def maybe_start(runtime):
    """Return (voice_lane, explicitly_enabled); absent/disabled config keeps legacy."""
    global _BLOCK_LEGACY
    _BLOCK_LEGACY = False
    data_dir = getattr(runtime, "DATA_DIR", None)
    if not isinstance(data_dir, Path):
        return None, False
    config_path = data_dir / CONFIG_NAME
    catalog = _read_config(config_path)
    if catalog is None:
        return None, False
    root = data_dir / "voice_models"
    lane = VoiceLane(runtime, catalog, PiperSynthesizer(root), WavePlayer())
    try:
        register(lane)
    except VoiceConfigurationError:
        lane.close()
        raise
    return lane, True


def register(lane):
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is not None and _ACTIVE is not lane:
            raise VoiceConfigurationError("Birden fazla Voice Core çıkış sahibi açılamaz.")
        _ACTIVE = lane


def active():
    with _ACTIVE_LOCK:
        return _ACTIVE


def block_legacy_on_fault():
    """An invalid explicit Voice Core configuration cannot select old TTS."""
    global _BLOCK_LEGACY
    _BLOCK_LEGACY = True


def legacy_blocked() -> bool:
    return bool(_BLOCK_LEGACY)


def interrupt_active() -> bool:
    lane = active()
    if lane is None:
        return False
    lane.interrupt()
    return True


def announce_active(text: str) -> bool:
    """Route direct local privacy notices through the same owner when enabled."""
    lane = active()
    if lane is None:
        return bool(_BLOCK_LEGACY)
    runtime = lane.runtime
    if not runtime.flags.get("speak", True):
        return True  # mute never starts a new private-mode voice notice
    owner = runtime.pc_profile()
    voice_key = owner.data["prefs"].get("voice") or "tr_erkek"
    raw_rate = owner.data["prefs"].get("rate", 0)
    rate = raw_rate if type(raw_rate) is int and -40 <= raw_rate <= 40 else 0
    try:
        lane.say(owner.slug, voice_key, text, background=True, rate=rate)
    except ValueError:
        # No fallback to Edge or a different local identity.
        runtime.emit("system", "Seçilen yerel ses kurulu değil; bildirim yalnız yazılı gösterildi.")
    return True


class VoiceLane:
    def __init__(self, runtime, catalog, synthesize, play):
        self.runtime = runtime
        self.catalog = catalog
        self._synthesize = synthesize
        self._lock = threading.RLock()
        self._outstanding = {}
        self.busy_event = threading.Event()
        self._closed = False
        self._coordinator = VoiceCoordinator(
            catalog, synthesize, play, self._receipt, max_pending=8,
        )

    def check_voice(self, voice_id: str):
        """Do not persist a new voice choice when its local model is missing."""
        spec = self.catalog.require(voice_id)
        if isinstance(self._synthesize, PiperSynthesizer):
            try:
                model_path = self._synthesize._model(spec)
            except OfflineVoiceUnavailable as exc:
                raise ValueError("Seçilen yerel ses modeli kurulu değil.") from exc
            metadata_path = Path(str(model_path) + ".json")
            if not metadata_path.is_file() or metadata_path.is_symlink():
                raise ValueError("Seçilen Piper modelinin doğrulanmış .onnx.json metaverisi eksik.")
            if not shutil.which("piper"):
                raise ValueError("Seçilen Piper motoru kurulu değil.")
        return spec

    def say(self, owner: str, voice_id: str, text: str, *,
            background: bool = False, rate: int = 0):
        """Enqueue without waiting for synthesis or blocking caller's Core work."""
        voice_id = voice_id if isinstance(voice_id, str) else ""
        self.catalog.require(voice_id)  # explicit exact voice; no implicit fallback
        request_id = self.runtime.secrets.token_hex(16)
        request = SpeechRequest(owner=owner, request_id=request_id,
                                voice_id=voice_id, text=text,
                                lane="background" if background else "foreground",
                                rate=rate)
        done = threading.Event()
        with self._lock:
            if self._closed:
                raise ValueError("Voice Core kapatılmış.")
            self._outstanding[request_id] = done
            self.busy_event.set()
        try:
            accepted = self._coordinator.submit(request)
        except Exception:
            _record_failure("modules/voice_runtime.py:submit")
            self._forget(request_id)
            raise
        if not accepted:
            self._forget(request_id)
            raise ValueError("Voice Core konuşma kuyruğu dolu; farklı sesle tekrar denenmedi.")
        return done

    def _forget(self, request_id: str):
        with self._lock:
            done = self._outstanding.pop(request_id, None)
            if not self._outstanding:
                self.busy_event.clear()
        if done is not None:
            done.set()

    def _receipt(self, receipt):
        self._forget(receipt.request_id)
        if self._closed:
            return
        try:
            if receipt.owner == self.runtime.pc_profile().slug:
                if receipt.status == "failed":
                    self.runtime.emit("system", "Seçilen yerel ses üretilemedi veya oynatılamadı; başka sese geçilmedi.")
                if not self.busy_event.is_set():
                    self.runtime.emit("state", "idle")
        except Exception:
            _record_failure("modules/voice_runtime.py:receipt")

    def interrupt(self):
        self._coordinator.interrupt_speech()  # NEVER cancels GoalState/worker
        # Busy remains set until the worker acknowledges pending receipts.

    def close(self):
        global _ACTIVE, _BLOCK_LEGACY
        with self._lock:
            self._closed = True
        self._coordinator.close()
        with _ACTIVE_LOCK:
            if _ACTIVE is self:
                _ACTIVE = None
                _BLOCK_LEGACY = False

    def is_busy(self) -> bool:
        return self.busy_event.is_set()
