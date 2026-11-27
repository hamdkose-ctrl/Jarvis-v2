"""Tur ölçümü: her kullanıcı isteğinin ne kadar sürdüğünü ve nasıl bittiğini kaydeder.

Kota sayacı (modules/usage_meter.py) model çağrılarını sayar; bu modül **kullanıcı turunu**
ölçer: istek kuyruğa alındığı an ile yanıtın yazıldığı an arasındaki süre, kaynak
(yazı/ses/fotoğraf) ve sonuç (ok/iptal/hata) ile kısa neden. **Mesaj metni yazılmaz.**

Kayıt kullanıcıya özel `~/.jarvis/tur/<kullanıcı>.jsonl` dosyasına bir satır olarak düşer;
dosya iki megabaytı geçince arşive taşınır ve 14 günden eski arşivler silinir. Ölçüm hatası
turu asla etkilemez. `bugün kaç tur` komutu modele gitmeden bugünün özetini verir.

Süre, sesin hoparlörden duyulduğu an değildir: yanıtın üretildiği andır. Ses gecikmesi
voice_runtime'ın kendi `speech_pace` satırında ölçülür.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.diagnostics import record_failure as _record_failure

_LOCK = threading.Lock()
_STARTS: dict[str, tuple[float, str, str]] = {}
_TR = timezone(timedelta(hours=3))
_MAX_BYTES = 2_000_000
_KEEP_DAYS = 14
_ARCHIVE_KEEP = 3


def _dir() -> Path:
    from config import DATA_DIR
    path = DATA_DIR / 'tur'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(owner) -> str:
    return re.sub(r'[^\w-]', '_', str(owner or 'default'))[:64] or 'default'


def _key(rid) -> str:
    return str(rid or '')[:64]


def start(rid, owner: str = '', source: str = '') -> None:
    """Turun başladığını işaretler. Aynı rid ikinci kez gelirse ilk an korunur."""
    try:
        key = _key(rid)
        with _LOCK:
            if key in _STARTS:
                return
            _STARTS[key] = (time.monotonic(), str(owner or ''), str(source or '')[:12])
    except Exception:
        _record_failure('modules/turn_metrics.py:start')   # ölçüm hatası turu etkilemez


def finish(rid, outcome: str = 'ok', note: str = '') -> None:
    """Turu kapatır: başlangıç yoksa (süreç yeniden başladı) kayıt yazılmaz."""
    try:
        key = _key(rid)
        with _LOCK:
            began = _STARTS.pop(key, None)
        if began is None:
            return
        started, owner, source = began
        row = {
            't': datetime.now(_TR).isoformat(timespec='seconds'),
            'rid': key,
            'src': source,
            'ms': max(int((time.monotonic() - started) * 1000), 0),
            'r': str(outcome or 'ok')[:12],
        }
        if note:
            row['not'] = str(note)[:60]
        record(row, owner)
    except Exception:
        _record_failure('modules/turn_metrics.py:finish')


def record(row: dict, owner: str = '') -> None:
    try:
        path = _dir() / (_slug(owner) + '.jsonl')
        encoded = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')
        with _LOCK:
            if path.exists() and path.stat().st_size > _MAX_BYTES:
                path.replace(path.with_name(path.name + '.archive-' + datetime.now(_TR).strftime('%Y%m%d%H%M%S%f')))
                _prune(path)
            with path.open('ab') as handle:
                handle.write(encoded)
                handle.flush()
                import os
                os.fsync(handle.fileno())
    except Exception:
        _record_failure('modules/turn_metrics.py:record')


def _prune(path: Path) -> None:
    cutoff = datetime.now().timestamp() - _KEEP_DAYS * 86400
    try:
        archives = sorted(path.parent.glob(path.name + '.archive-*'))
        for old in archives[:-_ARCHIVE_KEEP]:
            try:
                if old.stat().st_mtime < cutoff or len(archives) > _ARCHIVE_KEEP:
                    old.unlink()
            except OSError:
                _record_failure('modules/turn_metrics.py:_prune')
    except OSError:
        _record_failure('modules/turn_metrics.py:_prune')


def rows(owner: str = '', day: str | None = None) -> list[dict]:
    day = day or datetime.now(_TR).date().isoformat()
    path = _dir() / (_slug(owner) + '.jsonl')
    if not path.exists():
        return []
    result, partial = [], False
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        _record_failure('modules/turn_metrics.py:rows')
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            partial = True
            continue
        if isinstance(row, dict) and str(row.get('t', ''))[:10] == day and type(row.get('ms')) is int:
            result.append(row)
    if partial:
        _LAST_PARTIAL[owner or ''] = True
    return result


_LAST_PARTIAL: dict[str, bool] = {}


def _partial(owner: str) -> bool:
    return bool(_LAST_PARTIAL.pop(owner or '', False))


def _duration(ms: int) -> str:
    if ms < 1000:
        return f'{ms} ms'
    if ms < 60_000:
        return f'{ms / 1000:.1f} sn'.replace('.', ',')
    return f'{ms // 60_000} dk {(ms % 60_000) / 1000:.0f} sn'


def summary(owner: str = '', day: str | None = None) -> str:
    day = day or datetime.now(_TR).date().isoformat()
    data = rows(owner, day)
    if not data:
        return (f'{day} için kayıtlı tur yok. Ölçüm bu sürümden sonraki turları sayar; '
                'sohbet ettiysen ve hâlâ boşsa ölçüm yazamıyor demektir.')
    durations = sorted(row['ms'] for row in data)
    total = sum(durations)
    median = durations[len(durations) // 2]
    lines = [f'Tur ölçümü · {day} · {len(data)} tur, toplam {_duration(total)}, '
             f'ortalama {_duration(total // len(data))} (ortanca {_duration(median)}, en uzun {_duration(durations[-1])})']
    sources: dict[str, int] = {}
    for row in data:
        name = row.get('src') or 'bilinmiyor'
        sources[name] = sources.get(name, 0) + 1
    lines.append('Kaynak: ' + ', '.join(f'{name} {count} tur' for name, count in sorted(sources.items(), key=lambda x: -x[1])))
    outcomes: dict[str, int] = {}
    for row in data:
        name = row.get('r') or 'ok'
        outcomes[name] = outcomes.get(name, 0) + 1
    label = {'ok': 'cevap', 'iptal': 'iptal', 'hata': 'hata'}
    lines.append('Sonuç: ' + ', '.join(f'{count} {label.get(name, name)}' for name, count in sorted(outcomes.items(), key=lambda x: -x[1])))
    failures = [row for row in data if row.get('r') == 'hata' and row.get('not')]
    if failures:
        lines.append('Hata nedenleri: ' + ', '.join(sorted({row['not'] for row in failures})))
    if _partial(owner):
        lines.append('Ölçüm kısmi: okunamayan ya da yarım kalmış kayıt var; toplam doğrulanamadı.')
    lines.append('Süre, isteğin alındığı an ile yanıtın yazıldığı an arasındadır; sesin duyulduğu an değildir.')
    return '\n'.join(lines)


_COMMANDS = {'tur olcumu', 'tur ölçümü', 'olcum durumu', 'ölçüm durumu', 'tur durumu',
             'bugun kac tur', 'bugün kaç tur', 'bugun kac tur attim', 'bugün kaç tur attım'}


def handle(owner, command):
    text = ' '.join(str(command or '').casefold().replace('i̇', 'i').split()).strip(' .!?')
    text = re.sub(r'^jarvis[, ]+', '', text)
    if text in _COMMANDS:
        return summary(owner)
    return None
