"""User-declared hardware acceptance, isolated by owner and computer; never an automated pass."""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
from pathlib import Path
import platform
import sqlite3
import uuid
from config import DATA_DIR

CHECKS = ('wake_word_microphone', 'screen_camera', 'speaker_voice_quality',
          'other_live_accounts', 'restart_and_queue')
ROOT = DATA_DIR / 'acceptance'


def _machine():
    system = platform.system()
    installation = ''
    try:
        if system == 'Windows':
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                value, _ = winreg.QueryValueEx(key, 'MachineGuid')
                if isinstance(value, str):
                    installation = value.strip()
        elif system == 'Linux':
            with Path('/etc/machine-id').open(encoding='ascii') as stream:
                installation = stream.read(128).strip()
    except (OSError, ValueError, ImportError):
        pass
    # No raw host/OS identifier is persisted or included in the acceptance report.
    installation = installation or str(uuid.getnode())
    return hashlib.sha256((system + '|' + platform.node() + '|' + installation).encode('utf-8')).hexdigest()


def update(owner, *, confirm=(), reset=()):
    from modules.service_store import identity
    identity(owner)
    confirm, reset = tuple(confirm), tuple(reset)
    if any(name not in CHECKS for name in (*confirm, *reset)) or set(confirm) & set(reset):
        raise ValueError('Manuel kabul alanı geçersiz veya çelişkili.')
    path = ROOT / (owner + '.sqlite3')
    if any(p.is_symlink() for p in (ROOT, path, *ROOT.parents)) or any(
            path.with_name(path.name + suffix).is_symlink() for suffix in ('-journal', '-wal', '-shm')):
        raise ValueError('Kabul kaydı sembolik bağ olamaz.')
    if not path.exists() and not (confirm or reset):
        return {}
    ROOT.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS manual(machine TEXT, name TEXT, checked_at TEXT, PRIMARY KEY(machine,name))')
        machine = _machine()
        for name in reset:
            db.execute('DELETE FROM manual WHERE machine=? AND name=?', (machine, name))
        for name in confirm:
            db.execute('INSERT OR REPLACE INTO manual VALUES(?,?,?)',
                       (machine, name, datetime.now(timezone.utc).isoformat()))
        return dict(db.execute('SELECT name,checked_at FROM manual WHERE machine=?', (machine,)))
