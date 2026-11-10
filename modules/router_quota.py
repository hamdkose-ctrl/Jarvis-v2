"""Cross-process atomic request and optional reserved-token limits, enabled only by verified developer policy.

Policies are deliberately empty until official exact-model RPM/RPD limits are
reviewed. SQLite BEGIN IMMEDIATE prevents two local processes from consuming
the last request slot concurrently. Windows are rolling 60s and 24h (conservative).
No keys, user text or model responses are stored. This is not a provider billing
hard stop, and neuron usage is not currently metered. Token policies require a
trusted caller-provided upper bound for total input+output, not guessed tokens.
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


def _policy(provider: str, model: str, now: float) -> tuple[int, int, int | None, int | None] | None:
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
    tpm, tpd = row.get('tpm'), row.get('tpd')
    if tpm is not None or tpd is not None:
        valid_limits = (valid_limits and type(tpm) is int and type(tpd) is int
                        and 1 <= tpm <= 50_000_000 and tpm <= tpd <= 1_000_000_000)
    if not (source_ok and valid_date and valid_limits):
        raise ReservationUnavailable('Yerel kota kaynağı veya geçerliliği doğrulanmamış.')
    return rpm, rpd, tpm, tpd

def _window_wait(rows: list[tuple[float, int]], *, now: float, window: int,
                 max_requests: int, max_tokens: int | None, cost: int) -> int:
    """First future release where both request and conservative token units fit."""
    count = len(rows)
    tokens = sum(max(0, units) for _, units in rows)
    if count < max_requests and (max_tokens is None or tokens + cost <= max_tokens):
        return 0
    for stamp, units in rows:
        count -= 1
        tokens -= max(0, units)
        if count < max_requests and (max_tokens is None or tokens + cost <= max_tokens):
            return max(1, math.ceil(stamp + window - now))
    return window


def reserve(owner: str, provider: str, model: str, *, directory: Path,
            now: float | None = None, token_budget: int | None = None) -> bool:
    """Reserve one request atomically; false means no developer policy configured.

    A configured but invalid policy or an inaccessible DB blocks the call.
    Failed HTTP sends retain their reservation (conservative local accounting).
    A configured TPM/TPD policy REQUIRES a developer-trusted upper bound for
    total input+max output tokens; no estimate means fail-closed no send.
    """
    current = time.time() if now is None else now
    limits = _policy(provider, model, current)
    if limits is None:
        return False
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise ReservationUnavailable('Model kota kullanıcı bağlamı geçersiz.')
    rpm, rpd, tpm, tpd = limits
    if token_budget is not None and (
            type(token_budget) is not int or not 1 <= token_budget <= 2_000_000):
        raise ReservationUnavailable('Model token rezervasyon üst sınırı geçersiz.')
    if tpm is not None and token_budget is None:
        raise ReservationUnavailable('Doğrulanmış token üst sınırı olmadan istek yasak.')
    if tpm is not None and (token_budget > tpm or token_budget > tpd):
        raise ReservationExhausted(86400 if token_budget > tpd else 60)
    path = Path(directory) / 'atomic_requests.sqlite3'
    db = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), timeout=8, isolation_level=None)
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS requests ('
                   'owner TEXT NOT NULL, provider TEXT NOT NULL,'
                   'model TEXT NOT NULL, stamp REAL NOT NULL,'
                   'token_units INTEGER NOT NULL DEFAULT -1)')
        if 'token_units' not in {r[1] for r in db.execute('PRAGMA table_info(requests)')}:
            # Existing count-only rows have UNKNOWN token usage: never migrate as zero.
            db.execute('ALTER TABLE requests ADD COLUMN token_units INTEGER NOT NULL DEFAULT -1')
        db.execute('CREATE INDEX IF NOT EXISTS idx_req_key_time'
                   ' ON requests(owner,provider,model,stamp)')
        db.execute('DELETE FROM requests WHERE stamp<=?', (current - 86400,))
        key = (owner, provider, model)
        day = db.execute('SELECT stamp, token_units FROM requests'
                         ' WHERE owner=? AND provider=? AND model=? AND stamp>?'
                         ' ORDER BY stamp', (*key, current - 86400)).fetchall()
        if tpm is not None and any(units < 0 for _, units in day):
            db.rollback()
            raise ReservationUnavailable('Eski isteklerin token maliyeti bilinmiyor.')
        minute = [(stamp, units) for stamp, units in day if stamp > current - 60]
        cost = 0 if tpm is None else token_budget
        wait = max(
            _window_wait(minute, now=current, window=60, max_requests=rpm,
                         max_tokens=tpm, cost=cost),
            _window_wait(day, now=current, window=86400, max_requests=rpd,
                         max_tokens=tpd, cost=cost))
        if wait:
            db.rollback()
            raise ReservationExhausted(wait)
        db.execute('INSERT INTO requests(owner,provider,model,stamp,token_units)'
                   ' VALUES(?,?,?,?,?)',
                   (*key, current, -1 if token_budget is None else token_budget))
        db.commit()
        return True
    except (sqlite3.Error, OSError) as exc:
        _record_failure('modules/router_quota.py:reserve')
        raise ReservationUnavailable('Yerel kota rezervasyonu yazılamadı.') from exc
    finally:
        if db is not None:
            db.close()
