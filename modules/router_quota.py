"""Cross-process atomic request and optional reserved-token limits, enabled only by verified developer policy.

Policies exist only for exact provider/model rows a developer reviewed against an
official published limits page with a bounded validity date; every other provider
stays without a policy and no limit is ever guessed. SQLite BEGIN IMMEDIATE
prevents two local processes from consuming the last request slot concurrently.
Windows are rolling 60s and 24h (conservative).
No keys, user text or model responses are stored. This is not a provider billing
hard stop, and neuron usage is not currently metered. Token policies require a
trusted caller-provided upper bound for total input+output, not guessed tokens.
"""
from __future__ import annotations

import math
import json
import hashlib
from contextlib import contextmanager,ExitStack,closing
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
from modules.diagnostics import record_failure as _record_failure

# Groq's official Free plan base request caps for the three routed text models,
# reviewed 16 Nov 2026 on https://console.groq.com/docs/rate-limits. The page is
# org-level and "there may be exceptions", so this is a conservative local request
# ceiling, not a provider billing hard stop; the observed-429 gate still covers
# exceptions below the base value. Free TPM (8K) is deliberately NOT reserved: no
# caller supplies a trusted input+max-output upper bound and a tpm policy without
# one would fail-closed every Groq send. Gemini/Cloudflare pages publish no static
# free-tier RPM/RPD numbers, so they stay policy-less until a real verified source.
POLICIES: dict[tuple[str, str], dict] = {
    ('groq', model): {
        'source_url': 'https://console.groq.com/docs/rate-limits',
        'verified_at': 1794855600,  # 16 Nov 2026 19:00 UTC
        'expires_at': 1795460400,   # 23 Nov 2026 19:00 UTC — re-review before expiry
        'rpm': 30, 'rpd': 1000,
    } for model in ('openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'qwen/qwen3.8-27b')
}
_OWNER = re.compile(r'^[\w-]{1,100}$', re.UNICODE)


def write_trace(owner, record, *, directory):
    """Safe metadata in the existing quota database; never prompt/answer/secret."""
    if not isinstance(owner,str) or not _OWNER.fullmatch(owner):raise ValueError('Rota sahibi geçersiz.')
    path=Path(directory)/'atomic_requests.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ReservationUnavailable('Rota kaydı sembolik bağ olamaz.')
    with closing(sqlite3.connect(str(path),timeout=8)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS route_traces (owner TEXT,request_id TEXT,call_id TEXT,updated REAL,body TEXT,PRIMARY KEY(owner,request_id,call_id))')
        db.execute('INSERT OR REPLACE INTO route_traces VALUES(?,?,?,?,?)',
                   (owner,record['request_id'],record['call_id'],record['updated'],json.dumps(record,ensure_ascii=False,allow_nan=False)))
        db.execute('DELETE FROM route_traces WHERE owner=? AND rowid NOT IN (SELECT rowid FROM route_traces WHERE owner=? ORDER BY updated DESC LIMIT 512)',(owner,owner))


def read_trace(owner, request_id, *, directory):
    path=Path(directory)/'atomic_requests.sqlite3'
    if not path.exists():return None
    if path.is_symlink():raise ReservationUnavailable('Rota kaydı sembolik bağ olamaz.')
    with closing(sqlite3.connect(str(path),timeout=8)) as db, db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='route_traces'").fetchone():return None
        row=db.execute('SELECT body FROM route_traces WHERE owner=? AND request_id=? ORDER BY updated DESC LIMIT 1',(owner,request_id)).fetchone()
    return json.loads(row[0]) if row else None


def recent_traces(owner, *, directory, limit=12):
    path=Path(directory)/'atomic_requests.sqlite3'
    if not path.exists():return []
    if path.is_symlink():raise ReservationUnavailable('Rota kaydı sembolik bağ olamaz.')
    with closing(sqlite3.connect(str(path),timeout=8)) as db, db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='route_traces'").fetchone():return []
        rows=db.execute('SELECT body FROM route_traces WHERE owner=? ORDER BY updated DESC LIMIT ?',
                        (owner,min(50,max(1,limit)))).fetchall()
    return [json.loads(row[0]) for row in rows]


def role_qualified(owner,provider,model,connection_id,*,fingerprint,binding,directory):
    path=Path(directory)/'atomic_requests.sqlite3'
    if not path.exists() or path.is_symlink():return False
    with closing(sqlite3.connect(str(path),timeout=8)) as db, db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='role_qualifications'").fetchone():return False
        row=db.execute('SELECT fingerprint,binding,expires FROM role_qualifications WHERE owner=? AND provider=? AND model=? AND connection_id=?',
                       (owner,provider,model,connection_id or '')).fetchone()
    return bool(row and row[0]==fingerprint and row[1]==binding and row[2]>time.time())


def qualify_role(owner,spec,report,*,fingerprint,directory,corpus_sha256,expected_cases):
    """Manual full-corpus result, not a checkbox/model-size/native-schema claim."""
    rows=report.get('results',[])
    if (report.get('state')!='passed' or report.get('scope')!='holdout'
            or report.get('semantic_acceptance') is not True or report.get('corpus_sha256')!=corpus_sha256
            or type(report.get('accuracy')) not in (int,float) or not math.isfinite(report['accuracy']) or not .95<=report['accuracy']<=1
            or type(report.get('incorrect_action_proposals')) is not int or report['incorrect_action_proposals']!=0
            or type(report.get('attempted_effects')) is not int or report['attempted_effects']!=0
            or type(expected_cases) is not int or expected_cases<20 or report.get('planned_cases')!=expected_cases
            or not isinstance(rows,list) or len(rows)!=expected_cases or type(report.get('provider_responses')) is not int
            or report['provider_responses']<len(rows)
            or report.get('qualified_target')!={'provider':spec.provider,'model':spec.model,'connection_id':spec.connection_id}
            or any(not isinstance(row,dict) or row.get('responded') is not True for row in rows)
            or report.get('accuracy')!=sum(row.get('correct') is True for row in rows)/expected_cases):
        raise ValueError('Tam ve ölçülmüş Brain rol kabulü gerekli.')
    path=Path(directory)/'atomic_requests.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ReservationUnavailable('Kabul kaydı sembolik bağ olamaz.')
    with closing(sqlite3.connect(str(path),timeout=8)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS role_qualifications(owner TEXT,provider TEXT,model TEXT,connection_id TEXT,fingerprint TEXT,binding TEXT,expires REAL,head TEXT,corpus TEXT,PRIMARY KEY(owner,provider,model,connection_id))')
        db.execute('INSERT OR REPLACE INTO role_qualifications VALUES(?,?,?,?,?,?,?,?,?)',
            (owner,spec.provider,spec.model,spec.connection_id or '',fingerprint,spec.binding or str(spec.connection_revision),
             time.time()+7*86400,report.get('head'),corpus_sha256))


def reserve_custom(owner,ident,revision,*,directory,attempt_id=None,cost_bound=None,request=None):
    """Explicit custom connection's LOCAL daily request ceiling, not a dollar/billing guarantee."""
    from modules import router_connections
    try:row,_=router_connections.resolve(owner,ident,revision=revision)
    except (ValueError,OSError) as exc:raise ReservationUnavailable('Özel bağlantı değişti.') from exc
    ceiling=row['daily_requests']
    if request is not None and request.work_class=='background':
        ceiling=min(ceiling,request_ceiling(request))
    return reserve(owner,custom_provider(row),row['model'],directory=directory,
                   application_limit=ceiling,quota_scope=custom_scope(owner,row),
                   attempt_id=attempt_id,cost_limit=row.get('daily_cost_microusd'),cost_bound=cost_bound)


def request_ceiling(request):
    from modules import smart_router
    limits=smart_router.settings(request.owner)['application_limits']
    ceiling=limits['daily_requests']
    if request.work_class=='background':ceiling-=limits.get('interactive_daily_reserve',0)
    if ceiling<1:raise ReservationExhausted(86400)
    return ceiling


def custom_provider(row):
    return 'custom:'+hashlib.sha256(row['base_url'].encode()).hexdigest()[:32]


def custom_scope(owner,row):
    from modules import router_connections
    if row.get('quota_group'):return 'project:'+row['quota_group']
    _current,key=router_connections.resolve(owner,row['id'],revision=row['revision'],require_enabled=False)
    return 'key:'+hashlib.sha256((row['base_url']+':'+key).encode()).hexdigest()


def account_scope(request,spec):
    from modules import smart_router,router_connections,llm
    if spec.connection_id:
        row,_=router_connections.resolve(request.owner,spec.connection_id,revision=spec.connection_revision)
        if router_connections.is_local(row['base_url']):return 'local:loopback'
        return custom_scope(request.owner,row)
    if spec.provider=='ollama':
        info=llm.provider_configuration()
        from urllib.parse import urlsplit
        host=urlsplit(str(info.get('url') or '')).hostname or ''
        return 'local:loopback' if host in ('localhost','127.0.0.1','::1') else 'local:'+hashlib.sha256(host.encode()).hexdigest()
    configured=smart_router.settings(request.owner)['account_scopes'].get(spec.provider)
    if configured:return 'project:'+configured
    if spec.provider=='cloudflare':
        from modules import cloudflare_chat
        account=cloudflare_chat.user_cloudflare_account(request.owner)
        return 'account:'+hashlib.sha256(str(account or '').encode()).hexdigest()
    return 'key:'+smart_router._connection_fingerprint(request.owner,spec.provider)


@contextmanager
def admission(request,spec,*,directory):
    """Provider slots on the EXISTING Core LeaseTable/OS claims; never a new queue/scheduler."""
    from modules import smart_router,resource_leases,goal_executor
    limits=smart_router.settings(request.owner)['application_limits']
    account=account_scope(request,spec)
    count=1 if account.startswith('local:') else limits['max_parallel']
    reserved=0 if count==1 else limits['interactive_reserved']
    slots=range(reserved,count) if request.work_class=='background' else range(count)
    scope=('local' if account.startswith('local:') else spec.provider)+':'+account
    root=Path(directory)/'provider-claims'
    root.mkdir(parents=True,exist_ok=True)
    if root.is_symlink():raise ReservationUnavailable('Sağlayıcı claim dizini geçersiz.')
    leases=goal_executor._RESOURCE_LEASES
    for index in slots:
        digest=hashlib.sha256((scope+':'+str(index)).encode()).hexdigest()[:40]
        key=resource_leases.resource_key('provider',digest)
        ticket=None;stack=ExitStack()
        try:
            ticket=leases.acquire(owner=request.owner,job_id=request.call_id,step_id='model-'+str(index),
                plan_version=1,command_id=request.call_id+'-'+str(index),keys=(key,),ttl=300)
            stack.enter_context(resource_leases.process_resource_claim(root,key))
        except resource_leases.LeaseConflict:
            stack.close()
            if ticket is not None and leases.validate(ticket):leases.release(ticket)
            continue
        try:
            with stack:yield
        finally:
            if leases.validate(ticket):leases.release(ticket)
        return
    error=ReservationUnavailable('Sağlayıcı çağrı kapasitesi dolu; mevcut runtime beklemeyi/sürdürmeyi yönetir.')
    error.reason_code='PROVIDER_CAPACITY_BUSY';error.retry_after=1
    raise error


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
            now: float | None = None, token_budget: int | None = None,
            quota_scope: str | None = None, application_limit: int | None = None,
            attempt_id: str | None = None,cost_limit: int | None = None,cost_bound: int | None = None) -> bool:
    """Reserve one request atomically; false means no developer policy configured.

    A configured but invalid policy or an inaccessible DB blocks the call.
    Failed HTTP sends retain their reservation (conservative local accounting).
    A configured TPM/TPD policy REQUIRES a developer-trusted upper bound for
    total input+max output tokens; no estimate means fail-closed no send.
    """
    current = time.time() if now is None else now
    if cost_limit is not None:
        if type(cost_limit) is not int or not 1<=cost_limit<=10**12 or type(cost_bound) is not int or cost_bound<0:
            raise ReservationUnavailable('Parasal tavan için doğrulanmış çağrı maliyet üst sınırı gerekli; bilinmeyen fiyatla gönderilmedi.')
    limits = _policy(provider, model, current)
    if application_limit is not None:
        if type(application_limit) is not int or not 1<=application_limit<=500000:
            raise ReservationUnavailable('Uygulama çağrı tavanı geçersiz.')
        limits=(application_limit,application_limit,None,None) if limits is None else (
            min(limits[0],application_limit),min(limits[1],application_limit),limits[2],limits[3])
    if limits is None:
        return False
    if quota_scope is not None and (not isinstance(quota_scope,str) or not re.fullmatch(r'[\w.:/-]{1,240}',quota_scope)):
        raise ReservationUnavailable('Kota scope kimliği geçersiz.')
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
    if path.is_symlink():raise ReservationUnavailable('Kota kaydı sembolik bağ olamaz.')
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
        columns={r[1] for r in db.execute('PRAGMA table_info(requests)')}
        if 'quota_scope' not in columns:db.execute('ALTER TABLE requests ADD COLUMN quota_scope TEXT')
        if 'attempt_id' not in columns:db.execute('ALTER TABLE requests ADD COLUMN attempt_id TEXT')
        if 'cost_units' not in columns:db.execute('ALTER TABLE requests ADD COLUMN cost_units INTEGER')
        if 'actual_tokens' not in columns:db.execute('ALTER TABLE requests ADD COLUMN actual_tokens INTEGER')
        db.execute('CREATE INDEX IF NOT EXISTS idx_req_key_time'
                   ' ON requests(owner,provider,model,stamp)')
        db.execute('DELETE FROM requests WHERE stamp<=?', (current - 86400,))
        key = (owner, provider, model)
        if quota_scope is None:
            day = db.execute('SELECT stamp, token_units FROM requests'
                             ' WHERE owner=? AND provider=? AND model=? AND stamp>?'
                             ' ORDER BY stamp', (*key, current - 86400)).fetchall()
        else:
            day = db.execute('SELECT stamp, token_units FROM requests WHERE provider=? AND '
                '(quota_scope=? OR (owner=? AND quota_scope IS NULL)) AND stamp>? ORDER BY stamp',
                (provider,quota_scope,owner,current-86400)).fetchall()
        if tpm is not None and any(units < 0 for _, units in day):
            db.rollback()
            raise ReservationUnavailable('Eski isteklerin token maliyeti bilinmiyor.')
        if cost_limit is not None:
            costs=db.execute('SELECT cost_units FROM requests WHERE owner=? AND provider=? AND stamp>?',
                             (owner,provider,current-86400)).fetchall()
            if any(row[0] is None for row in costs):raise ReservationUnavailable('Önceki çağrıların parasal maliyeti bilinmiyor; tavan doğrulanamadı.')
            if sum(row[0] for row in costs)+cost_bound>cost_limit:raise ReservationExhausted(86400)
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
        db.execute('INSERT INTO requests(owner,provider,model,stamp,token_units,quota_scope,attempt_id,cost_units)'
                   ' VALUES(?,?,?,?,?,?,?,?)',
                   (*key, current, -1 if token_budget is None else token_budget,quota_scope,attempt_id,cost_bound))
        db.commit()
        return True
    except (sqlite3.Error, OSError) as exc:
        _record_failure('modules/router_quota.py:reserve')
        raise ReservationUnavailable('Yerel kota rezervasyonu yazılamadı.') from exc
    finally:
        if db is not None:
            db.close()


def reconcile(owner,attempt_id,usage,*,directory):
    # Only an exact provider total is trustworthy across reasoning/cache billing
    # conventions. Missing totals retain the reservation, even on cancellation.
    actual=usage.get('total_tokens') if isinstance(usage,dict) else None
    if type(actual) is not int or actual<0:return
    path=Path(directory)/'atomic_requests.sqlite3'
    if not path.exists() or path.is_symlink():return
    try:
        with closing(sqlite3.connect(str(path),timeout=8)) as db, db:
            columns={r[1] for r in db.execute('PRAGMA table_info(requests)')}
            if 'actual_tokens' not in columns:return
            db.execute('UPDATE requests SET actual_tokens=?,token_units=? WHERE owner=? AND attempt_id=?',
                       (actual,actual,owner,attempt_id))
    except (sqlite3.Error,OSError):
        _record_failure('modules/router_quota.py:reconcile')
