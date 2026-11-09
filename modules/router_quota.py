"""Cross-process atomic request-count limits, enabled only by verified developer policy.

Policies are deliberately empty until official exact-model RPM/RPD limits are
reviewed. SQLite BEGIN IMMEDIATE prevents two local processes from consuming
the last request slot concurrently. Windows are rolling 60s and 24h (conservative).
No keys, user text or model responses are stored. This is not a provider billing
hard stop and does not enforce TPM, TPD or neuron usage.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
from modules.diagnostics import record_failure as _record_failure

POLICIES: dict[tuple[str, str], dict] = {}
_OWNER = re.compile(r'^[\w-]{1,100}$', re.UNICODE)


class ReservationUnavailable(RuntimeError):
    reason_code = 'PROVIDER_LOCAL_QUOTA_UNAVAILABLE'
    retry_after = 0


class ReservationExhausted(RuntimeError):
    reason_code = 'PROVIDER_LOCAL_QUOTA_EXHAUSTED'

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__('Yerel model istek rezervasyon limiti doldu.')


def _policy(provider: str, model: str, now: float) -> tuple[int, int] | None:
    row = POLICIES.get((provider, model))
    if row is None:
        return None
    if not isinstance(row, dict):
        raise ReservationUnavailable('Yerel kota politikası geçersiz.')
    source = row.get('source_url')
    try:
        uri = urlsplit(source) if isinstance(source, str) else None
        source_ok = bool(uri and uri.scheme == 'https' and uri.hostname
                         and not uri.username and not uri.password)
    except ValueError:
        source_ok = False
    verified, expires = row.get('verified_at'), row.get('expires_at')
    valid_date = (type(verified) in (int, float) and type(expires) in (int, float)
                  and math.isfinite(verified) and math.isfinite(expires)
                  and 0 < verified <= now + 60 and verified < expires
                  and now < expires and expires - verified <= 31 * 86400)
    rpm, rpd = row.get('rpm'), row.get('rpd')
    valid_limits = (type(rpm) is int and type(rpd) is int
                    and 1 <= rpm <= 5000 and rpm <= rpd <= 500000)
    if not (source_ok and valid_date and valid_limits):
        raise ReservationUnavailable('Yerel kota kaynağı veya geçerliliği doğrulanmamış.')
    return rpm, rpd


def reserve(owner: str, provider: str, model: str, *, directory: Path,
            now: float | None = None) -> bool:
    """Reserve one request atomically; false means no developer policy configured.

    A configured but invalid policy or an inaccessible DB blocks the call.
    Failed HTTP sends retain their reservation (conservative local accounting).
    """
    current = time.time() if now is None else now
    limits = _policy(provider, model, current)
    if limits is None:
        return False
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise ReservationUnavailable('Model kota kullanıcı bağlamı geçersiz.')
    path = Path(directory) / 'atomic_requests.sqlite3'
    db = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), timeout=8, isolation_level=None)
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS requests ('
                   'owner TEXT NOT NULL, provider TEXT NOT NULL,'
                   'model TEXT NOT NULL, stamp REAL NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_req_key_time'
                   ' ON requests(owner,provider,model,stamp)')
        db.execute('DELETE FROM requests WHERE stamp<=?', (current - 86400,))
        key = (owner, provider, model)
        minute = db.execute('SELECT COUNT(*), MIN(stamp) FROM requests'
                            ' WHERE owner=? AND provider=? AND model=? AND stamp>?',
                            (*key, current - 60)).fetchone()
        day = db.execute('SELECT COUNT(*), MIN(stamp) FROM requests'
                         ' WHERE owner=? AND provider=? AND model=? AND stamp>?',
                         (*key, current - 86400)).fetchone()
        wait = []
        if minute[0] >= limits[0]:
            wait.append(max(1, math.ceil(minute[1] + 60 - current)))
        if day[0] >= limits[1]:
            wait.append(max(1, math.ceil(day[1] + 86400 - current)))
        if wait:
            db.rollback()
            raise ReservationExhausted(max(wait))
        db.execute('INSERT INTO requests(owner,provider,model,stamp) VALUES(?,?,?,?)',
                   (*key, current))
        db.commit()
        return True
    except (sqlite3.Error, OSError) as exc:
        _record_failure('modules/router_quota.py:reserve')
        raise ReservationUnavailable('Yerel kota rezervasyonu yazılamadı.') from exc
    finally:
        if db is not None:
            db.close()
