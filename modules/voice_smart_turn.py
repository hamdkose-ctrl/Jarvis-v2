"""Smart Turn: ses tonundan "cümle bitti mi?" kararı (yerel ONNX modeli).

Neden: mikrofon şu an yalnız sessizlik sayıyor; cümle ortasında nefes almak ile
cümlenin gerçekten bitmesi aynı görünüyor. Smart Turn (pipecat-ai/smart-turn-v3,
**BSD-2-Clause**, 8,7 MB) son ~8 saniyelik sese bakıp "konuşmacı bitirdi mi"
olasılığı verir. Model ve ağırlıklar açık; Stonic'in koduyla ilgisi yok — onlar da
aynı açık modeli kullanıyor.

Girdi biçimi modelin kendi sözleşmesidir: Whisper log-mel, 80 mel × 800 kare
(8 saniye, 10 ms adım). Özellik çıkarımı burada numpy ile yapılır (ek bağımlılık
yok): n_fft=400, hop=160, Hann, Slaney mel, log10 kırpma, (x+4)/4 normalizasyonu.

Model yoksa/bozuksa `complete()` None döner; çağıran noktalama kuralına düşer.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from modules.diagnostics import record_failure as _record_failure

SR = 16_000
N_FFT = 400
HOP = 160
N_MELS = 80
FRAMES = 800            # 8 saniye / 10 ms
AUDIO_SAMPLES = SR * 8  # model tam 8 saniye ister

MODEL_NAME = "smart-turn-v3.0.onnx"
_SESSION_LOCK = threading.Lock()
_SESSIONS: dict[str, object] = {}
_MEL_CACHE: dict[int, np.ndarray] = {}


def model_path(root: Path | str | None = None) -> Path:
    base = Path(root) if root else Path.home() / ".jarvis" / "turn_models"
    return base / MODEL_NAME


def _hz_to_mel(freq: np.ndarray | float) -> np.ndarray:
    """Slaney ölçeği (Whisper/librosa varsayılanı)."""
    freq = np.asarray(freq, dtype=np.float64)
    linear = freq / (200.0 / 3)
    log = 15.0 + np.log(np.maximum(freq, 1e-10) / 1000.0) / (np.log(6.4) / 27.0)
    return np.where(freq >= 1000.0, log, linear)


def _mel_to_hz(mel: np.ndarray) -> np.ndarray:
    mel = np.asarray(mel, dtype=np.float64)
    linear = mel * (200.0 / 3)
    log = 1000.0 * np.exp((np.log(6.4) / 27.0) * (mel - 15.0))
    return np.where(mel >= 15.0, log, linear)


def mel_filterbank(sample_rate: int = SR, n_fft: int = N_FFT, n_mels: int = N_MELS) -> np.ndarray:
    """[n_mels, n_fft//2+1] üçgen filtre bankası (Slaney normalizasyonu)."""
    cached = _MEL_CACHE.get((sample_rate, n_fft, n_mels))
    if cached is not None:
        return cached
    fft_freqs = np.linspace(0, sample_rate / 2, n_fft // 2 + 1)
    mel_points = np.linspace(_hz_to_mel(0.0), _hz_to_mel(sample_rate / 2), n_mels + 2)
    hz_points = _mel_to_hz(mel_points)
    bank = np.zeros((n_mels, len(fft_freqs)), dtype=np.float64)
    for index in range(n_mels):
        lower, centre, upper = hz_points[index], hz_points[index + 1], hz_points[index + 2]
        rising = (fft_freqs - lower) / max(centre - lower, 1e-10)
        falling = (upper - fft_freqs) / max(upper - centre, 1e-10)
        weights = np.maximum(0.0, np.minimum(rising, falling))
        norm = 2.0 / max(upper - lower, 1e-10)      # Slaney: alan normalizasyonu
        bank[index] = weights * norm
    _MEL_CACHE[(sample_rate, n_fft, n_mels)] = bank
    return bank


def log_mel(audio, *, sample_rate: int = SR) -> np.ndarray:
    """Son 8 saniyeyi Whisper log-mel'e çevir: [80, 800] float32."""
    samples = np.asarray(audio if audio is not None else [], dtype=np.float32).reshape(-1)
    if samples.size == 0:
        samples = np.zeros(AUDIO_SAMPLES, dtype=np.float32)
    if samples.size > AUDIO_SAMPLES:
        samples = samples[-AUDIO_SAMPLES:]
    elif samples.size < AUDIO_SAMPLES:              # baştan sıfırla doldur: ses sona yaslanır
        samples = np.concatenate([np.zeros(AUDIO_SAMPLES - samples.size, dtype=np.float32), samples])
    if samples.size < N_FFT:
        return np.zeros((N_MELS, FRAMES), dtype=np.float32)
    window = np.hanning(N_FFT).astype(np.float32)
    count = 1 + (samples.size - N_FFT) // HOP
    frames = np.lib.stride_tricks.as_strided(
        samples, shape=(count, N_FFT), strides=(samples.strides[0] * HOP, samples.strides[0]))
    spectrum = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
    mel = spectrum @ mel_filterbank(sample_rate).T                  # [count, 80]
    log = np.log10(np.maximum(mel, 1e-10))
    # Whisper normalizasyonu: dinamik aralık 8 birimle sınırlanır, sonra (x+4)/4.
    # Kırpma YOK: referans uygulama da kırpmıyor (ölçüm: kırpma korelasyonu 0,56'ya düşürüyordu).
    log = np.maximum(log, float(log.max()) - 8.0)
    normalised = ((log + 4.0) / 4.0).T.astype(np.float32)            # [80, count]
    if normalised.shape[1] < FRAMES:      # eksik kareler sessizlik: en düşük değer
        floor = float(normalised.min()) if normalised.size else -1.0
        pad = np.full((N_MELS, FRAMES - normalised.shape[1]), floor, dtype=np.float32)
        normalised = np.concatenate([pad, normalised], axis=1)
    return normalised[:, -FRAMES:]


def _session(path: Path):
    key = str(path)
    with _SESSION_LOCK:
        existing = _SESSIONS.get(key)
        if existing is not None:
            return existing
        import onnxruntime as ort
        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        _SESSIONS[key] = session
        return session


def available(root: Path | str | None = None) -> bool:
    """Model kurulu mu? (Ağırlık dosyası + onnxruntime)"""
    path = model_path(root)
    try:
        return path.is_file() and path.stat().st_size > 1_000_000
    except OSError:
        _record_failure("modules/voice_smart_turn.py:available")
        return False


def reference_features(audio) -> np.ndarray | None:
    """Referans (HuggingFace Whisper) özellik çıkarımı — kuruluysa onu kullan.

    Ölçüm (23 Kasım): elle yazılan numpy mel'i referansla hizalı korelasyon 0,40
    veriyor (filtre normalizasyonu farkı). Doğru davranış için modelin eğitildiği
    çıkarım şart; `transformers` kuruluysa o kullanılır, yoksa numpy sürümü
    denenir ve bu durum çağırana `last_feature_source()` ile bildirilir.
    """
    try:
        from transformers import WhisperFeatureExtractor  # noqa: F401
    except Exception:
        _record_failure("modules/voice_smart_turn.py:no_reference_features")
        return None
    try:
        samples = np.asarray(audio if audio is not None else [], dtype=np.float32).reshape(-1)
        if samples.size == 0:
            samples = np.zeros(AUDIO_SAMPLES, dtype=np.float32)
        samples = samples[-AUDIO_SAMPLES:]
        extractor = _extractor()
        batch = extractor(samples, sampling_rate=SR, return_tensors="np")["input_features"]
        return np.asarray(batch[0], dtype=np.float32)
    except Exception:
        _record_failure("modules/voice_smart_turn.py:reference_features")
        return None


_EXTRACTOR_LOCK = threading.Lock()
_EXTRACTOR = None


def _extractor():
    global _EXTRACTOR
    with _EXTRACTOR_LOCK:
        if _EXTRACTOR is None:
            from transformers import WhisperFeatureExtractor
            _EXTRACTOR = WhisperFeatureExtractor(chunk_length=AUDIO_SAMPLES // SR)
        return _EXTRACTOR


def feature_source() -> str:
    """Hangi özellik çıkarımı kullanılabilir: 'reference' | 'numpy'."""
    try:
        from transformers import WhisperFeatureExtractor  # noqa: F401
        return "reference"
    except Exception:
        _record_failure("modules/voice_smart_turn.py:feature_source")
        return "numpy"


def complete(audio, *, root: Path | str | None = None, threshold: float = 0.5,
             prefer_reference: bool = True) -> float | None:
    """Konuşmacı bitirdi mi? 0-1 arası olasılık; model yoksa None.

    Tek eşik yerine olasılık döner: çağıran isterse yalnız "tamam" der, isterse
    değeri loglar. Model hatası sıra kararını kilitlemez (None → noktalama kuralı).
    """
    if not available(root):
        return None
    try:
        session = _session(model_path(root))
        features = reference_features(audio) if prefer_reference else None
        if features is None:
            features = log_mel(audio)
        batch = features[np.newaxis, :, :]
        logits = session.run(None, {session.get_inputs()[0].name: batch})[0]
        value = float(np.asarray(logits).reshape(-1)[0])
        probability = 1.0 / (1.0 + np.exp(-value))       # tek logit → sigmoid
        return max(0.0, min(1.0, probability))
    except Exception:
        _record_failure("modules/voice_smart_turn.py:complete")
        return None


def verdict(audio, *, root: Path | str | None = None, threshold: float = 0.5,
            prefer_reference: bool = True) -> bool | None:
    """Karar olarak: True (bitti) / False (yarım) / None (model yok)."""
    probability = complete(audio, root=root, threshold=threshold, prefer_reference=prefer_reference)
    if probability is None:
        return None
    return probability >= threshold
