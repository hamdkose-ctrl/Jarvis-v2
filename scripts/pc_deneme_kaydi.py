"""PC denemelerini yerel bir JSON dosyasına madde madde kaydeden bağımsız araç."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


ITEMS = [
    {'id': 'A1', 'group': 'A', 'text': 'Devam: yarım kalmış PC görevini sürdür.'},
    {'id': 'A2', 'group': 'A', 'text': 'Devam et: bekleyen PC görevini sürdür.'},
    {'id': 'A3', 'group': 'A', 'text': 'PC devam: bekleyen görevi sürdür.'},
    {'id': 'A4', 'group': 'A', 'text': 'İptal: yarım kalmış PC görevini kapat.'},
    {'id': 'A5', 'group': 'A', 'text': 'PC iptal: aktif/bekleyen görevi kapat.'},
    {'id': 'B1', 'group': 'B', 'text': 'Rapordaki B1 PC denemesi.'},
    {'id': 'B2', 'group': 'B', 'text': 'Rapordaki B2 PC denemesi.'},
    {'id': 'B3', 'group': 'B', 'text': 'Rapordaki B3 PC denemesi.'},
    {'id': 'B4', 'group': 'B', 'text': 'Rapordaki B4 PC denemesi.'},
]

_STATUSES = {'c': 'çalıştı', 'y': 'yarım', 'b': 'bozuk', 'a': 'atlandı'}
_EMAIL = re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')
_PHONE = re.compile(r'(?<!\d)(?:\+?90[ .-]?)?0?5\d{2}(?:[ .-]?\d{3})(?:[ .-]?\d{2}){2}(?!\d)')
_TOKEN = re.compile(r'(?i)\b(?:sk[-_]?|ghp_|github_pat_|AIza)[A-Z0-9_-]{8,}\b')


class RecordError(ValueError):
    pass


def _mask_note(value: str) -> str:
    text = str(value or '')
    for pattern in (_EMAIL, _PHONE, _TOKEN):
        text = pattern.sub('***', text)
    return text[:300]


def _empty_state() -> dict:
    return {'results': {}}


def _load(path: Path) -> dict:
    if not path.exists():
        return _empty_state()
    try:
        raw = path.read_text(encoding='utf-8')
        if not raw.strip():
            raise RecordError('Sonuç dosyası boş.')
        data = json.loads(raw)
    except UnicodeError:
        raise RecordError('Sonuç dosyası UTF-8 olarak okunamadı.') from None
    except json.JSONDecodeError:
        raise RecordError('Sonuç dosyası bozuk JSON içeriyor.') from None
    except OSError as exc:
        raise RecordError(f'Sonuç dosyası okunamadı: {exc}.') from None
    if not isinstance(data, dict) or not isinstance(data.get('results'), dict):
        raise RecordError('Sonuç dosyasının yapısı geçersiz.')
    for key, row in data['results'].items():
        if (not isinstance(key, str) or not isinstance(row, dict)
                or row.get('status') not in _STATUSES.values()
                or not isinstance(row.get('note', ''), str)):
            raise RecordError('Sonuç dosyasının yapısı geçersiz.')
    return data


def _save(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.pc-deneme-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def reset(path: Path) -> None:
    _save(Path(path), _empty_state())


def run(items, input_fn=input, print_fn=print, path=Path('pc_deneme_sonuc.json')) -> dict:
    """Cevapsız maddeleri sırayla sorar; her cevabı anında atomik olarak kaydeder."""
    path = Path(path)
    data = _load(path)
    results = data['results']
    for item in items:
        item_id = str(item['id'])
        if item_id in results:
            continue
        print_fn(f"{item_id} [{item['group']}] {item['text']}")
        while True:
            answer = str(input_fn('Sonuç [c=çalıştı, y=yarım, b=bozuk, a=atla]: ')).strip().lower()
            if answer in _STATUSES:
                break
            print_fn('Geçersiz cevap. c, y, b veya a gir.')
        note = ''
        if answer in {'y', 'b'}:
            note = _mask_note(input_fn('Kısa not: '))
        results[item_id] = {'status': _STATUSES[answer], 'note': note}
        _save(path, data)
    return data


def summary(data: dict, items=ITEMS) -> str:
    results = data.get('results', {})
    parts = []
    counts = {'çalıştı': 0, 'yarım': 0, 'bozuk': 0, 'atlandı': 0}
    for item in items:
        row = results.get(item['id'])
        if not row:
            continue
        status = row['status']
        counts[status] += 1
        text = f"{item['id']} {status}"
        if row.get('note') and status in {'yarım', 'bozuk'}:
            text += f": {row['note']}"
        parts.append(text)
    details = '; '.join(parts) if parts else 'Henüz sonuç yok.'
    counter = (f"{counts['çalıştı']} çalıştı, {counts['yarım']} yarım, "
               f"{counts['bozuk']} bozuk, {counts['atlandı']} atlandı")
    return details + '\n' + counter


def _configure_console() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            try:
                reconfigure(encoding='utf-8')
            except (OSError, ValueError):
                pass


def main(argv=None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(description='PC deneme sonuçlarını madde madde kaydet.')
    parser.add_argument('path', nargs='?', default='pc_deneme_sonuc.json', help='Sonuç JSON dosyası')
    parser.add_argument('--bastan', action='store_true', help='Eski cevapları silip baştan başla')
    parser.add_argument('--ozet', action='store_true', help='Oturum açmadan mevcut sonuç özetini yazdır')
    args = parser.parse_args(argv)
    path = Path(args.path)
    try:
        if args.ozet:
            print(summary(_load(path)))
            return 0
        if args.bastan:
            reset(path)
        run(ITEMS, input, print, path)
        print('\n' + summary(_load(path)))
        return 0
    except RecordError as exc:
        print(f'Hata: {exc}')
        return 2
    except KeyboardInterrupt:
        print('\nDeneme kaydı durduruldu; önceki cevaplar kaydedildi.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
