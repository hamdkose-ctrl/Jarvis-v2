"""Explicit, local-only PDF OCR. No downloads, cloud fallback or persistent input files."""
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

MAX_BYTES = 4 * 1024 * 1024
MAX_PAGES = 10
MAX_TEXT = 20000
TIMEOUT = 30
LANGUAGES = ('tur+eng', 'tur', 'eng')
ERRORS = {
    'missing': 'Yerel OCR için Tesseract ve seçilen dil paketleri gerekli.',
    'reader': 'Yerel OCR için pypdfium2 ve Pillow gerekli; kurulum.bat ile onarın.',
    'limit': 'OCR belge boyutu veya sayfa boyutu sınırını aşıyor.',
    'timeout': 'Yerel OCR süre sınırına ulaştı; belge okunmuş sayılmadı.',
    'document': 'PDF açılamadı; bozuk veya şifreli olabilir.',
    'empty': 'Yerel OCR okunabilir metin bulamadı.',
    'failed': 'Yerel OCR tamamlanamadı; araç çıktısı gösterilmedi.',
}


class OcrError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(ERRORS[code])


def check(language='tur+eng'):
    if language not in LANGUAGES:
        raise ValueError('OCR dili geçersiz.')
    tool = shutil.which('tesseract')
    if not tool:
        return {'ok': False, 'text': ERRORS['missing']}
    try:
        cp = subprocess.run([tool, '--list-langs'], capture_output=True, timeout=5, check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        installed = set(cp.stdout.decode('utf-8', 'replace').splitlines())
        if not set(language.split('+')) <= installed:
            return {'ok': False, 'text': ERRORS['missing']}
    except (OSError, subprocess.SubprocessError):
        return {'ok': False, 'text': ERRORS['failed']}
    return {'ok': True, 'text': 'Yerel OCR motoru ve dil dosyaları mevcut; gerçek belge testi ayrıca gerekli.'}


def _extract(raw, language):
    if not raw or len(raw) > MAX_BYTES:
        raise OcrError('limit')
    if not check(language)['ok']:
        raise OcrError('missing')
    from modules.pdf_runtime import open_pdf
    deadline = time.monotonic() + TIMEOUT - 3
    chunks = []
    length = 0
    truncated = False
    with open_pdf(raw) as pdf:
        truncated = len(pdf) > MAX_PAGES
        for index in range(min(len(pdf), MAX_PAGES)):
            page = pdf[index]
            bitmap = None
            image = None
            try:
                width, height = page.get_size()
                if any(not math.isfinite(v) or v <= 0 or v > 20000 for v in (width, height)):
                    raise OcrError('limit')
                scale = min(2.5, 2200 / max(width, height))
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                png = io.BytesIO()
                image.save(png, format='PNG')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OcrError('timeout')
                cp = subprocess.run([shutil.which('tesseract'), 'stdin', 'stdout', '-l', language, '--psm', '3'],
                                    input=png.getvalue(), capture_output=True, timeout=min(6, remaining), check=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if len(cp.stdout) > MAX_TEXT * 4:
                    raise OcrError('limit')
                text = cp.stdout.decode('utf-8').strip()
                room = max(0, MAX_TEXT - length)
                value = text[:room]
                if value:
                    chunks.append(value)
                    length += len(value) + 1
                if len(text) > room or length >= MAX_TEXT:
                    truncated = True
                    break
            finally:
                if image is not None:
                    image.close()
                if bitmap is not None:
                    bitmap.close()
                page.close()
    body = '\n'.join(chunks)[:MAX_TEXT]
    if not body.strip():
        raise OcrError('empty')
    return {'body': body, 'truncated': truncated}


def _worker(raw, language):
    try:
        return _extract(raw, language)
    except OcrError as exc:
        return {'error': exc.code}
    except ImportError:
        return {'error': 'reader'}
    except subprocess.TimeoutExpired:
        return {'error': 'timeout'}
    except subprocess.SubprocessError:
        return {'error': 'failed'}
    except (ValueError, RuntimeError, OSError):
        return {'error': 'document'}


def read(raw, *, language='tur+eng'):
    from modules import requests_state
    requests_state.check()
    if language not in LANGUAGES:
        raise ValueError('OCR dili geçersiz.')
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise OcrError('limit')
    from modules.attachment_documents import _python
    try:
        cp = subprocess.run([_python(), '-m', 'modules.local_ocr', '--worker', language], input=raw,
                            capture_output=True, timeout=TIMEOUT, check=True,
                            cwd=str(Path(__file__).resolve().parents[1]),
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise OcrError('timeout') from None
    except (OSError, subprocess.SubprocessError):
        raise OcrError('failed') from None
    requests_state.check()
    try:
        if len(cp.stdout) > 100000:
            raise ValueError()
        result = json.loads(cp.stdout.decode('utf-8'))
        if isinstance(result, dict) and set(result) == {'error'} and result['error'] in ERRORS:
            raise OcrError(result['error'])
        if (not isinstance(result, dict) or set(result) != {'body', 'truncated'} or
                not isinstance(result['body'], str) or not result['body'].strip() or
                len(result['body']) > MAX_TEXT or type(result['truncated']) is not bool):
            raise ValueError()
        return result
    except OcrError:
        raise
    except (ValueError, TypeError):
        raise OcrError('failed') from None


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker' and sys.argv[2] in LANGUAGES:
        result = _worker(sys.stdin.buffer.read(MAX_BYTES + 1), sys.argv[2])
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    else:
        print('Yerel OCR, Jarvis sohbetinde açık dosya komutuyla başlatılır.')
        raise SystemExit(2)
