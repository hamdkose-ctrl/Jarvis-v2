"""Durable exact-content approvals, standing destination grants and send-once journal."""
import hashlib
import json
import time
import uuid
import unicodedata
from datetime import datetime, timedelta, timezone
from modules import publish_services as services, service_store, requests_state, privacy
from modules.diagnostics import record_failure as _record_failure

# Conservative personal-assistant budgets, per user; all destinations share them.
# Unknown outcomes also consume a slot: never assume a failed HTTP response means
# the provider did not send. Instagram preparation polling reuses the same slot.
DAILY_CHANNEL_LIMITS = {'gmail': 20, 'telegram': 30, 'whatsapp': 20, 'instagram': 5, 'youtube': 3}
DAILY_TOTAL_LIMIT = 50
DUPLICATE_WINDOW_SECONDS = 600
# Istanbul has used UTC+3 year-round since 2016; no Windows tzdata dependency.
_ISTANBUL = timezone(timedelta(hours=3), 'Europe/Istanbul')
_CHANNEL_NAMES = {'gmail': 'mail', 'telegram': 'Telegram', 'whatsapp': 'WhatsApp',
                  'instagram': 'Instagram', 'youtube': 'YouTube'}


def _budget_day(stamp):
    return datetime.fromtimestamp(stamp, _ISTANBUL).date().isoformat()


def _repeat_digest(payload):
    canonical = dict(payload)
    canonical['operation'] = payload.get('operation', services.OPERATIONS[payload['service']])
    if payload['service'] == 'instagram' and canonical['operation'] != 'reply_comment':
        canonical.setdefault('media_type', 'IMAGE')
    if 'file_sha256' in canonical:
        canonical.pop('file', None)  # The same video at another path is still the same content.
    canonical.pop('source_task', None)
    for key in ('text', 'subject'):
        if key in canonical:
            canonical[key] = unicodedata.normalize('NFC', canonical[key].strip())
    if payload['service'] == 'gmail':
        canonical['destination'] = canonical['destination'].casefold()
    elif payload['service'] in ('telegram', 'instagram'):
        canonical['destination'] = str(int(canonical['destination']))
    return _digest(canonical)


def _budget_schema(db, now):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='outbox_send_budget'").fetchone():
        return
    db.execute('''CREATE TABLE outbox_send_budget(
        id TEXT NOT NULL, day TEXT NOT NULL, channel TEXT NOT NULL,
        reserved REAL NOT NULL, fingerprint TEXT NOT NULL, PRIMARY KEY(id, day))''')
    db.execute('CREATE INDEX outbox_budget_day ON outbox_send_budget(day, channel)')
    db.execute('CREATE INDEX outbox_budget_repeat ON outbox_send_budget(fingerprint, reserved)')
    start = datetime.fromtimestamp(now, _ISTANBUL).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    # First installation also counts today's existing send journal. Do this only
    # once: a later preparation poll must not manufacture a new reservation.
    for row in db.execute("SELECT id,payload,updated FROM outbox WHERE state IN ('accepted','sending','unknown','preparing') AND updated>=?",
                          (min(start, now - DUPLICATE_WINDOW_SECONDS),)):
        payload = json.loads(row['payload'])
        db.execute('INSERT OR IGNORE INTO outbox_send_budget VALUES(?,?,?,?,?)',
                   (row['id'], _budget_day(row['updated']), payload['service'], row['updated'], _repeat_digest(payload)))


def _budget_block(db, record, now):
    day = _budget_day(now)
    if db.execute('SELECT 1 FROM outbox_send_budget WHERE id=? AND day=?', (record['id'], day)).fetchone():
        return None  # A known, already-budgeted publication may finish preparation.
    channel = record['payload']['service']
    counts = dict(db.execute('SELECT channel,COUNT(*) FROM outbox_send_budget WHERE day=? GROUP BY channel', (day,)))
    used, limit = counts.get(channel, 0), DAILY_CHANNEL_LIMITS.get(channel, 0)
    if used >= limit:
        return {'state': 'blocked', 'id': record['id'],
                'text': f'Bugün {_CHANNEL_NAMES[channel]} için {used} gönderim denemesi kaydedildi; günlük sınır ({limit}) doldu.'}
    total = sum(counts.values())
    if total >= DAILY_TOTAL_LIMIT:
        return {'state': 'blocked', 'id': record['id'],
                'text': f'Bugün toplam {total} gönderim denemesi kaydedildi; günlük toplam sınır ({DAILY_TOTAL_LIMIT}) doldu.'}
    duplicate = db.execute('SELECT 1 FROM outbox_send_budget WHERE fingerprint=? AND reserved>? AND id<>? LIMIT 1',
                           (_repeat_digest(record['payload']), now - DUPLICATE_WINDOW_SECONDS, record['id'])).fetchone()
    if duplicate:
        return {'state': 'blocked', 'id': record['id'],
                'text': 'Aynı hedefe aynı içerik kısa süre önce gönderilmeye çalışıldı; tekrar gönderim durduruldu.'}
    return None


def _digest(payload):
    return hashlib.sha256(service_store.encode(payload).encode()).hexdigest()


def grant(owner, service, destination, seconds=86400):
    if service not in (*services.OPERATIONS,'youtube_reply','instagram_reply') or not isinstance(destination,str) or '*' in destination or not destination:
        raise ValueError('İzin tek servis ve kesin hedefe ait olmalı.')
    # Reuse adapter destination validation without fabricating an outbound operation.
    import re
    patterns={'gmail':r'[^\s@,<>]+@[^\s@,<>]+\.[^\s@,<>]+','telegram':r'-?[0-9]{1,20}',
              'whatsapp':r'[1-9][0-9]{7,14}','instagram':r'[0-9]{1,30}','youtube':r'UC[A-Za-z0-9_-]{22}',
              'instagram_reply':r'[0-9]{1,30}','youtube_reply':r'UC[A-Za-z0-9_-]{22}'}
    if not re.fullmatch(patterns[service],destination) or type(seconds) is not int or not 60<=seconds<=30*86400:
        raise ValueError('İzin hedefi/süresi geçersiz.')
    with service_store.database(owner) as db:
        db.execute('INSERT OR REPLACE INTO grants VALUES(?,?,?)',(service,destination,time.time()+seconds))


def revoke(owner, service, destination):
    with service_store.database(owner) as db:db.execute('DELETE FROM grants WHERE service=? AND destination=?',(service,destination))


def prepare(owner, payload, work_key):
    payload=services.validate(payload)
    if 'source_task' in payload or 'text_from_task' in payload:raise ValueError('Gönderim kaydında kaynak görev gerçek çıktıya çözülmüş olmalı.')
    if not isinstance(work_key,str) or not 1<=len(work_key)<=200:raise ValueError('Gönderim iş kimliği gerekli.')
    encoded=service_store.encode(payload);digest=_digest(payload);now=time.time()
    with service_store.database(owner) as db:
        existing=db.execute('SELECT * FROM outbox WHERE work_key=?',(work_key,)).fetchone()
        if existing:
            if existing['digest']!=digest:raise ValueError('Aynı iş kimliği farklı içerikle kullanılamaz.')
            return existing['id']
        oid=uuid.uuid4().hex[:16]
        db.execute('INSERT INTO outbox(id,work_key,payload,digest,state,created,updated,receipt,error) VALUES(?,?,?,?,?,?,?,?,?)',(oid,work_key,encoded,digest,'prepared',now,now,'{}',''))
        return oid


def get(owner, oid):
    with service_store.database(owner) as db:
        row=db.execute('SELECT * FROM outbox WHERE id=?',(oid,)).fetchone()
        if row is None:raise ValueError('Bu kullanıcıya ait gönderim bulunamadı.')
        result=dict(row);result['payload']=json.loads(result['payload']);result['receipt']=json.loads(result['receipt'])
        if _digest(result['payload'])!=result['digest']:raise ValueError('Gönderim içeriği değişmiş.')
        return result


def history(owner):
    with service_store.database(owner) as db:
        return [dict(row) for row in db.execute('SELECT id,state,created,error FROM outbox ORDER BY created DESC LIMIT 50')]


def recover(owner,work_key):
    with service_store.database(owner) as db:
        row=db.execute('SELECT id FROM outbox WHERE work_key=?',(work_key,)).fetchone()
    return _result(get(owner,row['id'])) if row else None


def _result(record):
    if record['state']=='accepted':
        return {'state':'done','text':'Servis işlemi kabul etti; teslim/izlenme garantisi değildir.',
                'id':record['id'],'receipt':record['receipt'],'payload_sha256':record['digest']}
    if record['state'] in ('sending','unknown'):
        return {'state':'failed','id':record['id'],'text':'Dış işlem sonucu belirsiz; otomatik tekrar yapılmadı.'}
    if record['state']=='cancelled':return {'state':'blocked','id':record['id'],'text':'Gönderim iptal edildi.'}
    if record['state']=='preparing':return {'state':'approval','id':record['id'],'text':'Medya hazırlanıyor; yeni yayın oluşturulmadı. Aynı kayıt otomatik takip edilir; elle kontrol: işlem takip '+record['id']}
    return {'state':'approval','id':record['id'],'text':'İçerik ve hedef:\n'+service_store.encode(record['payload'])+'\nUygulamak için işlem onayla '+record['id'],
            'preview':record['payload']}


def _permission_decision(owner, payload, now, legacy_expiry, authorized_until):
    """Existing channel grants stay local to this immutable payload and channel."""
    try:
        from modules import permission_classify, permission_gate, permission_grants, permission_audit, permission_policy
        target = payload['destination']
        classification = permission_classify.classify('outbox', 'Gönder', target)
        grants = permission_grants.load(owner)
        grants = dict(grants)
        grants['message_out'] = dict(grants.get('message_out', {}))
        message_operation = (payload['service'] in ('gmail', 'telegram', 'whatsapp')
                             and payload.get('operation', services.OPERATIONS[payload['service']])
                             == services.OPERATIONS[payload['service']])
        if not message_operation:
            grants['message_out'] = {}  # Mesaj izni yayın veya yorum izni değildir.
        # Preserve old channel-scoped grants and approved preparation polling.
        # Never persist these as a new cross-channel standing permission.
        expiry = max(legacy_expiry or 0, authorized_until or 0,
                     grants['message_out'].get(target, 0))
        if expiry > now:
            grants['message_out'][target] = expiry
        result = permission_gate.decide(
            {'class': 'message_out', 'target': target, 'via': 'outbox'}, grants, now)
        decision, reason = result['decision'], result['reason']
        if classification != 'message_out':
            decision, reason = 'deny', 'Bu alıcıya gönderim izin politikasıyla engellendi.'
        decision, reason = permission_policy.apply(owner, 'outbox', 'message_out', decision, reason)
        if decision not in ('allow', 'ask', 'deny') or not isinstance(reason, str):
            raise ValueError('Geçersiz izin kararı.')
        permission_audit.record(owner, decision, 'message_out', target, 'outbox', reason)
        return decision, reason
    except Exception:
        _record_failure('modules/outbox.py:permission_gate')
        return 'deny', 'İzin denetimi tamamlanamadı; gönderim yapılmadı.'


def dispatch(owner, oid, *, approve=False):
    requests_state.check()
    record=get(owner,oid)
    if record['state'] not in ('prepared','preparing'):return _result(record)
    payload=record['payload']
    with service_store.database(owner) as db:
        now = time.time()
        _budget_schema(db, now)
        if blocked := _budget_block(db, record, now):
            return blocked
        # Atomic claim across processes; approval is for immutable stored content only.
        allowed=db.execute('SELECT expires FROM grants WHERE service=? AND destination=?',
                           (services.permission_key(payload),payload['destination'])).fetchone()
        decision, reason = _permission_decision(owner, payload, now,
                                                allowed['expires'] if allowed else 0, record['authorized_until'])
        if decision == 'deny':
            return {'state':'blocked', 'id':oid, 'text':reason}
        sensitive=any(privacy.redact(payload.get(key,''),force=True)!=payload.get(key,'') for key in ('text','subject'))
        if not approve and (decision == 'ask' or (sensitive and record['authorized_until']<=now)):
            if record['state']=='preparing':db.execute('UPDATE outbox SET updated=? WHERE id=?',(time.time(),oid))
            return _result(record)
        count=db.execute("UPDATE outbox SET state='sending',updated=?,authorized_until=? WHERE id=? AND state IN ('prepared','preparing') AND digest=?",
                         (time.time(),time.time()+86400 if approve else record['authorized_until'],oid,record['digest'])).rowcount
        if count!=1:return {'state':'failed','id':oid,'text':'Bu gönderim başka yürütücü tarafından alındı; tekrar uygulanmadı.'}
        # Reservation and send-once claim commit together under BEGIN IMMEDIATE.
        # Any interruption rolls both back before the external adapter is called.
        db.execute('INSERT OR IGNORE INTO outbox_send_budget VALUES(?,?,?,?,?)',
                   (oid, _budget_day(now), payload['service'], now, _repeat_digest(payload)))
    def progress(receipt):
        receipt={**record['receipt'],**receipt}
        with service_store.database(owner) as db:
            db.execute('UPDATE outbox SET receipt=?,updated=? WHERE id=? AND state=?',
                       (service_store.encode(receipt),time.time(),oid,'sending'))
    try:
        receipt=services.send(owner,payload,progress,checkpoint=record['receipt']) if payload['service']=='instagram' else services.send(owner,payload,progress)
        # No error body or credential-bearing URL is persisted.
        with service_store.database(owner) as db:
            db.execute("UPDATE outbox SET state='accepted',receipt=?,updated=? WHERE id=? AND state='sending'",
                       (service_store.encode(receipt),time.time(),oid))
    except services.Preparing:
        with service_store.database(owner) as db:
            db.execute("UPDATE outbox SET state='preparing',error='',updated=? WHERE id=? AND state='sending'",(time.time(),oid))
    except BaseException as exc:
        with service_store.database(owner) as db:
            db.execute("UPDATE outbox SET state='unknown',error=?,updated=? WHERE id=? AND state='sending'",
                       (type(exc).__name__,time.time(),oid))
        if isinstance(exc,(requests_state.Cancelled,KeyboardInterrupt,SystemExit)):raise
    return _result(get(owner,oid))


def cancel(owner, oid):
    with service_store.database(owner) as db:
        db.execute("UPDATE outbox SET state='cancelled',updated=? WHERE id=? AND state IN ('prepared','preparing')",(time.time(),oid))
    return _result(get(owner,oid))


def has_pending(owner,min_age=30):
    with service_store.database(owner) as db:
        return db.execute("SELECT 1 FROM outbox WHERE state='preparing' AND updated<=? LIMIT 1",(time.time()-min_age,)).fetchone() is not None


def poll(owner,min_age=30):
    """Only known not-yet-published containers, never unknown sends."""
    with service_store.database(owner) as db:
        rows=list(db.execute("SELECT id FROM outbox WHERE state='preparing' AND updated<=? ORDER BY updated LIMIT 1",(time.time()-min_age,)))
    return [dispatch(owner,row['id']) for row in rows]
