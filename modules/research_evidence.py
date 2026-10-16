"""A research answer needs an explicit result and literal evidence from the fetched page."""
import json
import re


def news_requested(text):
    """Use the runtime request, not a model-supplied exemption, for dated news."""
    text=re.sub(r'\bhaber\s+ver\w*','',str(text),flags=re.I)
    return bool(re.search(r'\bhaber(?!leş)|\bgelişme|\bgelisme|\bduyuru|yayın tarih|yayin tarih|son\s+\d+\s+gün|\bnews\b',text,re.I))


def news_report_requested(request,instruction,dependencies):
    if any(o.get('snapshot',{}).get('operation')=='read_message' for o in dependencies.values()):return False
    return (any(o.get('news_article') for o in dependencies.values()) or news_requested(instruction) or
            news_requested(request) and (not dependencies or any(o.get('verification',{}).get('agent')=='research' for o in dependencies.values())))


def article(response):
    """Conservative single-article extraction; listing dates are never article dates."""
    from bs4 import BeautifulSoup
    from datetime import date
    from urllib.parse import urlsplit
    from modules import public_sources
    url=public_sources.address(response['url'])
    if urlsplit(url).path.rstrip('/').split('/')[-1].lower() in {'','haberler','haber','news','duyurular','announcements','bilim-teknoloji'}:
        raise ValueError('Bu adres haber dizini; data.headlines ile tekil haber bağlantısı seç.')
    soup=BeautifulSoup(response['body'],'html.parser')
    schemas=[]
    def walk(value):
        if isinstance(value,dict):
            types=value.get('@type',[]);types=[types] if isinstance(types,str) else types
            if any(t in ('NewsArticle','Article','BlogPosting','Report') for t in types):schemas.append(value)
            for item in value.values():walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    for node in soup.select('script[type="application/ld+json"]'):
        try:walk(json.loads(node.string or node.get_text()))
        except (ValueError,TypeError):pass
    # Multiple article objects are a collection, not a dated article receipt.
    if len(schemas)>1:raise ValueError('Sayfa birden fazla haber içeriyor; tekil haber sayfası gerekli.')
    og=soup.find('meta',attrs={'property':'og:type'})
    node=soup.select_one('[itemprop="articleBody"]') or soup.find('article')
    if node is None and (schemas or og and og.get('content')=='article'):node=soup.find('main') or soup.body
    titles=soup.find_all('h1')
    if node is None or len(titles)!=1 or len(node.find_all('article'))>1:
        raise ValueError('Tekil haber gövdesi ve başlığı doğrulanamadı; dizinden gerçek haber bağlantısını seç.')
    title=titles[0].get_text(' ',strip=True)
    def matching_schema(schema):
        page=schema.get('url') or schema.get('mainEntityOfPage')
        if isinstance(page,dict):page=page.get('@id')
        return schema.get('headline')==title and (not page or page.rstrip('/')==url.rstrip('/'))
    schemas=[s for s in schemas if matching_schema(s)]
    if not node.find('h1') and not schemas:
        raise ValueError('Başlık haber gövdesine ait değil; liste kartı haber kanıtı sayılmadı.')
    # Only published metadata tied to this page; dateModified and dates in other cards are excluded.
    dates=[s.get('datePublished') for s in schemas if s.get('datePublished')]
    scope=node.find_parent('article') or node
    def belongs(element):
        return bool(element.find_parent('head') or
                    (element is scope or scope in element.parents) and not element.find_parent('aside') and
                    element.find_parent('article') in (None,scope))
    for meta in soup.find_all('meta'):
        if belongs(meta) and (meta.get('property')=='article:published_time' or meta.get('itemprop')=='datePublished'):dates.append(meta.get('content',''))
    if not dates:
        dates=[n.get('datetime','') for n in scope.find_all('time') if belongs(n) and (n.get('itemprop')=='datePublished' or re.search(r'publish|posted', ' '.join(n.get('class',[])),re.I))]
    days=set()
    for value in dates:
        if not isinstance(value,str):continue
        if m:=re.match(r'^(\d{4}-\d{2}-\d{2})(?:T|\s|$)',value):
            try:days.add(date.fromisoformat(m[1]).isoformat())
            except ValueError:pass
    if len(days)!=1:raise ValueError('Haberin kendisine ait tek bir yayın tarihi doğrulanamadı; başka tarihli kaynak seç.')
    for hidden in node(['script','style','noscript','nav','footer','header','aside','svg']):hidden.decompose()
    text=re.sub(r'\s+',' ',node.get_text(' ',strip=True))[:20000]
    if len(text)<80 or not title:raise ValueError('Tekil haber metni yeterli değil.')
    return {'url':url,'title':title,'published':days.pop(),'text':text}


def news_receipt(output):
    """Validate the local article snapshot and literal quote scope, without network/model calls."""
    from datetime import date
    from modules import public_sources
    source=output.get('news_article')
    if not isinstance(source,dict) or set(source)!={'url','title','published','text'}:raise ValueError('Tarihli tekil haber kanıtı eksik.')
    if public_sources.address(source['url'])!=output.get('source') or not source['title'].strip():raise ValueError('Haber kaynağı eşleşmiyor.')
    date.fromisoformat(source['published'])
    parse(json.dumps({'supported':True,'answer':output['text'],'quotes':output.get('source_quotes')},ensure_ascii=False),source['text'])
    return source


def news_date(published,request):
    from datetime import datetime, timezone, timedelta, date
    today=datetime.now(timezone(timedelta(hours=3))).date()
    day=date.fromisoformat(published)
    if day>today:raise ValueError('Haberin yayın tarihi gelecekte; güncel gelişme olarak kullanılmadı.')
    ranges=[int(n) for n in re.findall(r'(?:son\s+)?(\d{1,4})\s*gün',request,re.I)]
    recent=bool(re.search(r'güncel|guncel|\bson\b.*(?:geliş|haber)|latest|recent',request,re.I))
    maximum=max(ranges) if ranges else 90 if recent else None
    if maximum is not None and (today-day).days>maximum:raise ValueError('Haber istenen tarih aralığının dışında; daha yeni kaynak seç.')


def unavailable_footer(urls):
    if not urls:return ''
    return '\n\n## Erişilemeyen kaynaklar ve kanıt alınamayan sayfalar\n\nBu adreslerden erişim veya içerik sorunu nedeniyle doğrulanmış yanıt alınamadı; raporun kanıtı olarak kullanılmadı:\n'+''.join('\n- '+url for url in urls)


def news_report(dependencies):
    """Render only dated source quotes. No model can add dates or malformed nested links."""
    def escape(text):return re.sub(r'([\\`*_{}\[\]<>#])',r'\\\1',re.sub(r'\s+',' ',text))
    lines=['# Kaynaklı haber raporu','','Bu rapor yalnız aşağıdaki tekil haberlerden doğrulanan yayın tarihlerini ve birebir alıntıları içerir. Kapsamın eksiksiz olduğu veya tüm istenen kurumların tarandığı anlamına gelmez.']
    if not dependencies:raise ValueError('Haber raporu için doğrulanmış tekil kaynak gerekli.')
    seen=set()
    for output in dependencies.values():
        source=news_receipt(output)
        if source['url'] in seen:continue
        seen.add(source['url'])
        lines+=['','## '+escape(source['title']),'','Yayın tarihi: '+source['published'],'','Kaynak: <'+source['url'].replace('>','%3E').replace('<','%3C')+'>','', 'Kaynak alıntıları:']
        lines+=['\n> '+escape(re.sub(r'\s+',' ',q)) for q in output['source_quotes']]
    return '\n'.join(lines)+'\n'


def parse(answer,source,*,allow_unsupported=False):
    try:
        data=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',str(answer).strip()))
    except (ValueError,TypeError):
        raise ValueError('Araştırma yanıtında kaynak alıntısı yok; başarı sayılmadı.') from None
    if allow_unsupported and isinstance(data,dict) and set(data)=={'supported','answer','quotes'} and data['supported'] is False and data['answer']=='' and data['quotes']==[]:return data
    if not isinstance(data,dict) or set(data)!={'supported','answer','quotes'} or data['supported'] is not True:
        raise ValueError('Kaynak soruyu yanıtlamıyor; başarı sayılmadı. Başka ilgili kaynak gerekli.')
    if not isinstance(data['answer'],str) or not data['answer'].strip():raise ValueError('Araştırma yanıtı boş; başarı sayılmadı.')
    quotes=data['quotes']
    if not isinstance(quotes,list) or not 1<=len(quotes)<=5:raise ValueError('1–5 gerçek kaynak alıntısı gerekli; başarı sayılmadı.')
    normalized=lambda value:re.sub(r'\s+',' ',value).strip()
    text=normalized(source)
    if any(not isinstance(q,str) or not 20<=len(q)<=800 or normalized(q) not in text for q in quotes):
        raise ValueError('Araştırma alıntısı okunan sayfada yok; başarı sayılmadı.')
    return data


def legacy_unsupported(answer):
    """Invalidate the known old no-answer receipt without deleting its journal."""
    return bool(re.search(r'(kaynakta desteklenen bir yanıt verilemem|herhangi bir bilgi yer almamak|bu sayfa soruya yanıt vermiyor|no relevant information (?:was )?found)',str(answer),re.I))
