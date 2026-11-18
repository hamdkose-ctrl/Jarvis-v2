"""Verified publisher layouts and direct discovery. No third-party search service."""
import re
from datetime import date
from urllib.parse import urlsplit, unquote
from bs4 import BeautifulSoup


GENERAL_SOURCES=(
    {'name':'Mynet Haber','url':'https://www.mynet.com/haber/'},
    {'name':'Investing.com Türkçe','url':'https://tr.investing.com/news/'},
    {'name':'Anadolu Ajansı','url':'https://www.aa.com.tr/tr/gundem'},
    {'name':'BBC Türkçe','url':'https://www.bbc.com/turkce'},
    {'name':'İhlas Haber Ajansı','url':'https://www.iha.com.tr/'},
    {'name':'Demirören Haber Ajansı','url':'https://www.dha.com.tr/'},
    {'name':'ANKA Haber Ajansı','url':'https://ankahaber.net/'},
    {'name':'Türk Haberler Ajansı','url':'https://tha.istanbul/'},
    {'name':'İlke Haber Ajansı','url':'https://ilkha.com/'},
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

# Compatibility export for security tests and callers; it is discovery data only.
SOURCES = GENERAL_SOURCES


def _ai_request(request):
    return bool(re.search(r'yapay\s+zek|artificial\s+intelligence|\bai\b|makine\s+öğren|makine\s+ogren|machine\s+learning',str(request or ''),re.I))


def _ai_rows():
    """Genel haber tabanı korunur; gerçek AI/teknoloji yayıncıları okuma bütçesine alınır."""
    baseline=list(GENERAL_SOURCES[:4])
    preferred_names=('DonanımHaber','Webtekno')
    by_name={row['name']:row for row in GENERAL_SOURCES}
    rows=baseline+[by_name[name] for name in preferred_names if name in by_name]
    seen={row['url'] for row in rows}
    rows.extend(row for row in GENERAL_SOURCES if row['url'] not in seen)
    return rows


def sources_for(request=None):
    """Configured news indexes only; official/statistical primary evidence is not a news feed."""
    rows=_ai_rows() if _ai_request(request) else list(GENERAL_SOURCES)
    return [dict(row,scope=row.get('scope','Genel ve konu odaklı haber keşfi'),
                 live_connection_tested=False) for row in rows]


def publisher_key(url):
    labels=(urlsplit(url).hostname or '').removeprefix('www.').split('.')
    return '.'.join(labels[-3:] if '.'.join(labels[-2:]) in {'edu.tr','gov.tr','com.tr','org.tr'} else labels[-2:])




def broad_research(request):
    return bool(re.search(r'türkiye|turkiye|üniversitelerin|universitelerin',request,re.I) and
               not re.search(r'https://|sadece|yalnız|yalniz|tek (?:haber|kaynak)|bir haber|üniversitesi|universitesi|bakanlığı|bakanligi|ofisi|sanayi|cumhurbaşkan|cumhurbaskan',request,re.I))



def candidate_url(url,request,outputs):
    """Model guesses are not news links: require user, catalog or actual discovery provenance."""
    from modules.public_sources import address
    candidate=address(url)
    allowed={address(s['url']) for s in GENERAL_SOURCES}
    for raw in re.findall(r'https://[^\s<>"\]]+',request):
        try:allowed.add(address(raw.rstrip('.,;)')))
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
    selector='a[href*="/tr/haber_oku/"]' if host=='haber.dpu.edu.tr' else None
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
    if parsed.hostname in {'www.iha.com.tr','iha.com.tr','ilkha.com'}:
        return _agency_article(response,url,parsed.hostname)
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



def _agency_article(response,url,host):
    from modules import public_sources
    from urllib.parse import parse_qs
    soup=BeautifulSoup(response['body'],'html.parser')
    if host in {'www.iha.com.tr','iha.com.tr'}:
        nodes=soup.select('.widget_General_News_Detail')
        canon=soup.select('link[rel="canonical"]')
        if len(canon)!=1 or public_sources.address(canon[0].get('href',''))!=url:
            raise ValueError('İHA canonical kimliği eşleşmedi.')
        if len(nodes)!=1:raise ValueError('İHA tekil haber kapsayıcısı bulunamadı.')
        node=nodes[0];titles=node.select('h1');bodies=node.select('.news-detail__content')
        dates=[n.get_text(' ',strip=True).lstrip('- ').strip() for n in node.find_all('span')
               if re.fullmatch(r'\s*-?\s*\d{1,2}\s+[\wÇĞİÖŞÜçğıöşü]+\s+\d{4}\s+[\wÇĞİÖŞÜçğıöşü]+\s+\d{2}:\d{2}\s*',n.get_text(' ',strip=True))
               and not n.find_parent('a')]
        if len(dates)!=1:raise ValueError('İHA makaleye ait tek yayın tarihi bulunamadı.')
        published=_published(dates[0])
    else:
        nodes=soup.select('.post-layout-top-content-3')
        if len(nodes)!=1:raise ValueError('İLKHA tekil haber kapsayıcısı bulunamadı.')
        node=nodes[0];titles=node.select('.post-content > h3.title');bodies=node.select('.post-text')
        dates=node.select('.post-categories .author-social > li.cat-red')
        refs=[parse_qs(urlsplit(a.get('href','')).query).get('url',[]) for a in node.select('a[href]')
              if urlsplit(a.get('href','')).hostname=='twitter.com']
        if refs!=[[url]]:raise ValueError('İLKHA makale bağlantısı eşleşmedi.')
        if len(dates)!=1:raise ValueError('İLKHA makaleye ait tek yayın tarihi bulunamadı.')
        stamp=dates[0].get_text(' ',strip=True)
        m=re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{4}) \d{2}:\d{2}:\d{2}',stamp)
        if not m:raise ValueError('İLKHA yayın tarihi biçimi doğrulanamadı.')
        published=date(int(m[3]),int(m[2]),int(m[1])).isoformat()
    # Explicit conflicting page identity cannot be rescued by a share link.
    if host=='ilkha.com':
        for meta in soup.select('meta[property="og:url"]'):
            ref=meta.get('content','')
            # This CMS emits an unusable System.String[] path; do not treat it
            # as identity. Other explicit addresses must agree with the receipt.
            if '/System.String[]/' not in ref and public_sources.address(ref)!=url:
                raise ValueError('İLKHA sayfa kimliği çelişiyor.')
    if len(titles)!=1 or len(bodies)!=1:raise ValueError('Ajans tekil başlık/gövde bulunamadı.')
    title=titles[0].get_text(' ',strip=True)
    text=public_sources.readable_text(bodies[0])
    if not title or len(text)<80:raise ValueError('Ajans haber metni yetersiz.')
    return {'url':url,'title':title,'published':published,'text':text}
