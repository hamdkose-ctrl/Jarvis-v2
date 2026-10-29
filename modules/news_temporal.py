"""Separate requested publication time from event validity; no IO or model authority."""
from datetime import datetime,timedelta,timezone,date
import re

ISTANBUL=timezone(timedelta(hours=3))

class EventContextRequired(ValueError):
    """Missing user-owned scope; Core may ask, worker cannot choose it."""
    question='Hangi yer veya kapsam için bu kararı doğrulamamı istiyorsun?'


def request_scope(request,*,now=None,reference=None):
    now=now or datetime.now(ISTANBUL)
    if now.tzinfo is None:raise ValueError('Başvuru zamanı saat dilimli olmalı.')
    now=now.astimezone(ISTANBUL)
    reference=reference or now
    if reference.tzinfo is None:raise ValueError('İstek referans zamanı saat dilimli olmalı.')
    reference=reference.astimezone(ISTANBUL)
    text=str(request).casefold().replace('ı','i').replace('\u0307','')
    base={'intent':'publication_window','start':None,'end':now,'event_date':None,'requires_clock':False}
    # A future event date says nothing about when its announcement was published.
    if re.search(r'\byarin\b',text):
        return dict(base,intent='event_verification',event_date=(reference+timedelta(days=1)).date(),end=None)
    hours=re.search(r'\bson\s+(\d{1,4})\s+saat',text)
    days=re.search(r'\bson\s+(\d{1,4})\s+g[uü]n',text)
    if hours:
        value=int(hours[1])
        if not 1<=value<=2160:raise ValueError('Saat aralığı 1–2160 olmalı.')
        return dict(base,start=now-timedelta(hours=value),requires_clock=True)
    if days:
        value=int(days[1])
        if not 1<=value<=90:raise ValueError('Gün aralığı 1–90 olmalı.')
        return dict(base,start=now-timedelta(days=value))
    if re.search(r'\bson\s+dakika\b',text):
        return dict(base,start=now-timedelta(hours=1),requires_clock=True)
    midnight=now.replace(hour=0,minute=0,second=0,microsecond=0)
    if re.search(r'\bbu\s+sabah\b',text):
        return dict(base,start=midnight,end=min(now,midnight+timedelta(hours=12)),requires_clock=True)
    if re.search(r'\bbug[uü]n\w*',text):return dict(base,start=midnight)
    if re.search(r'\b(?:19|20)\d{2}\b',text):return dict(base,intent='historical',end=None)
    return dict(base,start=now-timedelta(days=7))


def check_publication(article,scope):
    if scope['intent']!='publication_window':
        raise ValueError('Olay/geçmiş dönem doğrulaması yayın yaşıyla sonuçlandırılamaz.')
    day=date.fromisoformat(article['published'])
    stamp=article.get('published_at')
    if stamp is not None:
        stamp=datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if stamp.tzinfo is None:raise ValueError('Yayın saati saat dilimiyle doğrulanmalı.')
        if stamp.date()!=day:raise ValueError('Yayın günü ve saati çelişiyor.')
        stamp=stamp.astimezone(ISTANBUL)
        if stamp>scope['end'] or scope['start'] and stamp<scope['start']:
            raise ValueError('Haber istenen yayın aralığının dışında.')
    else:
        if scope['requires_clock']:raise ValueError('Bu istek için doğrulanmış yayın saati gerekli.')
        if day>scope['end'].date() or scope['start'] and day<scope['start'].date():
            raise ValueError('Haber istenen yayın günlerinin dışında.')


def validate_event_evidence(payload,*,source_text,source_url,request,scope):
    """Bind an event claim to a literal quote; publication time is not event time."""
    if scope['intent']!='event_verification':raise ValueError('Olay doğrulama kapsamı yok.')
    if not isinstance(payload,dict) or set(payload)!={'supported','answer','quotes','event_date','scope'}:
        raise ValueError('Olay tarih/kapsam kanıtı eksik.')
    from modules import research_evidence
    evidence=research_evidence.parse(__import__('json').dumps({k:payload[k] for k in ('supported','answer','quotes')}),source_text)
    target=scope['event_date']
    if payload['event_date']!=target.isoformat():raise ValueError('Olay tarihi istenen günle eşleşmiyor.')
    def fold(value):return ' '.join(str(value).casefold().replace('ı','i').replace('\u0307','').split())
    named_scope=payload['scope']
    if not isinstance(named_scope,str) or not named_scope.strip() or fold(named_scope) not in fold(request):
        raise EventContextRequired(EventContextRequired.question)
    months=['ocak','şubat','mart','nisan','mayıs','haziran','temmuz','ağustos','eylül','ekim','kasım','aralık']
    labels=[target.isoformat(),target.strftime('%d.%m.%Y'),f'{target.day} {months[target.month-1]} {target.year}']
    if not any(fold(named_scope) in fold(q) and any(fold(day) in fold(q) for day in labels) for q in evidence['quotes']):
        raise ValueError('İstenen olay tarihi ve kapsam aynı gerçek alıntıda doğrulanamadı.')
    # Administrative decisions need a primary government source, not a news headline.
    if re.search(r'karar|tatil|iptal|duyuru',request,re.I):
        from urllib.parse import urlsplit
        host=(urlsplit(source_url).hostname or '').lower()
        if not host.endswith('.gov.tr'):
            raise ValueError('Bu karar için yetkili resmî birincil kaynak gerekli.')
        # Recognize only a source bound to the explicitly requested local scope.
        # Unknown/national authority mappings remain unresolved; a government
        # suffix alone must not authorize an unrelated jurisdiction.
        place=fold(named_scope).translate(str.maketrans('çğöşü','cgosu'))
        roots=(place+'.gov.tr',place+'.meb.gov.tr') if re.fullmatch(r'[a-z]+',place) else ()
        if not any(host==root or host.endswith('.'+root) for root in roots):
            raise ValueError('Resmî kaynağın istenen yer/kapsama bağlılığı doğrulanamadı; başka birincil kaynak gerekli.')
    return evidence


def event_receipt(output, *, request=None, reference=None):
    """Revalidate persisted event evidence; Core can supply original request identity."""
    proof=output.get('event_evidence')
    if not isinstance(proof,dict) or set(proof)!={'claim','source_text','request','reference'}:
        raise ValueError('Kayıtlı olay kanıtı eksik.')
    text=proof['source_text']
    if not isinstance(text,str) or not 80<=len(text)<=12000 or output.get('source_chars')!=len(text):
        raise ValueError('Olay kaynağı metin kanıtı geçersiz.')
    if request is not None and proof['request']!=request:
        raise ValueError('Olay kanıtı özgün istekle eşleşmiyor.')
    stamp=datetime.fromisoformat(proof['reference'])
    if stamp.tzinfo is None:raise ValueError('Olay referansı saat dilimli olmalı.')
    if reference is not None and stamp!=reference:
        raise ValueError('Olay referansı özgün istek zamanı ile eşleşmiyor.')
    from modules.browser_agent import _url
    source=_url(output.get('source',''))
    checked=validate_event_evidence(proof['claim'],source_text=text,source_url=source,
        request=proof['request'],scope=request_scope(proof['request'],reference=stamp))
    if output.get('source_quotes')!=checked['quotes']:
        raise ValueError('Olay alıntıları kayıtlı kaynakla eşleşmiyor.')
    return checked
