"""Geri dönüş noktası (checkpoint): Jarvis'in **verisini** tek komutla sakla ve geri al.

Kod zaten git'te: bu modül kodu değil, `~/.jarvis` altındaki kullanıcı verisini (kullanıcılar,
notlar, ayarlar, hedefler, anahtarlar, bilgi tabanı) tek bir zip'e alır. Ağır ve yeniden
üretilebilir klasörler (tarayıcı profili, modeller, ses modelleri, kota/tur sayaçları, sandbox)
**bilerek dışarıda** kalır; aksi hâlde yedek gigabaytlara çıkar ve geri alma işe yaramaz.

Davranış:
- `create()`: `~/.jarvis/checkpoint/<ad>.zip` yazar; en yeni 5 yedek tutulur.
- `restore(ad)`: yedeği **canlı veriye dokunmadan** `~/.jarvis/checkpoint_geri/<zaman>/` içine
  açar. `apply=True` ancak o zaman dosyaların üzerine yazar; varsayılan kuru provadır.
- `maybe_daily()`: açılışta çağrılır; son 24 saatte yedek yoksa bir tane alır (en fazla bir kez).

Hata hâlinde Jarvis çalışmaya devam eder: yedek alınamaması bir turu, güncellemeyi ya da
kapanmayı engellemez; hata tanılama kaydına yazılır.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

from modules.diagnostics import record_failure as _record_failure

ROOT = Path(__file__).resolve().parents[1]
KEEP = 5
MAX_FILE = 25 * 1024 * 1024          # tek dosya üst sınırı: 25 MB
_FOLDERS = ('users', 'goals', 'router', 'permission_audit', 'file-effect-claims', 'kb', 'uploads', 'sandbox')
_FILES = ('settings.json', 'config.json', 'prefs.json', 'phone_token.txt')
_SKIP_DIRS = {'webprofile', 'models', 'voice_models', 'turn_models', 'checkpoint', 'checkpoint_geri',
              'kota', 'tur', 'validation-cache', 'update_backup', 'yerel_yedek', '__pycache__'}


def _data() -> Path:
    from config import DATA_DIR
    return Path(DATA_DIR)


def _dir() -> Path:
    path = _data() / 'checkpoint'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _git_sha() -> str:
    try:
        done = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'],
                              capture_output=True, text=True, timeout=8)
        return done.stdout.strip() if done.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        _record_failure('modules/checkpoint.py:_git_sha')
        return ''


def _candidates() -> list[Path]:
    """Yedeğe girecek dosyalar; ağır klasörler ve tek dosya sınırı üstündekiler atlanır."""
    data = _data()
    picked: list[Path] = []
    for folder in _FOLDERS:
        base = data / folder
        if not base.is_dir():
            continue
        for path in base.rglob('*') if hasattr(base, "rglob") else []:
            if path.is_file() and not (_SKIP_DIRS & set(path.parts)):
                try:
                    if path.stat().st_size <= MAX_FILE:
                        picked.append(path)
                except OSError:
                    _record_failure('modules/checkpoint.py:_candidates')
    for name in _FILES:
        path = data / name
        if path.is_file() and path.stat().st_size <= MAX_FILE:
            picked.append(path)
    for path in data.glob('*.json'):
        if path not in picked and path.stat().st_size <= MAX_FILE:
            picked.append(path)
    return picked


def create(label: str = '') -> dict:
    """Yedek alır ve özetini döndürür. Hata durumunda istisna yerine ok=False döner."""
    try:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        name = stamp + ('-' + label if label else '') + '.zip'
        target = _dir() / name
        files = _candidates()
        manifest = {'when': datetime.now().isoformat(timespec='seconds'), 'label': label,
                    'commit': _git_sha(), 'files': [str(path.relative_to(_data())) for path in files]}
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                bundle.write(path, str(path.relative_to(_data())))
            bundle.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=1))
        _prune()
        return {'ok': True, 'name': name, 'files': len(files), 'bytes': target.stat().st_size,
                'commit': manifest['commit'], 'path': str(target)}
    except Exception as exc:
        _record_failure('modules/checkpoint.py:create')
        return {'ok': False, 'error': str(exc)[:200]}


def items() -> list[dict]:
    """Yedekler, en yeniden eskiye."""
    result = []
    try:
        for path in sorted(_dir().glob('*.zip'), key=lambda p: p.name, reverse=True):
            stat = path.stat()
            result.append({'name': path.name, 'when': datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds'),
                           'bytes': stat.st_size})
    except OSError:
        _record_failure('modules/checkpoint.py:items')
    return result


def _prune() -> None:
    try:
        for old in items()[KEEP:]:
            (_dir() / old['name']).unlink()
    except OSError:
        _record_failure('modules/checkpoint.py:_prune')


def restore(name: str, *, apply: bool = False) -> dict:
    """Yedeği ayrı bir klasöre açar. apply verilmedikçe canlı veriye dokunmaz."""
    try:
        source = _dir() / name
        if not source.is_file():
            return {'ok': False, 'error': 'Yedek bulunamadı: ' + str(name)}
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        folder = _data() / 'checkpoint_geri' / stamp
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source) as bundle:
            bundle.extractall(folder)
        applied = 0
        if apply:
            for path in folder.rglob('*'):
                if path.is_file() and path.name != 'MANIFEST.json':
                    rel = path.relative_to(folder)
                    if _SKIP_DIRS & set(rel.parts):
                        continue
                    dest = _data() / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
                    applied += 1
        return {'ok': True, 'folder': str(folder), 'applied': applied}
    except Exception as exc:
        _record_failure('modules/checkpoint.py:restore')
        return {'ok': False, 'error': str(exc)[:200]}


def last_age_hours() -> float:
    newest = items()[:1]
    if not newest:
        return float('inf')
    try:
        return max((time.time() - (_dir() / newest[0]['name']).stat().st_mtime) / 3600, 0.0)
    except OSError:
        _record_failure('modules/checkpoint.py:last_age_hours')
        return float('inf')


def maybe_daily(hours: float = 24.0) -> dict | None:
    """Açılışta: son yedek hours saatten eskiyse bir tane alır; yoksa hiçbir şey yapmaz."""
    if last_age_hours() < hours:
        return None
    return create('gunluk')


def summary() -> str:
    data = items()
    if not data:
        return ('Kayıtlı geri dönüş noktası yok. `python -X utf8 -m modules.checkpoint create` ile '
                'ilk yedeği alabilirsin.')
    lines = [f'Geri dönüş noktaları ({len(data)}/{KEEP}):']
    for row in data:
        lines.append('- ' + row["name"] + ' · ' + row["when"][:16].replace("T", " ") + ' · ' + format(row["bytes"] / 1048576, ".1f").replace(".", ",") + ' MB')
    lines.append('Geri almak için: `python -X utf8 -m modules.checkpoint restore <ad>` (önce ayrı klasöre açar).')
    return '\n'.join(lines)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else 'list'
    if command == 'create':
        result = create(argv[1] if len(argv) > 1 else '')
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('ok') else 1
    if command == 'restore':
        if len(argv) < 2:
            print('Kullanım: restore <yedek-adı> [--uygula]')
            return 2
        result = restore(argv[1], apply='--uygula' in argv)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('ok') else 1
    print(summary())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
