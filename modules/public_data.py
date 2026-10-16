"""Small, keyless public-data adapters. Search hits are discovery, never evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import threading
from urllib.parse import urlencode, urlsplit
from modules import public_sources, service_store, requests_state

CATALOG = (
    {'id': 'gdelt', 'name': 'GDELT DOC', 'operation': 'news_search',
     'documentation': 'https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/',
     'authentication': 'none', 'billing': 'free_public_endpoint',
     'scope': 'Haber bağlantısı keşfi; tüm kurumlar indekslenmez. seen_at yayın tarihi değildir. En fazla 90 gün, 20 sonuç, tek istek; otomatik yeniden deneme yok.'},
    {'id': 'frankfurter', 'name': 'Frankfurter', 'operation': 'exchange',
     'documentation': 'https://frankfurter.dev/', 'authentication': 'none',
     'billing': 'free_public_endpoint',
     'scope': 'Mevcut günlük kur adaptörü; anlık banka alış/satışı veya yatırım tavsiyesi değildir.'},
    {'id': 'publisher', 'name': 'Yayıncının kendi HTML/RSS/Atom dizini', 'operation': 'headlines',
     'documentation': '', 'authentication': 'none', 'billing': 'public_pages',
     'scope': 'Kullanıcı URL verir veya planlayıcı gerçek dizini seçer. Başlıklar ayrıca research ile okunmalıdır.'},
)
_SEARCH_LOCK=threading.Lock()
_SEARCH_NEXT=0.0


def catalog(owner):
    service_store.identity(owner)
    return {'sources': copy.deepcopy(CATALOG), 'checked_on': '2026-10-16',
            'live_connection_tested': False,
            'limits': ['Katalog listesi çalışan bağlantı veya kesintisiz erişim garantisi değildir.',
                       'Anahtar, hesap, kart, abonelik ve yeni model kurulmaz.',
                       'Sosyal medya mevcut yetkili hesapları; mağaza/finans analizi mevcut CSV araçlarını kullanır.']}


def _domains(domains):
    if domains is None:return []
    if not isinstance(domains,list) or not 1<=len(domains)<=5:raise ValueError('1–5 kaynak alan adı gerekli.')
    result=[]
    for value in domains:
        if not isinstance(value,str) or len(value)>253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',value):
            raise ValueError('Kaynak alan adı URL veya sorgu içeremez.')
        domain=value.lower()
        if '.' not in domain or any(not label or len(label)>63 or label.startswith('-') or label.endswith('-') for label in domain.split('.')):
            raise ValueError('Kaynak alan adı geçersiz.')
        public_sources.address('https://'+domain+'/')
        if domain not in result:result.append(domain)
    return result


def search_input(query,days=30,domains=None,limit=10):
    if not isinstance(query,str) or not 2<=len(query.strip())<=200 or not re.fullmatch(r'[\w\s-]+',query) or any(ord(c)<32 for c in query):
        raise ValueError('Haber sorgusu 2–200 karakterlik düz konu metni olmalı; URL, anahtar veya arama operatörü içeremez.')
    if any(word.upper() in {'OR','AND','NOT'} for word in query.split()):raise ValueError('Haber sorgusunda arama operatörü kullanılamaz.')
    if type(days) is not int or not 1<=days<=90:raise ValueError('Haber aralığı 1–90 gün olmalı.')
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('Haber sonuç sınırı 1–20 olmalı.')
    return ' '.join(query.split()),_domains(domains)


def news_search(owner,query,days=30,domains=None,limit=10,*,fetcher=None):
    service_store.identity(owner);requests_state.check()
    query,domains=search_input(query,days,domains,limit)
    # Quote words so the external service cannot treat a topic as query syntax.
    expression=' '.join('"'+word+'"' for word in query.split())
    if domains:expression+=' ('+' OR '.join('domain:'+d for d in domains)+')'
    url='https://api.gdeltproject.org/api/v2/doc/doc?'+urlencode({
        'query':expression,'mode':'artlist','format':'json','sort':'datedesc',
        'timespan':str(days)+'d','maxrecords':limit})
    # One process-wide lane: this public endpoint asks for >=5 seconds between calls.
    # Fail promptly instead of sleeping in the task queue or retrying a 429 loop.
    global _SEARCH_NEXT
    with _SEARCH_LOCK:
        if time.monotonic()<_SEARCH_NEXT:raise ValueError('Haber arama servisi beklemede; en az 5 saniye sonra dene veya yayıncının headlines dizinini kullan.')
        _SEARCH_NEXT=time.monotonic()+5
    try:response=(fetcher or public_sources.fetch)(url)
    except ValueError as exc:
        if '429' in str(exc):
            with _SEARCH_LOCK:_SEARCH_NEXT=max(_SEARCH_NEXT,time.monotonic()+60)
        raise
    try:data=json.loads(response['body'])
    except (ValueError,UnicodeDecodeError):raise ValueError('Haber arama servisi JSON döndürmedi; sonuç uydurulmadı.') from None
    if not isinstance(data,dict) or not isinstance(data.get('articles'),list):
        raise ValueError('Haber arama yanıtında articles listesi yok; servis hatası boş sonuç sayılmadı.')
    items=[];seen=set();skipped=0
    for row in data['articles'][:250]:
        requests_state.check()
        if not isinstance(row,dict) or not isinstance(row.get('title'),str) or not row['title'].strip():
            skipped+=1;continue
        try:article=public_sources.address(row.get('url'))
        except (ValueError,TypeError):skipped+=1;continue
        host=urlsplit(article).hostname
        if domains and not any(host==d or host.endswith('.'+d) for d in domains):skipped+=1;continue
        if article in seen:continue
        seen.add(article)
        items.append({'title':row['title'].strip()[:500],'url':article,'domain':host,
                      'seen_at':row.get('seendate','')[:40] if isinstance(row.get('seendate'),str) else '',
                      'published':'','publication_verified':False})
        if len(items)>=limit:break
    return {'items':items,'source':response['url'],'fetched_at':time.time(),
            'sha256':hashlib.sha256(response['body']).hexdigest(),'days':days,'domains':domains,
            'skipped':skipped,'coverage_complete':False,
            'scope':'Yalnız haber bağlantısı keşfi. İndeksin görülme tarihi yayın tarihi değildir; her bağlantıyı research ile doğrula. Boş sonuç konu hakkında haber olmadığı anlamına gelmez.'}
