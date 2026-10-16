"""Verified publisher layouts and direct discovery. No third-party search service."""
import re
from datetime import date
from urllib.parse import urlsplit, unquote
from bs4 import BeautifulSoup

SOURCES=(
    {'name':'Kütahya Dumlupınar Üniversitesi','url':'https://haber.dpu.edu.tr/'},
    {'name':'Yıldız Teknik Üniversitesi','url':'https://www.yildiz.edu.tr/medya/haberler'},
    {'name':'TÜBİTAK','url':'https://tubitak.gov.tr/tr/haberler'},
    {'name':'Boğaziçi Üniversitesi','url':'https://haberler.bogazici.edu.tr/'},
)


def recovery_indexes(request,seeds):
    """Broaden only the user's general Turkey/university research, not an exclusive source."""
    scoped=bool(re.search(r'sadece|yalnız|yalniz|\bonly\b|https://',request,re.I))
    # Existing source choices are authoritative; never replace one university with another.
    broad=bool(re.search(r'türkiye|turkiye|üniversitelerin|universitelerin|kaynakları sen|kaynaklari sen',request,re.I))
    named=bool(re.search(r'üniversitesi|universitesi|bakanlığı|bakanligi|ofisi|enstitüsü|enstitusu|tübitak|tubitak|boğaziçi|bogazici|dumlupınar|dumlupinar|yıldız|yildiz|sanayi|cumhurbaşkan|cumhurbaskan',request,re.I))
    if broad and not scoped and not named:
        # Failed planner guesses are not a reason to abandon the real publisher catalog.
        known=[s['url'] for s in SOURCES]
        preferred=[url for url in known if any((urlsplit(seed).hostname or '').removeprefix('www.')==
                    (urlsplit(url).hostname or '').removeprefix('www.') for seed in seeds)]
        return list(dict.fromkeys(preferred+known))[:4]
    defaults=[]
    return list(dict.fromkeys(defaults+seeds))[:4]


def broad_research(request):
    return bool(re.search(r'türkiye|turkiye|üniversitelerin|universitelerin',request,re.I) and
                not re.search(r'https://|sadece|yalnız|yalniz|tek (?:haber|kaynak)|bir haber|üniversitesi|universitesi|tübitak|tubitak|bakanlığı|bakanligi|ofisi|boğaziçi|bogazici|dumlupınar|dumlupinar|yıldız|yildiz|sanayi|cumhurbaşkan|cumhurbaskan',request,re.I))


def publisher_key(url):
    labels=(urlsplit(url).hostname or '').removeprefix('www.').split('.')
    return '.'.join(labels[-3:] if '.'.join(labels[-2:]) in {'edu.tr','gov.tr','com.tr','org.tr'} else labels[-2:])


def candidate_url(url,request,outputs):
    """Model guesses are not news links: require user, catalog or actual discovery provenance."""
    from modules.public_sources import address
    candidate=address(url)
    allowed={address(s['url']) for s in SOURCES}
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
