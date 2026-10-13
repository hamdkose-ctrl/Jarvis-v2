"""Complete the ONNX model set even when the paired TFLite file already exists."""
from pathlib import Path
import os
import tempfile
import urllib.request


def ensure_models():
    import openwakeword
    entries = dict(openwakeword.FEATURE_MODELS)
    entries['hey_jarvis'] = openwakeword.MODELS['hey_jarvis']
    paths = {}
    for name, entry in entries.items():
        path = Path(entry['model_path']).with_suffix('.onnx')
        paths[name] = str(path)
        if path.is_file() and path.stat().st_size:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        url = entry['download_url'].replace('.tflite', '.onnx')
        print('Model indiriliyor:', path.name, flush=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.download', delete=False) as temporary:
            pending = Path(temporary.name)
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        temporary.write(chunk)
            except BaseException:
                temporary.close()
                pending.unlink(missing_ok=True)
                raise
        try:
            import onnxruntime
            onnxruntime.InferenceSession(str(pending), providers=['CPUExecutionProvider'])
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)
    return paths


if __name__ == '__main__':
    from openwakeword.model import Model
    ensure_models()
    Model(wakeword_models=['hey_jarvis'], inference_framework='onnx')
    print('TAMAM: Hey Jarvis hazir')
