"""Small, keyless public-data adapters. Search hits are discovery, never evidence."""
from __future__ import annotations

import copy
import re
from modules import public_sources, service_store, requests_state

CATALOG = (
    {'id': 'frankfurter', 'name': 'Frankfurter', 'operation': 'exchange',
     'documentation': 'https://frankfurter.dev/', 'authentication': 'none',
     'billing': 'free_public_endpoint',
     'scope': 'Mevcut günlük kur adaptörü; anlık banka alış/satışı veya yatırım tavsiyesi değildir.'},
    {'id': 'publisher', 'name': 'Yayıncının kendi HTML/RSS/Atom dizini', 'operation': 'headlines',
     'documentation': '', 'authentication': 'none', 'billing': 'public_pages',
     'scope': 'Kullanıcı URL verir veya planlayıcı gerçek dizini seçer. Başlıklar ayrıca research ile okunmalıdır.'},
)


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


def search_input(query,days=7,domains=None,limit=10):
    if not isinstance(query,str) or not 2<=len(query.strip())<=200 or not re.fullmatch(r'[\w\s-]+',query) or any(ord(c)<32 for c in query):
        raise ValueError('Haber sorgusu 2–200 karakterlik düz konu metni olmalı; URL, anahtar veya arama operatörü içeremez.')
    if any(word.upper() in {'OR','AND','NOT'} for word in query.split()):raise ValueError('Haber sorgusunda arama operatörü kullanılamaz.')
    if type(days) is not int or not 1<=days<=90:raise ValueError('Haber aralığı 1–90 gün olmalı.')
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('Haber sonuç sınırı 1–20 olmalı.')
    return ' '.join(query.split()),_domains(domains)


def news_search(owner,query,days=7,domains=None,limit=10,*,fetcher=None):
    service_store.identity(owner);requests_state.check()
    query,domains=search_input(query,days,domains,limit)
    raise ValueError('Haber arama servisi kaldırıldı; data.headlines ile yayıncının kendi HTML/RSS dizinini kullan.')
