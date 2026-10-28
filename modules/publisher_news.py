"""Verified publisher layouts and direct discovery. No third-party search service."""
import re
from datetime import date
from urllib.parse import urlsplit, unquote
from bs4 import BeautifulSoup

SOURCES=(
    {'name':'Yıldız Teknik Üniversitesi','url':'https://www.yildiz.edu.tr/medya/haberler'},
    {'name':'TÜBİTAK','url':'https://tubitak.gov.tr/tr/haberler'},
    {'name':'Boğaziçi Üniversitesi','url':'https://haberler.bogazici.edu.tr/'},
)


GENERAL_SOURCES=(
    {'name':'Mynet Haber','url':'https://www.mynet.com/haber/'},
    {'name':'Investing.com Türkçe','url':'https://tr.investing.com/news/'},
    {'name':'Anadolu Ajansı','url':'https://www.aa.com.tr/tr/gundem'},
    {'name':'BBC Türkçe','url':'https://www.bbc.com/turkce'},
    {'name':'DW Türkçe','url':'https://www.dw.com/tr/'},
    {'name':'Euronews Türkçe','url':'https://tr.euronews.com/'},
    {'name':'NTV','url':'https://www.ntv.com.tr/'},
    {'name':'T24','url':'https://t24.com.tr/'},
    {'name':'Bloomberg HT','url':'https://www.bloomberght.com/'},
    {'name':'Ekonomim','url':'https://www.ekonomim.com/'},
    {'name':'KAP','url':'https://www.kap.org.tr/tr/',
     'scope':'Resmî şirket açıklamaları; genel haber bülteni değildir'},
    {'name':'DonanımHaber','url':'https://www.donanimhaber.com/'},
    {'name':'Webtekno','url':'https://www.webtekno.com/'},
    {'name':'TRT Haber','url':'https://www.trthaber.com/'},
)


def _ai_request(request):
    return bool(re.search(r'yapay\s+zek|artificial\s+intelligence|\bai\b|makine\s+öğren|makine\s+ogren|machine\s+learning',str(request or ''),re.I))


def _ai_rows():
    """Genel haber tabanı korunur; yalnız gerçek AI/teknoloji yayıncıları okuma bütçesine öne alınır."""
    baseline=list(GENERAL_SOURCES[:4])
    preferred_names=('DonanımHaber','Webtekno')
    combined=list(GENERAL_SOURCES)
    by_name={row['name']:row for row in combined}
    rows=baseline+[by_name[name] for name in preferred_names if name in by_name]
    seen={row['url'] for row in rows}
    rows.extend(row for row in combined if row['url'] not in seen)
    return rows


def sources_for(request=None):
    """Configured discovery indexes, not live-health or article evidence claims."""
    institutional=request is None or re.search(r'üniversite|universite|akademik|tübitak|tubitak|boğaziçi|bogazici|dumlupınar|dumlupinar|yıldız|yildiz',str(request),re.I)
    if institutional:
        rows=list(SOURCES)
    elif _ai_request(request):
        rows=_ai_rows()
    else:
        rows=list(GENERAL_SOURCES)
    institutional_urls={row['url'] for row in SOURCES}
    return [dict(row,scope=row.get('scope','Kurum/üniversite duyuruları' if row['url'] in institutional_urls else 'Genel ve konu odaklı haber keşfi'),
                 live_connection_tested=False) for row in rows]


def multiple_publishers(request):
    restricted=re.search(r'https://|sadece|yalnız|yalniz|\bonly\b|tek (?:haber|kaynak)|bir haber|üniversitesi|universitesi|tübitak|tubitak|boğaziçi|bogazici|dumlupınar|dumlupinar|yıldız|yildiz',request,re.I)
    return not restricted and bool(re.search(r'son\s+dakika|genel|gündem|gundem|haberler\w*|gelişmeler\w*|gelismeler\w*|\bnews\b',request,re.I))


def recovery_indexes(request,seeds):
    """Select scoped real indexes; old institutional guesses cannot trap general news."""
    scoped=bool(re.search(r'sadece|yalnız|yalniz|\bonly\b|https://',request,re.I))
    named=bool(re.search(r'üniversitesi|universitesi|bakanlığı|bakanligi|ofisi|enstitüsü|enstitusu|tübitak|tubitak|boğaziçi|bogazici|dumlupınar|dumlupinar|yıldız|yildiz|sanayi|cumhurbaşkan|cumhurbaskan',request,re.I))
    if scoped or named:return list(dict.fromkeys(seeds))[:4]
    # Recovery completion contract keeps the historical general-news baseline.
    # AI/topic prioritization belongs to discovery only and must not change this order.
    known=[s['url'] for s in GENERAL_SOURCES]
    host=lambda url:(urlsplit(url).hostname or '').removeprefix('www.')
    preferred=[url for url in known if any(host(seed)==host(url) for seed in seeds)]
    broad=bool(re.search(r'türkiye|turkiye|üniversitelerin|universitelerin|kaynakları sen|kaynaklari sen',request,re.I))
    excluded={host(s['url']) for s in SOURCES+GENERAL_SOURCES}
    discovered=[] if broad or multiple_publishers(request) else [url for url in seeds if host(url) not in excluded]
    ordered=(preferred+known+discovered) if multiple_publishers(request) else (discovered+preferred+known)
    return list(dict.fromkeys(ordered))[:4]


def publisher_key(url):
    labels=(urlsplit(url).hostname or '').removeprefix('www.').split('.')
    return '.'.join(labels[-3:] if '.'.join(labels[-2:]) in {'edu.tr','gov.tr','com.tr','org.tr'} else labels[-2:])


def catalog_keys(request=None):
    """Required baseline: up to four default indexes; other catalog entries are alternatives."""
    return {publisher_key(row['url']) for row in sources_for(request)[:4]}


def catalog_attempted(job):
    """Only a completed or failed execution counts as an attempted catalog read."""
    keys=set();known={row['url']:publisher_key(row['url']) for row in sources_for(job.get('request'))[:4]}
    for step in job.get('steps',[]):
        data=step.get('input',{});output=job.get('outputs',{}).get(step.get('id'),{})
        if (step.get('tool')=='data' and data.get('operation')=='headlines' and
                data.get('url') in known and step.get('started') is True and
                step.get('state') in {'done','failed'} and output.get('state')==step['state']):
            keys.add(known[data['url']])
    return keys


def broad_research(request):
    return bool(re.search(r'türkiye|turkiye|üniversitelerin|universitelerin',request,re.I) and
               not re.search(r'https://|sadece|yalnız|yalniz|tek (?:haber|kaynak)|bir haber|üniversitesi|universitesi|tübitak|tubitak|bakanlığı|bakanligi|ofisi|boğaziçi|bogazici|dumlupınar|dumlupinar|yıldız|yildiz|sanayi|cumhurbaşkan|cumhurbaskan',request,re.I))


def require_catalog(job):
    if not broad_research(job['request']):return
    attempted=catalog_attempted(job);known=catalog_keys(job['request'])
    if not known.issubset(attempted):
        raise ValueError(f'Genel Türkiye araştırması henüz tamamlanmadı: kayıtlı haber kataloğunun {len(attempted)}/{len(known)} kaynağı denendi. Kalan kayıtlı kaynakları tara; erişilemeyenleri raporda belirt.')


def candidate_url(url,request,outputs):
    """Model guesses are not news links: require user, catalog or actual discovery provenance."""
    from modules.public_sources import address
    candidate=address(url)
    allowed={address(s['url']) for s in SOURCES+GENERAL_SOURCES}
    for raw in re.findall(r'https://[^\s<>"\]]+',request):
        try:allowed.add(address(raw.rstrip('.,;)'))
        except ValueError:pass
    for output in outputs.values():
        if output.get('state')!='done':continue
        if output.get('source'):allowed.add(output['source'])
        for row in output.get('structured',{}).get('items',[]):
            if isinstance(row,dict) and isinstance(row.get('url'),str):allowed.add(row['url'])
    if candidate not in allowed:
        raise ValueError('Bu haber adresi kullanıcıdan, kayıtlı yayıncı dizininden veya doğrulanmış bağlantı keşfinden gelmedi. data operation=sources ve kayıtlı known_news_sources adresleriyle headlines kullan; URL yolu uydurma.')
    return candidate


def listing(response):
    """Keep real story links ahead of navigation before the generic 50-link cap."""
    host=urlsplit(response['url']).hostname
    selector=('a[href*="/tr/haber_oku/"]' if host=='haber.dpu.edu.tr' else
              'a[href*="/universite/haberler/"]' if host in {'yildiz.edu.tr','www.yildiz.edu.tr'} else None)
    if selector is None:return response
    soup=BeautifulSoup(response['body'],'html.parser')
    return {**response,'body':(''.join(str(a) for a in soup.select(selector))).encode('utf-8')}


def _same_url(raw,url):
    a=urlsplit(raw);b=urlsplit(url)
    return (a.scheme in {'http','https'} and not a.username and not a.password and a.port in (None,80,443) and
            (a.hostname or '').removeprefix('www.')==(b.hostname or '').removeprefix('www.') and
            unquote(a.path).rstrip('/')==unquote(b.path).rstrip('/') and a.query==b.query)


def _published(text):
    months={'ocak':1,'şubat':2,'mart':3,'nisan':4,'mayıs':5,'haziran':6,'temmuz':7,'ağustos':8,'eylül':9,'ekim':10,'kasım':11,'aralık':12}
    match=re.match(r'^(\d{1,2})\s+([\wÇĞİÖŞÜçğıöşü]+)\s+(\d{4})(?:\b|$)',text.strip())
    if not match or match[2].casefold() not in months:raise ValueError('Yayıncının kendi yayın tarihi okunamadı.')
    return date(int(match[3]),months[match[2].casefold()],int(match[1])).isoformat()


def article(response):
    """Only checked layouts; generic articles keep their existing stricter reader."""
    from modules import public_sources
    url=public_sources.address(response['url']);parsed=urlsplit(url)
    ytu=parsed.hostname in {'yildiz.edu.tr','www.yildiz.edu.tr'} and parsed.path.startswith('/universite/haberler/')
    dpu=parsed.hostname=='haber.dpu.edu.tr' and bool(re.fullmatch(r'/tr/haber_oku/[a-f0-9]+/[^/]+/?',parsed.path))
    if not ytu and not dpu:return None
    soup=BeautifulSoup(response['body'],'html.parser')
    if ytu:
        nodes=soup.select('#block-ytu-content > article.modern-news-article')
        canonical=soup.find('link',rel='canonical')
        if len(nodes)!=1 or canonical is None or not _same_url(canonical.get('href',''),url):raise ValueError('YTÜ haber gövdesi/canonical eşleşmedi.')
        node=nodes[0];titles=node.select('header.mn-header h1.mn-title');dates=node.select('header.mn-header .mn-meta-date');bodies=node.select('.mn-body')
    else:
        nodes=soup.select('#main.article > article#article-post')
        if len(nodes)!=1:raise ValueError('DPÜ tekil haber gövdesi bulunamadı.')
        node=nodes[0];titles=node.select('header h1');dates=node.select('footer .author-box > p');bodies=[node]
        refs=node.select('footer [data-href]')
        if not refs or any(not _same_url(n.get('data-href',''),url) for n in refs):raise ValueError('DPÜ haber bağlantısı sayfayla eşleşmedi.')
    if len(titles)!=1 or len(dates)!=1 or len(bodies)!=1 or node.find('article'):
        raise ValueError('Yayıncıda tekil başlık, gövde ve tarih eşleşmedi.')
    title=titles[0].get_text(' ',strip=True)
    if not title or any(h.get_text(' ',strip=True) not in ('',title) for h in soup.find_all('h1')):
        raise ValueError('Başlık başka haber veya liste başlığıyla çelişiyor.')
    stamp=dates[0].get_text(' ',strip=True)
    if dpu:
        prefix='Kurumsal İletişim Koordinatörlüğü - '
        if not stamp.startswith(prefix):raise ValueError('DPÜ yayın tarihi etiketi eksik.')
        stamp=stamp[len(prefix):]
    published=_published(stamp)
    body=bodies[0]
    for n in body(['script','style','noscript','nav','footer','header','aside','svg']):n.decompose()
    text=re.sub(r'\s+',' ',body.get_text(' ',strip=True))[:20000]
    if len(text)<80:raise ValueError('Yayıncı haber gövdesi yeterli değil.')
    return {'url':url,'title':title,'published':published,'text':text}
