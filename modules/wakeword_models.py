"""Uyandırma modellerini kullanıcı klasörüne indirir; paket klasörü yazılamasa da çalışır."""
from pathlib import Path
import os
import tempfile
import urllib.request

from config import DATA_DIR

MODEL_DIR = DATA_DIR / "wake_models"


def _entries():
    import openwakeword
    entries = dict(openwakeword.FEATURE_MODELS)
    entries['hey_jarvis'] = openwakeword.MODELS['hey_jarvis']
    return entries


def _download(url, path, opener):
    opener = opener or urllib.request.urlopen
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".download", delete=False) as temporary:
        pending = Path(temporary.name)
        try:
            with opener(url, timeout=60) as response:
                while chunk := response.read(1 << 20):
                    temporary.write(chunk)
        except BaseException:
            temporary.close()
            pending.unlink(missing_ok=True)
            raise
    return pending


def _valid(path):
    """İndirilen dosyanın gerçekten yüklenebilir bir ONNX modeli olduğunu doğrular."""
    import onnxruntime
    onnxruntime.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    return True


def ensure_models(destination=None, opener=None, validator=None, entries=None):
    """Eksik ONNX modellerini indirir; ada göre dosya yollarını döndürür.

    Yazılabilir bir hedef kullanılır (varsayılan `~/.jarvis/wake_models`): program
    dosyaları klasörüne yazma izni olmayan kurulumlarda eski sürüm `PermissionError`
    veriyordu ve uyandırma kelimesi sessizce Google yöntemine düşüyordu.
    """
    root = Path(destination) if destination is not None else MODEL_DIR
    root.mkdir(parents=True, exist_ok=True)
    validate = validator or _valid
    paths = {}
    for name, entry in (entries if entries is not None else _entries()).items():
        path = root / (Path(entry['model_path']).stem + '.onnx')
        paths[name] = str(path)
        if path.is_file() and path.stat().st_size:
            continue
        url = entry['download_url'].replace('.tflite', '.onnx')
        print("Model indiriliyor:", path.name, flush=True)
        pending = _download(url, path, opener)
        try:
            validate(pending)
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)
    return paths


if __name__ == "__main__":
    from openwakeword.model import Model
    paths = ensure_models()
    Model(wakeword_models=[paths['hey_jarvis']], inference_framework='onnx',
          melspec_model_path=paths['melspectrogram'], embedding_model_path=paths['embedding'])
    print("TAMAM: Hey Jarvis hazir", paths)
