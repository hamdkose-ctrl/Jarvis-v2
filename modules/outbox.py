"""Durable exact-content approvals, standing destination grants and send-once journal."""
import hashlib
import json
import time
import uuid
from modules import publish_services as services, service_store, requests_state, privacy


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


def dispatch(owner, oid, *, approve=False):
    requests_state.check()
    record=get(owner,oid)
    if record['state'] not in ('prepared','preparing'):return _result(record)
    payload=record['payload']
    with service_store.database(owner) as db:
        # Atomic claim across processes; approval is for immutable stored content only.
        allowed=db.execute('SELECT expires FROM grants WHERE service=? AND destination=?',
                           (services.permission_key(payload),payload['destination'])).fetchone()
        sensitive=any(privacy.redact(payload.get(key,''),force=True)!=payload.get(key,'') for key in ('text','subject'))
        if not approve and record['authorized_until']<=time.time() and (sensitive or not allowed or allowed['expires']<=time.time()):
            if record['state']=='preparing':db.execute('UPDATE outbox SET updated=? WHERE id=?',(time.time(),oid))
            return _result(record)
        count=db.execute("UPDATE outbox SET state='sending',updated=?,authorized_until=? WHERE id=? AND state IN ('prepared','preparing') AND digest=?",
                         (time.time(),time.time()+86400 if approve else record['authorized_until'],oid,record['digest'])).rowcount
        if count!=1:return {'state':'failed','id':oid,'text':'Bu gönderim başka yürütücü tarafından alındı; tekrar uygulanmadı.'}
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
