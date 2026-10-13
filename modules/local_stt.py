"""Optional, button-only Turkish STT. Recognition never downloads or calls a cloud API."""
from __future__ import annotations

import importlib.util
import logging
import re
import threading
import time
from pathlib import Path

import config
from modules import privacy
from modules.diagnostics import record_failure as _record_failure

MODELS = ('small', 'base')
_lock = threading.Lock()
_prepare_lock = threading.Lock()
_model = None
_model_path = None
_preparing: set[str] = set()
_errors: dict[str, str] = {}
_log = logging.getLogger('jarvis')

# Whisper sessizlikte/gürültüde eğitim verisinden cümle uydurabilir; bunlar komut sayılmaz.
_NO_SPEECH_PROB, _LOW_LOGPROB, _MAX_COMPRESSION = 0.6, -1.0, 2.4
_FABRICATED = {'altyazı m k', 'izlediğiniz için teşekkürler', 'izlediğiniz için teşekkür ederim',
               'abone olmayı unutmayın', 'abone olun', 'iyi seyirler', 'bir sonraki videoda görüşmek üzere',
               'bir sonraki videoda görüşürüz', 'videoyu beğenmeyi unutmayın'}
_FABRICATED_PREFIX = ('altyazı m k', 'izlediğiniz için teşekkür')
_PROMPT_CHARS = 200
_DEFAULT_BEAM = 5


def model_name() -> str:
    name = config.load_settings().get('local_stt_model', 'small')
    if name not in MODELS:
        raise ValueError('Yerel ses modeli small veya base olmalı.')
    return name


def model_dir(name: str) -> Path:
    if name not in MODELS:
        raise ValueError('Yerel ses modeli small veya base olmalı.')
    return config.DATA_DIR / 'models' / 'stt' / name


def _complete(path: Path) -> bool:
    return all((path / f).is_file() and (path / f).stat().st_size > 0
               for f in ('model.bin', 'config.json', 'tokenizer.json'))


def _norm(text: str) -> str:
    text = text.replace('İ', 'i').replace('I', 'ı').lower()
    return ' '.join(re.sub(r'[^\w\s]|_', ' ', text).split())


def beam_size() -> int:
    """Ayardaki hız/doğruluk dengesi (1 en hızlı, 5 en doğru); geçersizse eski davranış (5)."""
    try:
        value = int(config.load_settings().get('local_stt_beam', _DEFAULT_BEAM))
    except (TypeError, ValueError):
        return _DEFAULT_BEAM
    return value if 1 <= value <= 5 else _DEFAULT_BEAM


def hint_prompt() -> str | None:
    """Ayarlar › Özel kelimeler Whisper'a kısa bir ipucu olur (en çok ~200 karakter, tam kelimelerle)."""
    words = [w.strip() for w in str(config.load_settings().get('stt_words') or '').split(',') if w.strip()]
    prompt = ''
    for word in words:
        joined = f'{prompt}, {word}' if prompt else word
        if len(joined) > _PROMPT_CHARS:
            break
        prompt = joined
    return prompt or None


def _fabricated(seg, prompt: str = '') -> bool:
    """Konuşma yokken uydurulmuş segment mi? Olasılık alanları yoksa yalnız bilinen kalıplara bakılır.
    Whisper ipucu metnini çıktıya geri yazdıysa (tamamı ya da 3+ kelimelik parçası) o da atılır."""
    no_speech = getattr(seg, 'no_speech_prob', None)
    logprob = getattr(seg, 'avg_logprob', None)
    ratio = getattr(seg, 'compression_ratio', None)
    if no_speech is not None and logprob is not None and no_speech > _NO_SPEECH_PROB and logprob < _LOW_LOGPROB:
        return True
    if ratio is not None and ratio > _MAX_COMPRESSION:
        return True
    text = _norm(seg.text)
    if text in _FABRICATED or text.startswith(_FABRICATED_PREFIX):
        return True
    hint = _norm(prompt)
    return bool(hint) and (text == hint or (len(text.split()) >= 3 and text in hint))


def _load(path: Path, factory) -> None:
    """_lock altında çağrılır: tek önbellekli CPU modeli."""
    global _model, _model_path
    if _model_path != path:
        _model = None
        _model_path = None
        _model = factory(str(path), device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
        _model_path = path


def preload() -> bool:
    """Açılışta, yalnız zaten inmiş modeli arka planda belleğe alır; indirme ve ağ yok, hata sessizdir."""
    try:
        if not config.load_settings().get('local_stt_enabled', False):
            return False
        path = model_dir(model_name())
        if importlib.util.find_spec('faster_whisper') is None or not _complete(path):
            return False
    except Exception:
        _record_failure('modules/local_stt.py:preload')
        return False

    def run():
        try:
            from faster_whisper import WhisperModel
            with _lock:
                _load(path, WhisperModel)
        except Exception:
            _record_failure('modules/local_stt.py:preload')
            _log.warning('Yerel STT ön yükleme başarısız; ilk kullanımda yüklenecek.')

    threading.Thread(target=run, daemon=True, name='yerel-ses-yukle').start()
    return True


def status() -> dict:
    name = model_name()
    with _prepare_lock:
        preparing, error = name in _preparing, _errors.get(name, '')
    installed = importlib.util.find_spec('faster_whisper') is not None
    return {'model': name, 'installed': installed, 'ready': _complete(model_dir(name)),
            'preparing': preparing, 'error': error}


def prepare(name: str) -> dict:
    """Only this explicit UI action may fetch model weights; never install packages."""
    path = model_dir(name)
    if privacy.mode() != 'normal':
        raise ValueError('Model indirmek için önce Normal moda geç. İndirme bitince yerel kullanabilirsin.')
    if importlib.util.find_spec('faster_whisper') is None:
        raise ValueError('faster-whisper kurulu değil. Yerel ses kurulum yönergesini uygula.')
    with _prepare_lock:
        if name in _preparing:
            return {'started': False, 'model': name}
        _preparing.add(name)
        _errors.pop(name, None)

    def run():
        try:
            # Hugging Face receives only this model download, never microphone data.
            from faster_whisper import download_model
            download_model(name, output_dir=str(path), use_auth_token=False)
            if not _complete(path):
                raise ValueError('Model dosyaları eksik. İndirmeyi yeniden dene.')
        except Exception:
            _record_failure('modules/local_stt.py:prepare')
            with _prepare_lock:
                _errors[name] = 'Model indirilemedi. İnterneti ve boş disk alanını kontrol edip yeniden dene.'
            _log.warning('Yerel STT model hazırlığı başarısız (%s)', name)
        finally:
            with _prepare_lock:
                _preparing.discard(name)

    threading.Thread(target=run, daemon=True, name='yerel-ses-modeli').start()
    return {'started': True, 'model': name}


def transcribe(raw: bytes) -> str | None:
    if not raw:
        return None
    if len(raw) % 2 or len(raw) > 16000 * 2 * 30:
        raise ValueError('Yerel ses kaydı bozuk veya 30 saniyeden uzun.')
    name = model_name()
    path = model_dir(name)
    if not _complete(path):
        raise ValueError('Yerel ses modeli hazır değil. Ayarlar › Ses bölümünden modeli indir.')
    try:
        from faster_whisper import WhisperModel
        import numpy as np
    except ImportError as exc:
        raise ValueError('Yerel ses için faster-whisper kurulmalı.') from exc
    started = time.monotonic()
    # One cached CPU model; avoid simultaneous loads/transcriptions and excess RAM.
    with _lock:
        _load(path, WhisperModel)
        audio = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
        prompt = hint_prompt()
        segments, _ = _model.transcribe(audio, language='tr', beam_size=beam_size(), initial_prompt=prompt,
                                       vad_filter=True, condition_on_previous_text=False)
        heard = [s for s in segments if s.text.strip()]
        kept = [s for s in heard if not _fabricated(s, prompt or '')]
        text = ' '.join(s.text.strip() for s in kept).strip()
    _log.info('Yerel STT tamamlandı: model=%s süre=%.2f sn, süzülen segment=%d', name, time.monotonic() - started,
              len(heard) - len(kept))
    return text or None
