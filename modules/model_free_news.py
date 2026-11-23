"""Model-free dated-news reading for durable research.

A verified single article is evidence on its own. This module extracts a few literal,
query-relevant sentences and seals them as a normal research receipt without consuming
an LLM/provider quota. It never invents claims or publication dates.
"""
from __future__ import annotations
import re

from modules import privacy, public_sources, research_delivery, research_evidence, requests_state, task_results

_STOP={
    'haber','haberler','haberleri','haberi','guncel','güncel','son','durum','nelerdir','nedir','neler','ne','var','bugun','bugün',
    'anlat','anlatir','anlatır','gelisme','gelişme','gelismeler','gelişmeler','hakkinda','hakkında','icin','için',
    'ara','arastir','araştır','bak','bakar','latest','news','recent','today','what','about','the','and','ile','bir',
    'bunları','bunlari','özetle','ozetle',
    'haberini','haberlerini','haberlerden','sadece','yalnız','yalniz','kaynak','kaynakları','kaynaklari',
    'rapor','raporu','dosya','dosyaya','kaydet','markdown','oluştur','olustur','ver','gün','gun','günde','gunde',
}

# Request geography is data, not feature-specific branching. Add aliases here without
# changing validation logic or coupling geography to a subject such as artificial intelligence.
_GEOGRAPHY_ALIASES={
    'Türkiye': ('türkiye','turkiye','turkey','türk','turk','turkish','istanbul','ankara','izmir'),
    'Almanya': ('almanya','germany','alman','german','berlin','münih','munih','munich'),
    'ABD': ('abd','amerika birleşik devletleri','amerika birlesik devletleri','united states','usa','u.s.','american','amerikan','washington'),
    'İngiltere': ('ingiltere','birleşik krallık','birlesik krallik','united kingdom','britain','british','london','londra'),
    'Fransa': ('fransa','france','french','fransız','fransiz','paris'),
    'İtalya': ('italya','italy','italian','roma','rome'),
    'İspanya': ('ispanya','spain','spanish','madrid'),
    'Rusya': ('rusya','russia','russian','moskova','moscow'),
    'Çin': ('çin','cin','china','chinese','pekin','beijing'),
    'Japonya': ('japonya','japan','japanese','tokyo'),
    'Hindistan': ('hindistan','india','indian','delhi'),
}


def _fold(value):
    return str(value).casefold().replace('ı','i').replace('\u0307','')


_FOLDED_STOP = frozenset(_fold(word) for word in _STOP)


def terms(value):
    """Return topical words only; generic news/request words do not create false relevance."""
    result=[]
    topical = re.sub(r'https?://[^\s<>|]+', ' ', _fold(value))
    topical = re.sub(r'\bson\s+dakika\b', ' ', topical)
    topical = re.sub(r'\bhaber\s+(?:ler|leri|lerini|lerden|lerinden|i|ini)\b', 'haber', topical)
    for aliases in _GEOGRAPHY_ALIASES.values():
        for alias in aliases:
            topical = re.sub(r'(?<!\w)'+re.escape(_fold(alias))+r'(?!\w)', ' ', topical)
    for word in re.findall(r'[\wçğıöşüâîû-]+',topical,re.UNICODE):
        word=word.strip('-_')
        if len(word)<3 or word in _FOLDED_STOP or word.isdigit():continue
        if word not in result:result.append(word)
        if len(result)>=16:break
    return result


def _ai_scope_ok(article, request):
    """If AI is an explicit requested subject, the article itself must contain AI evidence."""
    wanted=_fold(request)
    ai_requested=(re.search(r'\byapay\s+zek',wanted) is not None or
                  'artificial intelligence' in wanted or re.search(r'\bai\b',wanted) is not None)
    if not ai_requested:
        return True
    body=re.sub(r'\s+',' ',article.get('text') or '').strip()
    title=re.sub(r'\s+',' ',article.get('title') or '').strip()
    if title and body.startswith(title) and (len(body)==len(title) or body[len(title)] in ' :-–—'):
        body=body[len(title):].lstrip(' :-–—')
    haystack=_fold(body)
    return bool(re.search(r'\byapay\s+zek',haystack) or 'artificial intelligence' in haystack or
                re.search(r'\bai\b',haystack))


def requested_geographies(request):
    """Return explicitly named geographies using one reusable, data-driven contract."""
    wanted=_fold(request)
    result=[]
    for name, aliases in _GEOGRAPHY_ALIASES.items():
        if any(re.search(r'(?<!\w)'+re.escape(_fold(alias))+r'(?!\w)', wanted) for alias in aliases):
            result.append((name, aliases))
    return result


def _geography_scope_ok(article, request):
    requested=requested_geographies(request)
    if not requested:
        return True, None
    haystack=_fold((article.get('title') or '')+' '+(article.get('text') or ''))
    for name, aliases in requested:
        if not any(re.search(r'(?<!\w)'+re.escape(_fold(alias))+r'(?!\w)', haystack) for alias in aliases):
            return False, name
    return True, None


# Sayfa çerçevesi: menü, öneri kutusu, footer. Canlı kusur (22 Kasım 2026): alakasız
# haber (kar yağışı) "doğrulanmış" sayıldı çünkü kanıt olarak menüdeki "Son seçim anketi
# yayınlandı!" kutusu seçildi. Çerçeve cümlesi kanıt olamaz.
_CHROME_MARKERS = ('güncel', 'politika', 'son dakika', 'kategoriler', 'tümünü gör',
                   'iletişim', 'gizlilik', 'reklam', 'çerez', 'abone', 'künye', 'hakkımızda',
                   'copyright', 'teknoloji', 'otomobil', 'eğitim', 'sağlık', 'yaşam')


def _chrome(sentence):
    """Menü/öneri kutusu cümlesi mi? Kanıt seçiminde kullanılmaz."""
    folded = _fold(sentence)
    return sum(1 for marker in _CHROME_MARKERS if marker in folded) >= 3


def _sentences(text):
    text=re.sub(r'\s+',' ',str(text)).strip()
    rows=[]
    for match in re.finditer(r'[^.!?]+(?:[.!?]+|$)',text):
        sentence=match.group(0).strip()
        if 25<=len(sentence)<=800:rows.append((match.start(),sentence))
    return rows


def quotes(article,request):
    """Pick 1-3 exact article sentences and enforce explicit request scope for news verification."""
    if not _ai_scope_ok(article,request):
        raise ValueError('Tekil haber kullanıcının istediği yapay zekâ konusuyla eşleşmiyor; başka gerçek haber bağlantısı seç.')
    text=re.sub(r'\s+',' ',article['text']).strip()
    title=re.sub(r'\s+',' ',article['title']).strip()
    if title and text.startswith(title) and (len(text)==len(title) or text[len(title)] in ' :-–—'):
        text=text[len(title):].lstrip(' :-–—')
    rows=[(pos,sentence) for pos,sentence in _sentences(text) if not _chrome(sentence)]
    if not rows:raise ValueError('Haber gövdesinde aktarılabilir tam cümle bulunamadı.')
    wanted=terms(request)
    folded_title=_fold(title)
    title_topic=any(term in folded_title for term in wanted)
    scored=[]
    for pos,sentence in rows:
        folded=_fold(sentence)
        # Konu, cümlenin kendisinde geçmeli. Eskiden başlık eşleşmesi her cümleye 2 puan
        # ekliyordu; bu yüzden konu geçmeyen cümleler de "kanıt" sayılabiliyordu.
        hits=sum(1 for term in wanted if term in folded)
        score=hits*3+(2 if title_topic else 0)
        scored.append((score,pos,sentence,hits))
    eslesen=[row for row in scored if row[3]>0]
    # Konu haberde başlıkta ya da girişte olmalı. Sayfanın ilerisindeki "ilgili haberler"
    # bağlantısı ("Son seçim anketi yayınlandı!") kanıt değildir: kar yağışı haberi
    # "seçim" diye doğrulanıyordu (canlı 22 Kasım 2026).
    lead=_fold(' '.join(sentence for _pos, sentence in rows[:2]))
    lead_topic=any(term in lead for term in wanted)
    if wanted and not (title_topic or lead_topic):
        raise ValueError('Haber başlığı istenen konuyla eşleşmiyor; başka gerçek haber bağlantısı seç.')
    if wanted and eslesen:
        scored=eslesen
    geography_ok, missing=_geography_scope_ok(article,request)
    if not geography_ok:
        raise ValueError(f'Tekil haber istenen {missing} coğrafya kapsamını kanıtlamıyor.')
    selected=sorted(scored,key=lambda row:(-row[0],row[1]))[:3]
    if not wanted:selected=scored[:3]
    selected=sorted(selected,key=lambda row:row[1])
    result=[]
    for row in selected:
        sentence=row[2]
        sentence=re.sub(r'\s+',' ',sentence).strip()
        if sentence not in result:result.append(sentence)
    if not result:raise ValueError('Haber gövdesinden doğrulanabilir alıntı seçilemedi.')
    return result


def receipt(article,request,*,source_only=True):
    """Seal already-read pipeline evidence; never fetch or call a provider."""
    url=str((article or {}).get('url') or '')
    if (blocked:=privacy.blocked('web')) and not privacy.public_read(url):raise PermissionError(blocked)
    requests_state.check()
    research_evidence.news_date(article,request)
    evidence=quotes(article,request)
    return task_results.seal('research',{
        'state':'done','text':' '.join(evidence),'source':article['url'],
        'source_chars':len(article['text']),'source_quotes':evidence,
        'source_only':bool(source_only),'news_article':article})


def run(owner,data,request,*,source_only=False):
    """Fetch, verify and render one dated article without any LLM call."""
    if not isinstance(data,dict) or not isinstance(data.get('url'),str):raise ValueError('Araştırma için haber adresi gerekli.')
    if (blocked:=privacy.blocked('web')) and not privacy.public_read(data['url']):raise PermissionError(blocked)
    requests_state.check()
    response=public_sources.fetch(data['url'])
    article=research_evidence.article(response)
    sealed=receipt(article,request or data.get('question',''),source_only=source_only)
    return sealed if source_only else research_delivery.synthesize(sealed,request)

