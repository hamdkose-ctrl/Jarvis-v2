"""Discover references, inspect evidence, and explicitly bind bounded public GET APIs.

Catalog entries and MCP documentation never install code or grant account access.
"""
from __future__ import annotations
import hashlib
import math
import json
import re
import time
from urllib.parse import urlencode,urlsplit
from modules import public_sources,service_store
from modules.diagnostics import record_failure as _record_failure

INDEXES=(
    'https://raw.githubusercontent.com/public-apis/public-apis/master/README.md',
    'https://raw.githubusercontent.com/3rt4nm4n/turkish-apis/main/README.md',
)


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS capability_refs(id TEXT PRIMARY KEY,name TEXT,url TEXT,category TEXT,description TEXT,index_url TEXT,assessed REAL DEFAULT 0,assessment TEXT DEFAULT \'{}\',binding TEXT DEFAULT \'\')')
    db.execute('CREATE TABLE IF NOT EXISTS capability_indexes(url TEXT PRIMARY KEY,body TEXT,fetched REAL)')


def _fold(text):return text.replace('I','ı').replace('İ','i').lower()


def _references(body,index):
    section='';result=[]
    for line in body.splitlines():
        if line.startswith('#'):section=line.lstrip('# ').strip()[:100]
        if not line.startswith('|'):continue
        match=re.search(r'\[([^\]]+)\]\((https://[^)\s]+)\)',line)
        if not match:continue
        try:url=public_sources.address(match.group(2))
        except ValueError:continue
        fields=line.split('|')
        result.append({'name':match.group(1)[:120],'url':url,'category':section,
                       'description':fields[2].strip()[:700] if len(fields)>2 else '',
                       'kind':'mcp_reference' if 'MCP' in section else 'api_reference','index_url':index})
    return result


def discover(owner,query,*,fetcher=None):
    service_store.identity(owner)
    if not isinstance(query,str) or not 2<=len(query.strip())<=200:raise ValueError('Aranacak yetenek 2–200 karakter olmalı.')
    fetcher=fetcher or public_sources.fetch;words=[_fold(w) for w in query.split() if len(w)>1];found=[];warnings=[]
    for index in INDEXES:
        with service_store.database(owner) as db:
            _schema(db);cached=db.execute('SELECT * FROM capability_indexes WHERE url=?',(index,)).fetchone()
        try:
            if cached and time.time()-cached['fetched']<3600:body=cached['body']
            else:
                response=fetcher(index);body=response['body'].decode('utf-8',errors='replace')
                with service_store.database(owner) as db:
                    db.execute('INSERT OR REPLACE INTO capability_indexes VALUES(?,?,?)',(index,body,time.time()))
            for ref in _references(body,index):
                ref['score']=sum(w in _fold(ref['name']+' '+ref['description']+' '+ref['category']) for w in words)
                if ref['score']:found.append(ref)
        except Exception as exc:
            _record_failure('modules/capability_hub.py:discover')
            from modules import requests_state
            if isinstance(exc,requests_state.Cancelled):raise
            warnings.append('Bir kaynak kataloğu okunamadı: '+type(exc).__name__)
    found=sorted(found,key=lambda r:-r['score']);result=[];seen=set()
    with service_store.database(owner) as db:
        _schema(db)
        for ref in found:
            if ref['url'] in seen:continue
            seen.add(ref['url']);ident=hashlib.sha256(ref['url'].encode()).hexdigest()[:16]
            if not db.execute('SELECT id FROM capability_refs WHERE id=?',(ident,)).fetchone():
                if db.execute('SELECT count(*) FROM capability_refs').fetchone()[0]>=200:break
                db.execute('INSERT INTO capability_refs(id,name,url,category,description,index_url) VALUES(?,?,?,?,?,?)',
                    (ident,ref['name'],ref['url'],ref['category'],ref['description'],ref['index_url']))
            result.append({**ref,'id':ident,'state':'discovered','pricing_verified':False,'authentication_verified':False,
                           'permission':'Kaynak referansı; çalıştırma/kurulum izni sağlamaz.'})
            if len(result)>=15:break
    return {'candidates':result,'warnings':warnings}


def rows(owner):
    with service_store.database(owner) as db:
        _schema(db)
        result=[]
        for row in db.execute('SELECT * FROM capability_refs ORDER BY name LIMIT 200'):
            item=dict(row);item['assessment']=json.loads(item['assessment'])
            item['binding']=json.loads(item['binding']) if item['binding'] else None
            result.append(item)
        return result


def _record(owner,ident):
    if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{16}',ident):raise ValueError('Yetenek kimliği geçersiz.')
    with service_store.database(owner) as db:
        _schema(db);row=db.execute('SELECT * FROM capability_refs WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Bu kullanıcıya ait servis adayı yok.')
        return dict(row)


def assess(owner,ident,*,fetcher=None):
    row=_record(owner,ident);response=(fetcher or public_sources.fetch)(row['url'])
    excerpt=public_sources.text(response['body'])
    result={'document_reachable':True,'document_url':response['url'],'document_sha256':hashlib.sha256(response['body']).hexdigest(),
            'excerpt':excerpt[:3500],'pricing_verified':False,'authentication_verified':False,
            'operation_tested':False,'code_installed':False,'state':'documentation_read',
            'next':'Ücret/kota, kimlik doğrulama ve kesin işlem resmî belgede ayrıca doğrulanmalı. MCP referansı kendi başına çalışan adaptör değildir.'}
    with service_store.database(owner) as db:
        db.execute('UPDATE capability_refs SET assessment=?,assessed=? WHERE id=?',(service_store.encode(result),time.time(),ident))
    return result


def public_binding(owner,ident,endpoint,parameters,*,confirmed=False):
    row=_record(owner,ident);endpoint=public_sources.address(endpoint)
    if urlsplit(endpoint).query:raise ValueError('Bağlantı adresi parametresiz olmalı; parametre şeması ayrı tanımlanır.')
    if not isinstance(parameters,dict) or len(parameters)>12:raise ValueError('En fazla 12 parametre tanımlanabilir.')
    for name,kind in parameters.items():
        if (not isinstance(name,str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,40}',name) or
            re.search(r'key|token|secret|password|credential|auth|command|action|delete|send|update',name,re.I) or
            kind not in ('string','integer','number','boolean')):raise ValueError('Yalnız açık, kimlik bilgisi içermeyen okuma parametreleri kullanılabilir.')
    if re.search(r'/(?:delete|remove|send|create|update|execute|run)(?:/|$)',urlsplit(endpoint).path,re.I):
        raise ValueError('Yazma/çalıştırma adresi genel okuma adaptörüne bağlanamaz.')
    binding={'endpoint':endpoint,'method':'GET','parameters':parameters,'authentication':'none','code_installed':False}
    preview='Genel internet API okuması bağlanacak: '+row['name']+'\nGET '+endpoint+'\nParametreler: '+service_store.encode(parameters)+'\nKimlik doğrulaması yok. Ücret/kota doğrulanmadı; hesap anahtarı veya MCP kodu kurulmayacak.'
    if not confirmed:return {'state':'approval','text':preview,'id':ident}
    with service_store.database(owner) as db:
        db.execute('UPDATE capability_refs SET binding=? WHERE id=?',(service_store.encode(binding),ident))
    return {'state':'done','text':'Sabit adresli genel GET adaptörü kaydedildi. Servisin çalışırlığı henüz sınanmadı.','binding':binding}


def read(owner,ident,parameters,*,fetcher=None):
    row=_record(owner,ident)
    if not row['binding']:raise ValueError('Bu referansa onaylı genel okuma adaptörü bağlanmamış.')
    binding=json.loads(row['binding']);schema=binding['parameters']
    if not isinstance(parameters,dict) or set(parameters)-set(schema):raise ValueError('Bağlantıda olmayan parametre gönderilemez.')
    for key,value in parameters.items():
        kind=schema[key]
        valid=(kind=='string' and isinstance(value,str) and len(value)<=500) or (kind=='integer' and type(value) is int) or (kind=='number' and type(value) in (int,float)) or (kind=='boolean' and type(value) is bool)
        if not valid or type(value) is float and not math.isfinite(value):raise ValueError('API parametre türü geçersiz.')
    url=binding['endpoint']+('?' + urlencode(parameters) if parameters else '')
    response=(fetcher or public_sources.fetch)(url)
    try:value=json.loads(response['body'])
    except ValueError:raise ValueError('Genel veri adaptörü JSON yanıtı gerektirir.') from None
    encoded=service_store.encode(value)
    return {'data':value if len(encoded)<=20000 else None,'excerpt':encoded[:20000],
            'truncated':len(encoded)>20000,'source':response['url'],'fetched_at':time.time(),
            'sha256':hashlib.sha256(response['body']).hexdigest(),'interpretation':'source_data_only'}


def unbind(owner,ident):
    _record(owner,ident)
    with service_store.database(owner) as db:db.execute('UPDATE capability_refs SET binding=\'\' WHERE id=?',(ident,))
