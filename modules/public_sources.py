"""Bounded public HTTPS reads. Source text is data, never executable instructions."""
from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl
import xml.etree.ElementTree as ET

MAX_BYTES = 1_000_000


def address(url, *, resolve=False):
    if not isinstance(url,str) or len(url)>2048 or any(ord(c)<32 for c in url):
        raise ValueError('Kaynak adresi geçersiz.')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Kaynak yalnız şifresiz, standart HTTPS adresi olabilir.')
    host=parsed.hostname.encode('idna').decode('ascii').lower().rstrip('.')
    if host=='localhost' or host.endswith(('.localhost','.local','.internal')):
        raise ValueError('Yerel/ağ içi kaynak kullanılamaz.')
    if any(re.search(r'key|token|secret|password|signature|credential|auth',key,re.I) for key,_ in parse_qsl(parsed.query)):
        raise ValueError('Kaynak adresinde kimlik bilgisi saklanamaz.')
    try:
        if not ipaddress.ip_address(host).is_global:raise ValueError('Kaynak genel internette olmalı.')
    except ValueError as exc:
        if ':' in host or re.fullmatch(r'[\d.]+',host):raise ValueError('Kaynak genel internette olmalı.') from exc
    if resolve:
        records=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        if not records or any(not ipaddress.ip_address(row[4][0]).is_global for row in records):
            raise ValueError('Kaynak genel internette olmalı.')
    return urlunsplit(('https','['+host+']' if ':' in host else host,parsed.path or '/',parsed.query,''))


def fetch(url, *, max_bytes=MAX_BYTES):
    """No credentials, cookies, POSTs, automatic redirects or unbounded responses."""
    import urllib3
    import certifi
    from modules import privacy,requests_state
    if blocked:=privacy.blocked('web'):raise PermissionError(blocked)
    requests_state.check();deadline=time.monotonic()+20
    for _ in range(4):
        url=address(url)
        parsed=urlsplit(url);host=parsed.hostname
        records=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        if not records or any(not ipaddress.ip_address(row[4][0]).is_global for row in records):
            raise ValueError('Kaynak genel internette olmalı.')
        requests_state.check()
        pool=urllib3.HTTPSConnectionPool(records[0][4][0],port=443,assert_hostname=host,
              server_hostname=host,cert_reqs='CERT_REQUIRED',ca_certs=certifi.where(),maxsize=1)
        response=None
        try:
            response=pool.urlopen('GET',urlunsplit(('','',parsed.path or '/',parsed.query,'')),
                headers={'Host':'['+host+']' if ':' in host else host,'User-Agent':'Jarvis/2 public-source-reader',
                         'Accept':'application/json, application/rss+xml, application/atom+xml, text/html, text/plain'},
                timeout=urllib3.Timeout(connect=5,read=8,total=max(.1,deadline-time.monotonic())),
                preload_content=False,redirect=False,retries=False)
            if response.status in (301,302,303,307,308):
                location=response.headers.get('Location')
                if not location:raise ValueError('Kaynak yönlendirmesi adres içermiyor.')
                url=address(urljoin(url,location));continue
            if response.status<200 or response.status>=300:raise ValueError('Kaynak HTTP yanıtı başarılı değil: '+str(response.status))
            length=response.headers.get('Content-Length')
            if length and (not length.isdigit() or int(length)>max_bytes):raise ValueError('Kaynak yanıtı boyut sınırını aşıyor.')
            chunks=[];size=0
            while True:
                requests_state.check()
                if time.monotonic()>deadline:raise ValueError('Kaynak süre sınırını aşıyor.')
                block=response.read1(16384,decode_content=True)
                if not block:break
                size+=len(block)
                if size>max_bytes:raise ValueError('Kaynak boyut sınırını aşıyor.')
                chunks.append(block)
            return {'url':url,'body':b''.join(chunks),'content_type':response.headers.get('Content-Type','')}
        finally:
            if response is not None:response.close()
            pool.close()
    raise ValueError('Kaynak çok fazla yönlendirildi.')


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.links=[];self.parts=[];self.current=None;self.hidden=0;self.feeds=[]

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style','noscript','nav','footer','header'):self.hidden+=1
        if tag=='a' and not self.hidden:self.current={'url':attrs.get('href',''),'title':'','label':attrs.get('aria-label') or attrs.get('title',''),'alt':''}
        if tag=='img' and self.current and not self.hidden:self.current['alt']+=attrs.get('alt','')+' '
        if tag=='link' and attrs.get('type') in ('application/rss+xml','application/atom+xml'):
            self.feeds.append(attrs.get('href',''))

    def handle_endtag(self,tag):
        if tag=='a' and self.current:
            self.links.append({'url':self.current['url'],'title':self.current['title'].strip() or self.current['label'] or self.current['alt']});self.current=None
        if tag in ('script','style','noscript','nav','footer','header') and self.hidden:self.hidden-=1

    def handle_data(self,data):
        if self.hidden:return
        self.parts.append(data)
        if self.current:self.current['title']+=data+' '


def text(body):
    page=Page();page.feed(body.decode('utf-8',errors='replace'))
    return re.sub(r'\s+',' ',' '.join(page.parts)).strip()[:20000]


def feeds(response):
    """Only same-host RSS/Atom endpoints explicitly advertised by the fetched page."""
    url=address(response['url']);host=urlsplit(url).hostname
    page=Page();page.feed(response['body'].decode('utf-8',errors='replace'))
    result=[]
    for link in page.feeds:
        try:target=address(urljoin(url,link))
        except ValueError:continue
        if urlsplit(target).hostname==host and target!=url and target not in result:result.append(target)
        if len(result)>=2:break
    return result


def entries(response):
    """RSS/Atom or same-origin HTML article links, without fetching linked pages."""
    body=response['body'];url=address(response['url']);host=urlsplit(url).hostname
    if len(body)>MAX_BYTES:raise ValueError('Kaynak fazla büyük.')
    if re.search(br'<!\s*ENTITY\b',body,re.I) or (re.search(br'<!\s*DOCTYPE\b',body,re.I) and
            not re.search(br'<!DOCTYPE\s+html\s*>',body,re.I)):
        raise ValueError('XML varlık bildirimleri kabul edilmez.')
    result=[]
    try:root=ET.fromstring(body)
    except ET.ParseError:root=None
    if root is not None and root.tag.rsplit('}',1)[-1] in ('rss','feed','RDF'):
        for item in root.iter():
            if item.tag.rsplit('}',1)[-1] not in ('item','entry'):continue
            fields={child.tag.rsplit('}',1)[-1]:child for child in item}
            def value(*names):
                return next((' '.join(fields[n].itertext()).strip() for n in names if n in fields),'')
            link=fields.get('link');target=(link.get('href') or ''.join(link.itertext())) if link is not None else ''
            result.append({'url':target,'title':value('title'),'summary':value('description','summary','content')[:4000],
                           'published':value('pubDate','published','updated')[:100]})
            if len(result)>=100:break
    else:
        page=Page();page.feed(body.decode('utf-8',errors='replace'))
        result=[{**row,'summary':'','published':''} for row in page.links if len(row['title'].strip())>=8]
    clean=[];seen=set()
    for row in result:
        try:target=address(urljoin(url,row['url']))
        except ValueError:continue
        if urlsplit(target).hostname!=host or target==url or target in seen:continue
        title=re.sub(r'\s+',' ',row['title']).strip()[:400]
        if not title:continue
        seen.add(target);clean.append({**row,'url':target,'title':title})
        if len(clean)>=50:break
    return clean
