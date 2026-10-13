"""Standard-library release journal and recovery, usable before application imports."""
from __future__ import annotations
from contextlib import contextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

KEEP = 3
MAX_BYTES = 100 * 1024 * 1024
EXCLUDED = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache', '.backups', 'backups', '.gradle', 'build'}
PROTECTED = {'release_guard.py', 'launcher.py', 'scripts/baslat.bat', 'baslat.bat', 'modules/release_workspace.py', 'modules/validation.py'}


def _cleanup_workspace(folder):
    """Windows may briefly retain a test directory handle after a child exits."""
    def writable_retry(operation, path, error):
        if getattr(error[1], 'winerror', None) != 5:
            raise error[1]
        import stat
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        operation(path)
    for delay in (0, .05, .1, .2, .4, .8):
        if delay:
            time.sleep(delay)
        try:
            shutil.rmtree(folder, onerror=writable_retry)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if getattr(exc, 'winerror', None) not in (32, 33):
                raise
    import logging
    logging.getLogger(__name__).warning('Windows geçici test klasörünü kilitli tutuyor; temizlik ertelendi: %s', folder)


@contextmanager
def temporary_workspace(prefix):
    """Only a cleanup sharing violation may be deferred, never a test failure."""
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield folder
    finally:
        _cleanup_workspace(folder)


def _record_failure(location):
    # Recovery diagnostics cannot import potentially broken application modules.
    import sys
    error = sys.exc_info()[0]
    text = location + ': ' + (error.__name__ if error else 'unknown') + '\n'
    try:
        folder = data_root(); folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'safe_start.log').open('a', encoding='utf-8') as output: output.write(text)
    except OSError:
        pass


def data_root():
    return Path(os.environ.get('JARVIS_DATA_DIR') or Path.home() / '.jarvis')


def store(project, data=None):
    key = hashlib.sha256(str(Path(project).resolve()).encode()).hexdigest()[:16]
    return Path(data or data_root()) / 'releases' / key


def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.release-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False).encode('utf-8'))


def read(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def protected_source(name):
    # Normalize aliases and Windows case before matching recovery infrastructure.
    return Path(str(name)).as_posix().casefold() in {p.casefold() for p in PROTECTED}


def safe_path(project, name):
    p = Path(name)
    if p.is_absolute() or not p.parts or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('Geçersiz kaynak yolu.')
    result = Path(project) / p
    for part in (result, *result.parents):
        if part == Path(project): break
        if part.is_symlink(): raise ValueError('Sembolik bağlantı kaynak kapsamı dışında.')
    result.resolve().relative_to(Path(project).resolve())
    return result


def contents(path):
    return Path(path).read_bytes() if Path(path).exists() else None


def copy_source(project, target):
    """Copy source/assets, never virtual environments or private runtime data."""
    project, target = Path(project).resolve(), Path(target).resolve()
    private = data_root().resolve()
    def ignore(folder, names):
        ignored = []
        for name in names:
            p = Path(folder) / name
            if name in EXCLUDED or name in {'.env', 'settings.json', 'gemini_key.txt', 'groq_key.txt', 'github_token.txt', 'phone_token.txt'} or p.is_symlink() or p.resolve() == private or p.resolve() == target:
                ignored.append(name)
        return ignored
    shutil.copytree(project, target, ignore=ignore)


def current_python(project, fallback, data=None):
    return read(store(project, data) / 'runtime.json', {}).get('python') or str(fallback)


def pending(project, data=None):
    folder = store(project, data)
    ident = read(folder / 'pending.json')
    return read(folder / 'history' / (ident + '.json')) if ident else None


def prepare(project, records, owner, python=None, data=None):
    folder = store(project, data)
    if pending(project, data): raise ValueError('Önce bekleyen geliştirmeyi yeniden başlat veya geri al.')
    ident = uuid.uuid4().hex
    item = {'id': ident, 'project': str(Path(project).resolve()), 'owner': owner,
            'status': 'applying', 'created': time.time(), 'files': records,
            'previous_python': current_python(project, __import__('sys').executable, data),
            'python': python or current_python(project, __import__('sys').executable, data)}
    encoded = json.dumps(item).encode()
    if len(encoded) > MAX_BYTES: raise ValueError('Bu değişiklik yedek boyutu sınırını aşıyor; parçalara böl.')
    save(folder / 'history' / (ident + '.json'), item)
    save(folder / 'pending.json', ident)
    return item


def update(project, item, status, data=None):
    item['status'] = status
    if status == 'applying' and len(json.dumps(item).encode()) > MAX_BYTES:
        raise ValueError('Bu değişiklik yedek boyutu sınırını aşıyor.')
    save(store(project, data) / 'history' / (item['id'] + '.json'), item)


def installed(project, item, data=None):
    save(store(project, data) / 'runtime.json', {'python': item['python']})
    update(project, item, 'awaiting_start', data)


def restore(project, item, data=None):
    active = read(store(project, data) / 'pending.json')
    if active and active != item['id']:
        raise ValueError('Başka bir sürüm işlemi bekliyor; geri alma başlatılmadı.')
    # Validate the whole set first: never overwrite subsequent manual edits.
    for name, rec in item['files'].items():
        before = base64.b64decode(rec['before']) if rec['before'] is not None else None
        if digest(contents(safe_path(project, name))) not in {digest(before), rec['after']}:
            raise ValueError('Kurtarma durduruldu; dosya sonradan değişmiş: ' + name)
    # A confirmed release has no pending pointer. Recreate it before the first
    # rollback write, so an interrupted later undo is recoverable at startup.
    save(store(project, data) / 'pending.json', item['id'])
    update(project, item, 'rolling_back', data)
    for name, rec in item['files'].items():
        p = safe_path(project, name)
        if rec['before'] is None: p.unlink(missing_ok=True)
        else: atomic(p, base64.b64decode(rec['before']))
    save(store(project, data) / 'runtime.json', {'python': item['previous_python']})
    if item.get('development_state_path'):
        save(item['development_state_path'], item['development_state_before'])
    update(project, item, 'rolled_back', data)
    clear_pending(project, item, data)


def clear_pending(project, item, data=None):
    folder = store(project, data)
    if read(folder / 'pending.json') == item['id']:
        (folder / 'pending.json').unlink(missing_ok=True)


def recover(project, data=None):
    item = pending(project, data)
    if item and item['status'] in {'applying', 'rolling_back'}:
        restore(project, item, data)
        return True
    # A completed rollback/confirmation whose pointer cleanup was interrupted.
    if item and item['status'] in {'rolled_back', 'confirmed'}:
        clear_pending(project, item, data)
    return False


def confirm(project, item, data=None):
    update(project, item, 'confirmed', data)
    clear_pending(project, item, data)
    try:
        cleanup(project, data)
    except (OSError, ValueError):
        _record_failure('release_guard.py:cleanup')


def cleanup(project, data=None):
    folder = store(project, data); history = folder / 'history'
    active = read(folder / 'pending.json')
    files = sorted(history.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
    confirmed = next((read(p)['id'] for p in files if read(p)['status'] == 'confirmed'), None)
    kept, size, protected_python = 0, 0, {current_python(project, '', data)}
    for p in files:
        item = read(p)
        protected = item['id'] in {active, confirmed} or item['status'] in {'applying', 'rolling_back', 'awaiting_start'}
        retain = protected or (kept < KEEP and size + p.stat().st_size <= MAX_BYTES)
        if retain:
            kept += 1; size += p.stat().st_size
            protected_python.update((item['python'], item['previous_python']))
        else: p.unlink()
    # Only environments owned by this installation; never delete the original .venv.
    for env in (folder / 'environments').glob('*'):
        if env.is_dir() and str(environment_python(env)) not in protected_python:
            shutil.rmtree(env)


def environment_python(env):
    return Path(env) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def ready(component):
    """Separate engine/server startup markers; no user secrets in the handshake."""
    location = os.environ.get('JARVIS_BOOT_MARKERS')
    if location and component in {'engine', 'web'}:
        atomic(Path(location) / component, os.environ['JARVIS_BOOT_ID'].encode())
