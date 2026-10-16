"""A research answer needs an explicit result and literal evidence from the fetched page."""
import json
import re


def news_requested(text):
    """Use the runtime request, not a model-supplied exemption, for dated news."""
    text=re.sub(r'\bhaber\s+ver\w*','',str(text),flags=re.I)
    return bool(re.search(r'\bhaber(?!leş)|\bgelişme|\bgelisme|\bduyuru|gündem|gundem|haftal[ıi]k\s+olay|yayın tarih|yayin tarih|son\s+\d+\s+gün|\bnews\b',text,re.I))


def news_report_requested(request,instruction,dependencies):
    if any(o.get('snapshot',{}).get('operation')=='read_message' for o in dependencies.values()):return False
    return (any(o.get('news_article') for o in dependencies.values()) or news_requested(instruction) or
            news_requested(request) and (not dependencies or any(o.get('verification',{}).get('agent')=='research' for o in dependencies.values())))


def article(response):
    """Conservative single-article extraction; listing dates are never article dates."""
    from modules import publisher_news
    direct=publisher_news.article(response)
    if direct is not None:return direct
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
    # TÜBİTAK's single-news template renders the page title as a sibling block.
    # Bind only that exact publisher layout and canonical URL, not arbitrary lists.
    canonical=soup.find('link',rel='canonical')
    publisher_title=soup.select_one('#block-feza-gursey-page-title h1')
    publisher_body=soup.select_one('#block-feza-gursey-content > article')
    region=node.find_parent(class_='region-content')
    tubitak=(urlsplit(url).hostname=='tubitak.gov.tr' and urlsplit(url).path.startswith('/tr/haber/') and
             canonical is not None and canonical.get('href','').rstrip('/')==url.rstrip('/') and
             publisher_title is titles[0] and publisher_body is node and region is not None and
             publisher_title.find_parent(class_='region-content') is region and len(region.find_all('article'))==1)
    if not node.find('h1') and not schemas and not tubitak:
        raise ValueError('Başlık haber gövdesine ait değil; liste kartı haber kanıtı sayılmadı.')
    # Only published metadata tied to this page; dateModified and dates in other cards are excluded.
    dates=[s.get('datePublished') for s in schemas if s.get('datePublished')]
    if tubitak:
        months={'oca':1,'şub':2,'mar':3,'nis':4,'may':5,'haz':6,'tem':7,'ağu':8,'eyl':9,'eki':10,'kas':11,'ara':12}
        for label in node.select('.node-date'):
            if label.find_parent('aside'):continue
            match=re.fullmatch(r'(\d{1,2})\s+([\wÇĞİÖŞÜçğıöşü]+)\s+(\d{4})',label.get_text(' ',strip=True))
            if match and match[2].casefold() in months:
                try:dates.append(date(int(match[3]),months[match[2].casefold()],int(match[1])).isoformat())
                except ValueError:pass
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


def news_window(request):
    ranges=[int(n) for n in re.findall(r'(?:son\s+)?(\d{1,4})\s*gün',request,re.I)]
    recent=bool(re.search(r'güncel|guncel|\bson\b.*(?:geliş|haber)|haftalık|haftalik|bu hafta|weekly|latest|recent',request,re.I))
    if ranges:return max(ranges)
    if recent:return 7
    # An explicit historical year is a user-selected historical request.
    historical=bool(re.search(r'\b(?:19|20)\d{2}\b',request))
    return 7 if not historical and (news_requested(request) or re.search(r'gündem|gundem',request,re.I)) else None


def news_date(published,request):
    from datetime import datetime, timezone, timedelta, date
    today=datetime.now(timezone(timedelta(hours=3))).date()
    day=date.fromisoformat(published)
    if day>today:raise ValueError('Haberin yayın tarihi gelecekte; güncel gelişme olarak kullanılmadı.')
    maximum=news_window(request)
    if maximum is not None and (today-day).days>maximum:raise ValueError('Haber istenen tarih aralığının dışında; daha yeni kaynak seç.')


def unavailable_footer(urls):
    if not urls:return ''
    from modules.public_sources import address
    from urllib.parse import urlsplit
    clean=[];rejected=0
    for url in urls:
        try:
            normalized=address(url)
            host=urlsplit(normalized).hostname or ''
            if len(host.split('.'))<2 or len(host.split('.')[-1])<2 or host.startswith('www.') and len(host.split('.'))<3:
                raise ValueError('Eksik alan adı')
            if normalized not in clean:clean.append(normalized)
        except (ValueError,TypeError):rejected+=1
    return ('\n\n## Erişilemeyen kaynaklar ve kanıt alınamayan sayfalar\n\nBu adreslerden erişim veya içerik sorunu nedeniyle doğrulanmış yanıt alınamadı; raporun kanıtı olarak kullanılmadı:\n'+
            ''.join('\n- '+url for url in clean)+(f'\n\nAyrıca {rejected} geçersiz/eksik adres kaynak olarak kullanılmadı.' if rejected else ''))


def vague_question(question,request):
    def fold(text):return re.sub(r'[^\w]+',' ',text.casefold()).strip()
    value=fold(question)
    return value in {'eksik somut bilgi','eksik bilgi','daha fazla bilgi','detay ver','bilgi gerekli'} or value==fold(request)


def preview(output):
    """Keep user-facing news readable while retaining legacy preview compatibility."""
    sources=([output['news_article']] if output.get('news_article') else
             [row['news_article'] for row in output.get('news_report_evidence',{}).get('sources',{}).values() if row.get('news_article')])
    unique={source['url']:source for source in sources}
    report=bool(output.get('news_report_evidence'))
    if report and output.get('file'):
        return ''
    lines=[]
    if report:
        from modules.publisher_news import publisher_key
        publishers={publisher_key(url) for url in unique}
        lines.append(f'{len(unique)} haber, {len(publishers)} farklı yayıncı doğrulandı. Tam alıntılar rapor dosyasında.')
    for source in list(unique.values())[:4]:
        title=re.sub(r'([\\`*_{}\[\]<>#])',r'\\\1',re.sub(r'\s+',' ',source['title']))
        url=source['url'].replace('<','%3C').replace('>','%3E')
        lines.append(title+' · '+source['published']+'\nKaynak: '+url)
    if len(unique)>4:lines.append('Diğer kaynaklar rapor dosyasında.')
    return '\n\n'.join(lines)


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


def literal_ai_quotes(article,request):
    """Narrow model-free fallback: literal AI excerpts, never an inferred answer."""
    if not re.search(r'yapay\s+zek[aâ]',request,re.I):raise ValueError('Bu konu için modelsiz alıntı seçimi desteklenmiyor.')
    text=article['text'];quotes=[]
    if text.startswith(article['title']):text=text[len(article['title']):].lstrip()
    for match in re.finditer(r'yapay\s+zek[aâ]',text,re.I):
        boundary=text.rfind('. ',0,match.start());start=0 if boundary<0 else boundary+2
        end=text.find('. ',match.end())
        end=len(text) if end<0 else end+1
        excerpt=text[start:min(end,start+700)].strip()
        if re.search(r'yapay\s+zek[aâ]',excerpt,re.I) and 20<=len(excerpt)<=800 and excerpt not in quotes:quotes.append(excerpt)
        if len(quotes)>=3:break
    if not quotes:raise ValueError('Haber gövdesinde yapay zekâ hakkında yeterli birebir alıntı bulunamadı.')
    return {'supported':True,'answer':'Modelsiz kaynak alıntıları; kapsam ve yorum doğrulanmadı.','quotes':quotes}


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
