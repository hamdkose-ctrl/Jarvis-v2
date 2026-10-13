"""Deduplicated incoming events and delivery receipts; no automatic replies."""
import hashlib
import hmac
import json
import re
import time
from modules import service_store as store, publish_services as services, account_tools, privacy

MAX_BODY=262144


def config(owner):
    if privacy.blocked('web'):raise PermissionError('Gizlilik modu webhook alımını kapatıyor.')
    data=services.configuration(owner,'whatsapp')
    if data.get('webhook_enabled') is not True:raise PermissionError('Webhook bu kullanıcıda kapalı.')
    for key in ('app_secret','verify_token'):
        if not isinstance(data.get(key),str) or len(data[key])<16:raise PermissionError('Webhook doğrulama yapılandırması gerekli.')
    if not isinstance(data.get('phone_number_id'),str) or not data['phone_number_id'].isdigit():raise PermissionError('WhatsApp telefon kimliği gerekli.')
    return data


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS incoming(service TEXT,event_id TEXT,kind TEXT,source TEXT,text TEXT,remote_time TEXT,received REAL,payload TEXT,PRIMARY KEY(service,event_id))')
    db.execute('CREATE TABLE IF NOT EXISTS delivery(service TEXT,remote_id TEXT,status TEXT,remote_time INTEGER,received REAL,PRIMARY KEY(service,remote_id))')
    db.execute('CREATE INDEX IF NOT EXISTS incoming_recent ON incoming(service,received DESC)')


def ingest(owner, raw, signature):
    store.identity(owner);settings=config(owner)
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BODY:raise ValueError('Webhook gövde sınırı geçersiz.')
    if not isinstance(signature,str) or not re.fullmatch(r'sha256=[a-f0-9]{64}',signature):raise PermissionError('Webhook imzası gerekli.')
    expected='sha256='+hmac.new(settings['app_secret'].encode(),raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature):raise PermissionError('Webhook imzası eşleşmiyor.')
    data=json.loads(raw)
    if not isinstance(data,dict) or data.get('object')!='whatsapp_business_account':raise ValueError('Webhook nesnesi geçersiz.')
    events=[]
    for entry in data.get('entry',[]):
        for change in entry.get('changes',[]):
            value=change.get('value',{})
            if change.get('field')!='messages' or str(value.get('metadata',{}).get('phone_number_id'))!=settings['phone_number_id']:continue
            for item in value.get('messages',[]):
                mid=item.get('id');sender=item.get('from');stamp=item.get('timestamp')
                if not isinstance(mid,str) or not 1<=len(mid)<=300 or not isinstance(sender,str) or not re.fullmatch('[0-9]{7,15}',sender):raise ValueError('Gelen mesaj kimliği/kaynağı geçersiz.')
                text=item.get('text',{}).get('body','') if item.get('type')=='text' else '[Metin olmayan mesaj; medya indirilmedi.]'
                if not isinstance(text,str) or len(text)>20000:raise ValueError('Gelen mesaj metni geçersiz.')
                events.append((mid,'message',sender,text,str(stamp or ''),{}))
            for item in value.get('statuses',[]):
                mid=item.get('id');status=item.get('status');stamp=item.get('timestamp')
                if not isinstance(mid,str) or not 1<=len(mid)<=300 or status not in ('sent','delivered','read','failed') or not isinstance(stamp,str) or not re.fullmatch(r'[0-9]{1,16}',stamp):raise ValueError('Teslim kaydı geçersiz.')
                events.append((mid+':'+status+':'+stamp,'delivery','',status,stamp,{'remote_id':mid,'status':status}))
    if len(events)>500:raise ValueError('Webhook olay sayısı sınırı aşıldı.')
    inserted=0;messages=0;deliveries=0
    with store.database(owner) as db:
        _schema(db)
        for eid,kind,sender,text,stamp,payload in events:
            count=db.execute('INSERT OR IGNORE INTO incoming VALUES(?,?,?,?,?,?,?,?)',
                             ('whatsapp',eid,kind,sender,text,stamp,time.time(),store.encode(payload))).rowcount
            inserted+=count
            if kind=='message':messages+=count
            else:deliveries+=count
            if kind=='delivery':
                previous=db.execute('SELECT status,remote_time FROM delivery WHERE service=? AND remote_id=?',('whatsapp',payload['remote_id'])).fetchone()
                rank={'sent':1,'delivered':2,'read':3,'failed':0}
                if previous is None or int(stamp)>=previous['remote_time'] and (rank[payload['status']]>=rank[previous['status']] or payload['status']=='failed' and previous['status'] not in ('delivered','read')):
                    db.execute('INSERT OR REPLACE INTO delivery VALUES(?,?,?,?,?)',('whatsapp',payload['remote_id'],payload['status'],int(stamp),time.time()))
    return {'stored':inserted,'messages':messages,'deliveries':deliveries}


def read(owner,limit=5):
    with store.database(owner) as db:
        _schema(db)
        rows=[dict(r) for r in db.execute('SELECT event_id,kind,source,text,remote_time,received FROM incoming WHERE service=? ORDER BY received DESC,event_id LIMIT ?',('whatsapp',limit))]
    snapshot={'owner':owner,'service':'whatsapp','operation':'list_inbox','fetched_at':time.time(),
              'items':[{'id':r['event_id'],'text':r['text'],'kind':r['kind'],'source':r['source'],'remote_time':r['remote_time']} for r in rows],
              'scope':'bounded_account_read'}
    from modules import social_reads
    return {'state':'done','text':social_reads.render(snapshot),'snapshot':snapshot,'sha256':account_tools.digest(snapshot)}


def delivery(owner,remote_id):
    with store.database(owner) as db:
        _schema(db)
        row=db.execute('SELECT status,remote_time,received FROM delivery WHERE service=? AND remote_id=?',('whatsapp',remote_id)).fetchone()
    return dict(row) if row else None
