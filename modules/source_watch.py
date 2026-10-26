"""Explicit per-user public-source watches; durable deduplication, no model polling."""
from __future__ import annotations
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlsplit
import uuid
from modules import public_sources,service_store,privacy,requests_state
from modules.diagnostics import record_failure as _record_failure

_LOCK=threading.Lock()
MAX_RULES=20
KNOWN_SOURCES={
    'istanbul_egitim':{'url':'https://istanbul.meb.gov.tr/','label':'İstanbul İl Millî Eğitim Müdürlüğü',
                       'aliases':(('istanbul','okul'),('istanbul','eğitim'),('istanbul','meb'))},
}


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS source_watches(id TEXT PRIMARY KEY,url TEXT,label TEXT,terms TEXT,interval INTEGER,due REAL,baseline INTEGER DEFAULT 0,paused INTEGER DEFAULT 0,error TEXT DEFAULT \'\',created REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS source_seen(rule TEXT,item TEXT,PRIMARY KEY(rule,item))')
    db.execute('CREATE TABLE IF NOT EXISTS source_events(id TEXT PRIMARY KEY,rule TEXT,item TEXT,payload TEXT,created REAL,notified INTEGER DEFAULT 0,UNIQUE(rule,item))')
    db.execute('CREATE TABLE IF NOT EXISTS source_versions(rule TEXT,url TEXT,fingerprint TEXT,checked REAL,PRIMARY KEY(rule,url))')


def _terms(terms):
    if not isinstance(terms,list) or not 1<=len(terms)<=12 or any(not isinstance(t,str) or not t.strip() or len(t)>80 for t in terms):
        raise ValueError('Takip için 1–12 konu sözcüğü gerekli.')
    return list(dict.fromkeys(t.strip() for t in terms))


def add(owner,url,terms,interval=600,label=''):
    service_store.identity(owner);url=public_sources.address(url);terms=_terms(terms)
    if type(interval) is not int or not 300<=interval<=86400:raise ValueError('Kontrol aralığı 300–86400 saniye olmalı.')
    if not isinstance(label,str) or len(label)>100:raise ValueError('Takip etiketi geçersiz.')
    ident=uuid.uuid4().hex[:12]
    with service_store.database(owner) as db:
        _schema(db)
        if db.execute('SELECT count(*) FROM source_watches').fetchone()[0]>=MAX_RULES:raise ValueError('En fazla 20 kaynak takip edilebilir.')
        if db.execute('SELECT id FROM source_watches WHERE url=? AND terms=?',(url,service_store.encode(terms))).fetchone():
            raise ValueError('Bu kaynak ve konu zaten takip ediliyor.')
        db.execute('INSERT INTO source_watches(id,url,label,terms,interval,due,created) VALUES(?,?,?,?,?,?,?)',
                   (ident,url,label or urlsplit(url).hostname,service_store.encode(terms),interval,time.time(),time.time()))
    return ident


def rows(owner):
    with service_store.database(owner) as db:
        _schema(db)
        return [{**dict(row),'terms':json.loads(row['terms'])} for row in db.execute('SELECT * FROM source_watches ORDER BY created DESC')]


def pause(owner,ident,on=True):
    if type(on) is not bool:raise ValueError('Duraklatma boolean olmalı.')
    with service_store.database(owner) as db:
        _schema(db)
        if not db.execute('UPDATE source_watches SET paused=? WHERE id=?',(int(on),ident)).rowcount:
            raise ValueError('Bu kullanıcıya ait kaynak takibi yok.')


def remove(owner,ident):
    with service_store.database(owner) as db:
        _schema(db)
        if not db.execute('DELETE FROM source_watches WHERE id=?',(ident,)).rowcount:raise ValueError('Bu kullanıcıya ait kaynak takibi yok.')
        db.execute('DELETE FROM source_seen WHERE rule=?',(ident,));db.execute('DELETE FROM source_events WHERE rule=?',(ident,))
        db.execute('DELETE FROM source_versions WHERE rule=?',(ident,))


def events(owner,limit=20):
    if type(limit) is not int or not 1<=limit<=50:raise ValueError('Bildirim sınırı 1–50 olmalı.')
    with service_store.database(owner) as db:
        _schema(db)
        return [{**json.loads(row['payload']),'id':row['id'],'notified':bool(row['notified'])} for row in
                db.execute('SELECT * FROM source_events ORDER BY created DESC LIMIT ?',(limit,))]


def _fold(value):return value.replace('I','ı').replace('İ','i').lower()


def _excerpt(body,terms):
    # Preserve actual wording, including negations/exceptions. Never turn a keyword
    # match into a claim that all schools, districts or dates share a decision.
    text=public_sources.text(body)
    sentences=re.split(r'(?<=[.!?])\s+',text)
    matched=[i for i,s in enumerate(sentences) if any(_fold(t) in _fold(s) for t in terms)]
    if not matched:return None
    start=max(0,matched[0]-1)
    quote=' '.join(sentences[start:min(len(sentences),matched[0]+3)])
    return quote[:2200]+(' [Alıntı kesildi; kaynağın tamamını kontrol et.]' if len(quote)>2200 else '')


def render(event):
    return ('İzlediğin kaynakta yeni içerik: '+event['title']+'\n'+
            ('Yayın tarihi: '+event['published']+'\n' if event.get('published') else 'Yayın tarihi kaynakta doğrulanamadı.\n')+
            'Kaynak alıntısı: '+event['quote']+'\nKaynak: '+event['url']+
            '\nBu bir kaynak güncellemesidir; kararın geçerli günü/kapsamı alıntıdan bağımsız varsayılmadı.')


def poll(owner,notify=None,*,now=None,fetcher=None,rule_id=None,force=False):
    """One due source, at most two new article reads. First pass establishes baseline."""
    service_store.identity(owner)
    if privacy.blocked('web') or not _LOCK.acquire(blocking=False):return None
    fetcher=fetcher or public_sources.fetch;now=time.time() if now is None else now
    produced=[]
    subscription_payloads=[]
    try:
        with service_store.database(owner) as db:
            _schema(db)
            row=db.execute('SELECT * FROM source_watches WHERE paused=0 AND (? OR due<=?) AND (? IS NULL OR id=?) ORDER BY due LIMIT 1',
                           (int(force),now,rule_id,rule_id)).fetchone()
            if row:
                row=dict(row);db.execute('UPDATE source_watches SET due=? WHERE id=?',(now+row['interval'],row['id']))
        if row:
            try:
                response=fetcher(row['url']);items=public_sources.entries(response)
                if not items:raise ValueError('Kaynakta duyuru/haber girdisi bulunamadı; başarı sayılmadı.')
                with service_store.database(owner) as db:
                    _schema(db)
                    active=db.execute('SELECT baseline FROM source_watches WHERE id=? AND paused=0',(row['id'],)).fetchone()
                    if not active:return None
                    seen={r[0] for r in db.execute('SELECT item FROM source_seen WHERE rule=?',(row['id'],))}
                    if len(seen)>=5000:raise ValueError('Kaynağın izleme kayıt sınırı doldu; takip yeniden düzenlenmeli.')
                    baseline=not active['baseline']
                    versions={r['url']:dict(r) for r in db.execute('SELECT * FROM source_versions WHERE rule=?',(row['id'],))}
                    if baseline:
                        for item in items:db.execute('INSERT OR IGNORE INTO source_seen VALUES(?,?)',(row['id'],item['url']))
                        db.execute('UPDATE source_watches SET baseline=1,error=\'\' WHERE id=?',(row['id'],))
                terms=json.loads(row['terms'])
                new=[i for i in items if i['url'] not in seen] if not baseline else []
                refresh=sorted(items[:10],key=lambda item:versions.get(item['url'],{}).get('checked',0))
                selected=(new if new else refresh)[:2]
                for item in selected:
                    requests_state.check()
                    article=fetcher(item['url'])
                    if urlsplit(article['url']).hostname!=urlsplit(item['url']).hostname:
                        raise ValueError('Duyuru başka kaynak alanına yönlendi; eşleştirme yapılmadı.')
                    quote=_excerpt(article['body'],terms)
                    fingerprint=hashlib.sha256(service_store.encode([item['title'],item['published'],quote]).encode()).hexdigest()
                    old=versions.get(item['url'])
                    changed=not baseline and (item['url'] not in seen or old is not None and old['fingerprint']!=fingerprint)
                    payload={'title':item['title'],'url':article['url'],'published':item['published'],
                             'quote':quote or '', 'source_url':row['url'],'fetched_at':now,
                             'content_sha256':hashlib.sha256(article['body']).hexdigest(),
                             'official_domain':urlsplit(article['url']).hostname.endswith('.gov.tr'),
                             'interpretation':'source_quote_only'}
                    with service_store.database(owner) as db:
                        _schema(db)
                        if not db.execute('SELECT id FROM source_watches WHERE id=? AND paused=0',(row['id'],)).fetchone():break
                        db.execute('INSERT OR IGNORE INTO source_seen VALUES(?,?)',(row['id'],item['url']))
                        db.execute('INSERT OR REPLACE INTO source_versions VALUES(?,?,?,?)',(row['id'],item['url'],fingerprint,now))
                        if quote and changed:
                            if db.execute('SELECT count(*) FROM source_events WHERE rule=?',(row['id'],)).fetchone()[0]>=2000:
                                db.execute('DELETE FROM source_events WHERE id IN (SELECT id FROM source_events WHERE rule=? AND notified=1 ORDER BY created LIMIT 50)',(row['id'],))
                                if db.execute('SELECT count(*) FROM source_events WHERE rule=?',(row['id'],)).fetchone()[0]>=2000:
                                    raise ValueError('Teslim edilmemiş kaynak bildirimleri sınırı doldu.')
                            eid=uuid.uuid4().hex[:16]
                            count=db.execute('INSERT OR IGNORE INTO source_events(id,rule,item,payload,created) VALUES(?,?,?,?,?)',
                                (eid,row['id'],item['url']+'#'+fingerprint,service_store.encode(payload),now)).rowcount
                            if count:
                                produced.append({**payload,'id':eid})
                                subscription_payloads.append(payload)
                        db.execute('UPDATE source_watches SET error=\'\' WHERE id=?',(row['id'],))
            except requests_state.Cancelled:raise
            except Exception as exc:
                _record_failure('modules/source_watch.py:poll')
                with service_store.database(owner) as db:
                    _schema(db);db.execute('UPDATE source_watches SET error=? WHERE id=?',(type(exc).__name__,row['id']))
        if subscription_payloads:
            from modules import runtime_subscription
            for event in subscription_payloads:
                runtime_subscription.publish(owner, row['id'], event, occurred_at=event.get('fetched_at'))
        if notify:
            with service_store.database(owner) as db:
                _schema(db)
                pending=[dict(r) for r in db.execute('SELECT e.* FROM source_events e JOIN source_watches w ON e.rule=w.id WHERE e.notified=0 AND w.paused=0 ORDER BY e.created LIMIT 5')]
            for event in pending:
                notify(owner,event['id'],privacy.redact(render(json.loads(event['payload'])),force=True))
                with service_store.database(owner) as db:
                    db.execute('UPDATE source_events SET notified=1 WHERE id=?',(event['id'],))
        return produced
    finally:_LOCK.release()
