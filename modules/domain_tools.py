"""Read-only financial/store analysis, dated public rates, news and owned social data."""
from __future__ import annotations
import csv
from datetime import date
from decimal import Decimal,InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from modules import public_sources,service_store,task_results,requests_state


def _amount(value,separator='.'):
    if not isinstance(value,str) or separator not in ('.',','):raise ValueError('Sayı biçimi geçersiz.')
    value=value.strip().replace(' ','')
    if separator==',':value=value.replace('.','').replace(',','.')
    elif ',' in value:raise ValueError('Ondalık virgüllü veri için decimal="," belirt.')
    try:number=Decimal(value)
    except InvalidOperation:raise ValueError('Geçersiz sayısal hücre.') from None
    if not number.is_finite() or abs(number)>Decimal('1e18'):raise ValueError('Sayısal hücre sınır dışında.')
    return number


def csv_analysis(owner,kind,path,columns,decimal='.'):
    service_store.identity(owner)
    from modules import nxapi
    original=Path(path);source=nxapi.allowed(path)
    if (not source or not source.is_file() or source.suffix.lower()!='.csv' or original.is_symlink() or
        any(p.is_symlink() for p in original.parents) or source.stat().st_size>5_000_000):
        raise ValueError('Analiz için izinli kullanıcı alanında en fazla 5 MB CSV gerekli.')
    if not isinstance(columns,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in columns.items()):raise ValueError('Sütun eşleştirmesi gerekli.')
    required={'amount','kind'} if kind=='finance' else {'sku','quantity'} if kind=='store' else set()
    optional={'date'} if kind=='finance' else {'minimum','price'}
    if not required or not required.issubset(columns) or set(columns)-required-optional:raise ValueError('Analiz sütunları geçersiz.')
    raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise ValueError('CSV UTF-8 olmalı; kodlama tahmin edilmedi.') from None
    first=text.splitlines()[0] if text.splitlines() else ''
    delimiter=';' if first.count(';')>first.count(',') else ','
    reader=csv.DictReader(io.StringIO(text),delimiter=delimiter)
    if not reader.fieldnames or not set(columns.values()).issubset(reader.fieldnames):raise ValueError('Belirtilen sütun CSV başlığında yok.')
    income=expense=Decimal(0);units=Decimal(0);value=Decimal(0);low=[];seen=set();count=0
    for index,row in enumerate(reader,2):
        requests_state.check();count+=1
        if count>20000:raise ValueError('CSV 20.000 satır sınırını aşıyor.')
        if None in row or any(row.get(name) is None for name in columns.values()):raise ValueError('CSV satırında eksik/fazla hücre: '+str(index))
        try:
            if kind=='finance':
                amount=_amount(row[columns['amount']],decimal)
                if amount<0:raise ValueError('Gelir/gider tutarı negatif olamaz; tür ayrı sütundadır.')
                label=row[columns['kind']].strip().casefold()
                if label in ('gelir','income'):income+=amount
                elif label in ('gider','expense'):expense+=amount
                else:raise ValueError('İşlem türü gelir/income veya gider/expense olmalı.')
            else:
                sku=row[columns['sku']].strip()
                if not sku or len(sku)>120 or sku in seen:raise ValueError('Ürün kodu boş, fazla uzun veya yineleniyor.')
                seen.add(sku);quantity=_amount(row[columns['quantity']],decimal)
                if quantity<0:raise ValueError('Stok miktarı negatif olamaz.')
                units+=quantity
                if 'price' in columns:
                    price=_amount(row[columns['price']],decimal)
                    if price<0:raise ValueError('Birim değer negatif olamaz.')
                    value+=quantity*price
                if 'minimum' in columns:
                    minimum=_amount(row[columns['minimum']],decimal)
                    if minimum<0:raise ValueError('Minimum stok negatif olamaz.')
                    if quantity<minimum:low.append({'sku':sku,'quantity':str(quantity),'minimum':str(minimum),'difference':str(minimum-quantity)})
        except ValueError as exc:raise ValueError('CSV satırı '+str(index)+': '+str(exc)) from None
    if not count:raise ValueError('CSV veri satırı içermiyor.')
    if task_results.file_digest(source)!=digest:raise ValueError('CSV analiz sırasında değişti.')
    result=({'income':str(income),'expense':str(expense),'net':str(income-expense)} if kind=='finance' else
            {'products':count,'units':str(units),'inventory_value':str(value) if 'price' in columns else None,
             'below_minimum':low[:100],'below_minimum_count':len(low),'truncated':len(low)>100})
    return {'kind':kind,'rows':count,'result':result,'columns':columns,'decimal':decimal,
            'source_file':str(source),'source_sha256':digest,'source_unchanged':True,
            'scope':'Yalnız sağlanan CSV; canlı banka/mağaza bağlantısı veya stok/sipariş değişikliği yapılmadı.'}


def exchange(owner,base,quote,on_date=None,*,fetcher=None):
    service_store.identity(owner)
    if any(not isinstance(v,str) or not re.fullmatch('[A-Za-z]{3}',v) for v in (base,quote)):raise ValueError('Üç harfli para birimi gerekli.')
    if on_date is not None:
        if not isinstance(on_date,str):raise ValueError('Tarih YYYY-MM-DD olmalı.')
        date.fromisoformat(on_date)
    url='https://api.frankfurter.dev/v2/rate/'+base.lower()+'/'+quote.lower()
    if on_date:url+='?'+urlencode({'date':on_date})
    response=(fetcher or public_sources.fetch)(url);data=json.loads(response['body'])
    if not isinstance(data,dict) or data.get('base')!=base.upper() or data.get('quote')!=quote.upper():raise ValueError('Kur yanıtı para birimleriyle eşleşmiyor.')
    rate=_amount(str(data.get('rate','')))
    if rate<=0 or not isinstance(data.get('date'),str):raise ValueError('Kur/değer tarihi geçersiz.')
    date.fromisoformat(data['date'])
    if on_date and data['date']>on_date:raise ValueError('Kaynak istenen tarihten sonraki kuru döndürdü.')
    return {'data':data,'source':response['url'],'fetched_at':time.time(),
            'sha256':hashlib.sha256(response['body']).hexdigest(),'scope':'Günlük kaynak kuru; anlık banka alış/satış fiyatı değildir.'}


def headlines(owner,url,*,query=None,fetcher=None):
    from urllib3.exceptions import HTTPError
    service_store.identity(owner)
    if query is not None and (not isinstance(query,str) or not query.strip() or len(query)>300):raise ValueError('Kaynak sorgusu 1–300 karakter olmalı.')
    response=(fetcher or public_sources.fetch)(url)
    from modules import publisher_news
    items=public_sources.entries(publisher_news.listing(response))
    discovered_from=None
    if not items:
        for feed in public_sources.feeds(response):
            try:
                candidate=(fetcher or public_sources.fetch)(feed)
                rows=public_sources.entries(candidate)
            except PermissionError:raise
            except (ValueError,OSError,HTTPError):continue
            if rows:
                discovered_from=response['url'];response=candidate;items=rows;break
    if not items:raise ValueError('Kaynakta okunabilir haber/duyuru girdisi yok; varsa sayfanın ilan ettiği RSS/Atom bağlantıları da sonuç vermedi. Başka gerçek duyuru dizini seç.')
    if query is not None:
        def fold(value):return value.casefold().replace('ı','i').replace('\u0307','')
        terms=set(re.findall(r'[\w]+',fold(query)))
        def rank(row):
            title=fold(row['title']);text=fold(row.get('summary','')+' '+row['url'])
            return sum(3*(term in title)+(term in text) for term in terms if len(term)>2)
        items=sorted(items,key=rank,reverse=True)
    return {'items':items[:20],'source':response['url'],'discovered_from':discovered_from,'fetched_at':time.time(),
            'sha256':hashlib.sha256(response['body']).hexdigest(),'scope':'Kaynak başlıkları; metin doğruluğu veya karar kapsamı ayrıca incelenmeli.'}


def social(owner,service,operation,resource_id=None,limit=10):
    service_store.identity(owner)
    from modules import task_agents
    if service not in ('youtube','instagram'):raise ValueError('Sosyal analiz YouTube/Instagram mevcut hesap adaptörlerini kullanır.')
    data={'service':service,'operation':operation,'limit':limit}
    if resource_id is not None:data['resource_id']=resource_id
    output=task_agents.worker(owner,{'id':'social_read','agent':'account','input':data},{})
    if output.get('state')!='done':return output
    task_results.verify(output,owner=owner)
    return {'state':'done','source_receipt':output,'text':output['text'],
            'scope':'Mevcut yetkili hesabın okuma verisi; paylaşım, yorum yanıtlama ve hesap ayarı değiştirilmedi.'}
