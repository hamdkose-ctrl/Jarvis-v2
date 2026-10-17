"""Model çağrısı sayacı: neyin kota harcadığını kanıtla göstermek için.

Her gerçek sağlayıcı çağrısı (Gemini, Groq, Ollama, OpenRouter, ücretli, gömme, ses, Live bağlantısı)
kullanıcıya özel `~/.jarvis/kota/<kullanıcı>.jsonl` dosyasına bir satır yazar: zaman, sağlayıcı, model,
çağıran yer (modül.fonksiyon), giden/gelen karakter ve sonuç (ok, 429, hata kodu). İstem veya cevap
metni yazılmaz. Karakter sayısı token değildir; yaklaşık büyüklük içindir. Sayaç hata verirse çağrı
etkilenmez. `kota durumu` komutu modele gitmeden bugünün özetini verir.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.diagnostics import record_failure as _record_failure

_LOCK = threading.Lock()
_TR = timezone(timedelta(hours=3))
_MAX_BYTES = 2_000_000          # bu boyutu aşan dosya .1 olarak döner (en fazla iki dosya)
_SKIP = ('modules/llm.py', 'modules/usage_meter.py', 'modules/smart_router.py', 'modules/model_wait.py',
         'modules/paid_providers.py', 'modules/live_session.py')


def _dir():
    from config import DATA_DIR
    path = DATA_DIR / 'kota'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _owner():
    try:
        from modules import llm
        return llm.current_user() or 'default'
    except Exception:
        _record_failure('modules/usage_meter.py:_owner')
        return 'default'


def _slug(owner):
    return re.sub(r'[^\w-]', '_', str(owner or 'default'))[:64] or 'default'


_ROOT = str(Path(__file__).resolve().parents[1]).replace('\\', '/').casefold() + '/'


def caller() -> str:
    """Çağrıyı başlatan ilk Jarvis kodu: 'router.classify', 'goal_executor._plan' gibi."""
    frame, fallback = sys._getframe(1), None
    while frame is not None:
        name = frame.f_code.co_filename.replace('\\', '/')
        low = name.casefold()
        if low.startswith(_ROOT) and not name.endswith(_SKIP) and '/.venv' not in low \
                and '/site-packages/' not in low:
            label = name.rsplit('/', 1)[-1].removesuffix('.py') + '.' + frame.f_code.co_name
            if not frame.f_code.co_name.startswith('<'):
                return label
            fallback = fallback or label   # lambda/iç ifade: dışındaki adlı fonksiyon daha açıklayıcı
        frame = frame.f_back
    return fallback or 'bilinmiyor'


def outcome(error) -> str:
    """Hatayı kısa sonuç etiketine çevirir: '429', '503', 'baglanti', 'hata'."""
    code = getattr(error, 'code', None) or getattr(error, 'status_code', None)
    if code is None:
        code = getattr(getattr(error, 'response', None), 'status_code', None)
    if isinstance(code, int):
        return str(code)
    text = str(error)
    match = re.search(r'\b(4\d\d|5\d\d)\b', text)
    if match:
        return match.group(1)
    if 'Connection' in type(error).__name__ or 'Timeout' in type(error).__name__:
        return 'baglanti'
    return 'hata'


def record(provider: str, model: str = '', chars_in: int = 0, chars_out: int = 0, result: str = 'ok',
           source: str | None = None, owner: str | None = None) -> None:
    try:
        now = datetime.now(_TR)
        row = {'t': now.isoformat(timespec='seconds'), 'p': provider, 'm': str(model or '')[:60],
               's': source or caller(), 'i': int(chars_in or 0), 'o': int(chars_out or 0), 'r': str(result)[:20]}
        path = _dir() / (_slug(owner or _owner()) + '.jsonl')
        with _LOCK:
            if path.exists() and path.stat().st_size > _MAX_BYTES:
                path.replace(path.with_suffix('.jsonl.1'))
            with open(path, 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception:
        _record_failure('modules/usage_meter.py:record')  # sayaç hatası çağrıyı etkilemez


def size(*parts) -> int:
    """Giden metnin karakter sayısı; sohbet geçmişi (genai Content/sözlük listesi) dahil."""
    total = 0
    for part in parts:
        if isinstance(part, str):
            total += len(part)
        elif isinstance(part, dict):
            total += size(part.get('content'))
        elif isinstance(part, (list, tuple)):
            total += sum(size(item) for item in part)
        elif part is not None:
            for item in getattr(part, 'parts', None) or []:
                total += len(getattr(item, 'text', None) or '')
    return total


def rows(owner: str | None = None, day: str | None = None) -> list[dict]:
    day = day or datetime.now(_TR).date().isoformat()
    base = _dir() / (_slug(owner or _owner()) + '.jsonl')
    out = []
    for path in (base.with_suffix('.jsonl.1'), base):
        try:
            with open(path, encoding='utf-8') as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if str(row.get('t', '')).startswith(day):
                        out.append(row)
        except OSError:
            continue
    return out


_LABEL = {'gemini': 'Gemini', 'groq': 'Groq', 'ollama': 'Ollama (yerel)', 'openrouter': 'OpenRouter',
          'openai': 'OpenAI', 'anthropic': 'Claude', 'gemini-embed': 'Gemini gömme',
          'gemini-ses': 'Gemini ses çevirme', 'gemini-live': 'Gemini Live bağlantısı'}


def summary(owner: str | None = None, day: str | None = None) -> str:
    data = rows(owner, day)
    day = day or datetime.now(_TR).date().isoformat()
    if not data:
        return f'{day} için kayıtlı model çağrısı yok. Sayaç yalnız bu sürümden sonraki çağrıları sayar.'
    lines = [f'Kota sayacı · {day} · toplam {len(data)} çağrı, giden ~{sum(r["i"] for r in data):,} karakter'
             .replace(',', '.')]
    providers = Counter(r['p'] for r in data)
    lines.append('')
    lines.append('Sağlayıcıya göre:')
    for name, count in providers.most_common():
        mine = [r for r in data if r['p'] == name]
        limited = sum(1 for r in mine if r['r'] == '429')
        failed = sum(1 for r in mine if r['r'] not in ('ok', '429'))
        extra = ', '.join(x for x in (f'{limited} kez 429' if limited else '', f'{failed} hata' if failed else '') if x)
        lines.append(f'- {_LABEL.get(name, name)}: {count} çağrı' + (f' ({extra})' if extra else ''))
    lines.append('')
    lines.append('En çok çağıran yerler:')
    for source, count in Counter(r['s'] for r in data).most_common(8):
        chars = sum(r['i'] for r in data if r['s'] == source)
        lines.append(f'- {source}: {count} çağrı, ~{chars:,} karakter'.replace(',', '.'))
    lines.append('')
    lines.append('Karakter sayısı token değildir, yaklaşık büyüklüktür. Sağlayıcının kalan kotası buradan bilinmez.')
    return '\n'.join(lines)


_COMMANDS = {'kota durumu', 'kota raporu', 'kota sayaci', 'kota sayacı', 'model kullanimi', 'model kullanımı',
             'bugun ne kadar kota harcadim', 'bugün ne kadar kota harcadım', 'kota ne durumda'}


def handle(owner, command):
    text = ' '.join(str(command or '').casefold().replace('i̇', 'i').split()).strip(' .!?')
    text = re.sub(r'^jarvis[, ]+', '', text)
    if text in _COMMANDS:
        return summary(owner)
    return None
