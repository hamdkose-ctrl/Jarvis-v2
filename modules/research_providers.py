"""Provider-neutral, read-only research contracts for Phase 4A.

Search and extraction are deliberately separate. Provider adapters only build
validated request descriptions; the runtime injects the network transport and
keeps credentials outside model/context payloads.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, quote_plus, urlsplit

from modules import public_sources
from modules.diagnostics import record_failure as _record_failure

_SEARCH_PROVIDERS = frozenset({"searxng", "duckduckgo", "tavily", "exa", "arxiv"})
_EXTRACTORS = frozenset({"firecrawl", "public_sources"})


def _query(query: str) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("Araştırma sorgusu geçersiz.")
    return query.strip()


def _limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Araştırma sonuç sınırı 1–50 olmalı.")
    return limit


def search_request(query: str, *, provider: str = "searxng", limit: int = 10) -> dict:
    """Build a provider request without executing a network call or exposing keys."""
    query = _query(query)
    limit = _limit(limit)
    if provider not in _SEARCH_PROVIDERS:
        raise ValueError("Arama sağlayıcısı desteklenmiyor.")
    if provider == "searxng":
        return {"provider": provider, "operation": "search", "method": "GET", "path": "/search", "params": {"q": query, "format": "json", "pageno": 1, "limit": limit}}
    if provider == "duckduckgo":
        return {"provider": provider, "operation": "search", "method": "GET", "path": "/html/", "params": {"q": query, "kl": "tr-tr", "limit": limit}}
    if provider == "tavily":
        return {"provider": provider, "operation": "search", "method": "POST", "path": "/search", "json": {"query": query, "max_results": limit, "include_answer": False}}
    if provider == "exa":
        return {"provider": provider, "operation": "search", "method": "POST", "path": "/search", "json": {"query": query, "numResults": limit, "contents": {"text": {"maxCharacters": 4000}}}}
    return {"provider": provider, "operation": "search", "method": "GET", "path": "/api/query", "params": {"search_query": query, "start": 0, "max_results": limit}}



def _duckduckgo_transport(request: dict) -> dict:
    """Read bounded DuckDuckGo HTML and expose only public result URLs."""
    if not isinstance(request, dict) or request.get("provider") != "duckduckgo":
        raise ValueError("Salt-okunur arama taşıyıcısı geçersiz.")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    query = _query(params.get("q"))
    limit = _limit(params.get("limit"))
    response = public_sources.fetch(
        "https://html.duckduckgo.com/html/?q=" + quote_plus(query) + "&kl=tr-tr"
    )
    from bs4 import BeautifulSoup
    page = BeautifulSoup(response["body"].decode("utf-8", errors="replace"), "html.parser")
    # A challenge/error document is not a valid empty search result.
    if page.select('form[action*="anomaly"], #challenge-form, .anomaly-modal'):
        raise ValueError('public_search_blocked: DuckDuckGo doğrulama/engel sayfası döndürdü.')
    results = []
    for link in page.select("a.result__a"):
        href = str(link.get("href") or "").strip()
        title = link.get_text(" ", strip=True)
        if href.startswith("//"):
            href = "https:" + href
        parsed = urlsplit(href)
        if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            href = (parse_qs(parsed.query).get("uddg") or [""])[0]
        try:
            target = public_sources.address(href)
        except ValueError:
            continue
        if not title or any(row["url"] == target for row in results):
            continue
        results.append({"url": target, "title": title[:400], "snippet": ""})
        if len(results) >= limit:
            break
    if not results and not page.select('.no-results, .no-results__message'):
        raise ValueError('public_search_unrecognized: Arama yanıtında sonuç veya açık sonuç-yok işareti bulunamadı.')
    return {"results": results}


def search_public(query: str) -> list[dict]:
    """Search one keyless public provider through the bounded HTTPS reader."""
    return search_all(query, providers=("duckduckgo",), transport=_duckduckgo_transport)

# --- arXiv (anahtarsız, resmî Atom API) -------------------------------------
_ACADEMIC_HINT = re.compile(
    '(?:^|[^0-9A-Za-zÇĞİÖŞÜçğıöşü])(makale[a-zçğıöşü]*|akademik|paper[a-z]*|arxiv|bilimsel|tez[a-z]*|çalışma|calisma|literatür|literatur)(?:[^0-9A-Za-zÇĞİÖŞÜçğıöşü]|$)', re.I)


def academic_requested(text: str) -> bool:
    """Metin akademik kaynak istiyor mu? (Yalnız kaynak türü seçimi; yetki değil.)"""
    return bool(_ACADEMIC_HINT.search(text or ''))


def _arxiv_transport(request: dict) -> dict:
    """arXiv Atom akışını oku; yalnız herkese açık başlık/özet/URL döndür."""
    if not isinstance(request, dict) or request.get("provider") != "arxiv":
        raise ValueError("arXiv taşıyıcısı geçersiz.")
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    query = _query(params.get("search_query", "").removeprefix("all:"))
    limit = _limit(params.get("max_results"))
    response = public_sources.fetch(
        "https://export.arxiv.org/api/query?search_query=all:"
        + quote(query) + "&start=0&max_results=" + str(limit)
        + "&sortBy=relevance&sortOrder=descending"
    )
    import xml.etree.ElementTree as ET
    atom = "{http://www.w3.org/2005/Atom}"
    body = response.get("body")
    if isinstance(body, str):
        body = body.encode("utf-8")  # ET, kodlama bildirimli str kabul etmez.
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, TypeError) as exc:
        raise ValueError("arxiv_unrecognized: arXiv yanıtı okunamadı.") from exc
    rows = []
    for entry in root.findall(atom + "entry"):
        title = " ".join((entry.findtext(atom + "title") or "").split())
        summary = " ".join((entry.findtext(atom + "summary") or "").split())
        url = (entry.findtext(atom + "id") or "").strip()
        # arXiv <id> alanı http:// ile gelir; arXiv https sunar, adres okuyucu
        # yalnız standart HTTPS kabul ettiği için şema yükseltilir.
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        published = (entry.findtext(atom + "published") or "")[:10]
        try:
            target = public_sources.address(url)
        except ValueError:
            continue
        if not title:
            continue
        rows.append({"provider": "arxiv", "url": target, "title": title[:400],
                     "snippet": summary[:600], "source_kind": "academic",
                     "published": published, "verified": False})
        if len(rows) >= limit:
            break
    if not rows:
        raise ValueError("arxiv_empty: Bu sorgu için arXiv sonucu bulunamadı.")
    return {"results": rows}


def search_academic(query: str, *, limit: int = 5) -> list[dict]:
    """arXiv'te anahtarsız arama; hata durumunda boş liste (tur düşmez)."""
    try:
        request = search_request(query, provider="arxiv", limit=limit)
        return _arxiv_transport(request)["results"][:limit]
    except ValueError:
        return []
    except Exception:
        _record_failure("modules/research_providers.py:arxiv")
        return []


# --- Türkçe akademik kaynak: Crossref (anahtarsız açık API) --------------------
# Kullanıcı kararı (22 Kasım 2026): "arXiv İngilizce, ben ne anlarım" + DergiPark /
# Google Akademik / Akademist adresleri verildi. Ölçüm: DergiPark araması bot
# doğrulamasına düşüyor, Google Akademik otomatik erişimi yasaklıyor, Akademist'in
# arama akışı yalnız statik sayfa döndürüyor. DergiPark makalelerinin DOI'si
# Crossref'te olduğu için Türkçe akademik kaynak **Crossref açık API'sinden** gelir.
_TOC_LIKE = re.compile(
    r'^(?:icindekiler|contents|onsoz|sunus|kisaltmalar|tablolar listesi|sekiller listesi)'
    r'(?![0-9a-z])', re.I | re.ASCII)


_TR_FOLD = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')


def _published_key(published) -> int:
    """Tarihi sıralanabilir sayıya çevirir (YYYYMMDD); eksik tarih 0 sayılır."""
    text = str(published or '').strip()
    parts = text.split('-')
    if not parts or not parts[0].isdigit() or len(parts[0]) != 4:
        return 0
    day = parts[0]
    month = parts[1] if len(parts) > 1 and parts[1].isdigit() else '01'
    rest = parts[2] if len(parts) > 2 and parts[2].isdigit() else '01'
    return int(day) * 10000 + int(month) * 100 + int(rest)


def turkish_text(value: str) -> bool:
    """Metin Türkçe mi? (Türkçe harf veya yaygın Türkçe sözcük.)"""
    text = str(value or '')
    return any(ch in text for ch in 'çğıöşüÇĞİÖŞÜ')


def _crossref_transport(request: dict) -> dict:
    response = public_sources.fetch(request['url'], max_bytes=1_500_000)
    try:
        payload = json.loads(response['body'])
    except ValueError:
        raise ValueError('Crossref yanıtı JSON değil.') from None
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        raise ValueError('Crossref yanıtı başarısız.')
    items = ((payload.get('message') or {}).get('items')) or []
    if not isinstance(items, list):
        raise ValueError('Crossref sonuç listesi geçersiz.')
    terms = [term.translate(_TR_FOLD).casefold()
             for term in re.split(r'\s+', str(request['query'])) if len(term) >= 3]
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        titles = item.get('title') or []
        title = ' '.join(str(titles[0]).split()) if isinstance(titles, list) and titles else ''
        doi = str(item.get('DOI') or '').strip()
        if not title or not doi or not re.fullmatch(r'10\.[^\s]{3,200}', doi):
            continue
        abstract = re.sub(r'<[^>]+>', ' ', str(item.get('abstract') or ''))
        abstract = ' '.join(abstract.split())[:600]
        # İçindekiler/ön söz kayıtları makale değildir (canlı: "Mutfakta Yapay Zeka"
        # kitabının içindekiler sayfası 1. sırada geldi).
        # Türkçe büyük harf katlanır (İ -> i), sonra ASCII desenle bakılır.
        if _TOC_LIKE.match(abstract.translate(_TR_FOLD).lower()):
            continue
        # Alakasız kayıt gelmesin: sorgu terimlerinden biri başlıkta/özetinde geçmeli.
        blob = (title + ' ' + abstract).translate(_TR_FOLD).casefold()
        if terms and not any(term in blob for term in terms):
            continue
        issued = ((item.get('issued') or {}).get('date-parts') or [[None]])[0]
        published = '-'.join(f'{int(part):02d}' if index else str(int(part))
                             for index, part in enumerate(issued) if isinstance(part, int)) if issued else ''
        journal = ''
        containers = item.get('container-title') or []
        if isinstance(containers, list) and containers:
            journal = ' '.join(str(containers[0]).split())[:120]
        rank = 0 if any(term in title.translate(_TR_FOLD).casefold() for term in terms) else 1
        results.append({'rank': rank, 'provider': 'crossref', 'url': 'https://doi.org/' + doi,
                        'title': title[:400], 'snippet': abstract, 'published': published[:10],
                        'journal': journal,
                        'language': 'tr' if (item.get('language') == 'tr' or turkish_text(title)) else 'en'})
        if len(results) >= request['limit'] * 4:
            break
    # Başlığında arama terimi geçenler önce; yalnız özette geçenler yalnız yer doldurmak
    # için arkadan eklenir (kullanıcı: "konudan çok saçma yazılar var").
    # "Güncel" isteğinde en yeni kayıt önce gelsin: isabet sınıfı, sonra tarih (yeniden eskiye).
    results.sort(key=lambda row: (row['rank'], -_published_key(row.get('published'))))
    sonuc = [row for row in results if row['rank'] == 0][:request['limit']]
    if len(sonuc) < request['limit']:
        sonuc += [row for row in results if row['rank'] == 1][:request['limit'] - len(sonuc)]
    for row in sonuc:
        row.pop('rank', None)
    return {'results': sonuc}


def search_turkish(query: str, *, limit: int = 5) -> list[dict]:
    """Türkçe akademik makale araması (Crossref açık API; DergiPark DOI'leri dahil).

    Hata durumunda boş liste döner; tur düşmez. Bot korumalı siteler kazınmaz.
    """
    try:
        query = _query(query)
        limit = _limit(limit)
        from urllib.parse import urlencode
        url = 'https://api.crossref.org/works?' + urlencode(
            {'query.bibliographic': query, 'rows': min(40, limit * 8)})
        return _crossref_transport({'url': url, 'query': query, 'limit': limit})['results'][:limit]
    except ValueError:
        return []
    except Exception:
        _record_failure('modules/research_providers.py:crossref')
        return []


def news_search_query(request: str) -> str:
    """Remove delivery/window instructions, preserving topical/geographic words.

    The original request remains the article verification/completion authority.
    """
    text=_query(request)
    text=re.sub(r'\bson\s+\d+\s+(?:gün|gun|hafta|ay|saat)\b',' ',text,flags=re.I)
    text=re.sub(r'\b(?:haber|haberler|haberleri|haberlerini|güncel|guncel|araştır|arastir|araştırın|arastirin|ara|rapor|raporu|dosya|dosyası|dosyasi|dosyaya|kaydet|oluştur|olustur|özetle|ozetle|ve)\b',' ',text,flags=re.I)
    # Output language is an instruction only when explicitly tied to a report.
    if re.search(r'\b(?:rapor|raporu|dosya|dosyası|dosyasi)\b',request,re.I):
        text=re.sub(r'\bTürkçe\b',' ',text,flags=re.I)
    text=re.sub(r'\b(?:son\s+dakika|bu\s+sabah|bugün|bugun)\b',' ',text,flags=re.I)
    text=re.sub(r'\s+',' ',text).strip(' ,;:')
    return text or 'güncel haberler'


def search_news_public(query: str) -> list[dict]:
    """News-only keyless fallback; one attempt per service, no model calls."""
    from modules import requests_state
    from modules import research_evidence
    window=research_evidence.news_window(query)
    query=news_search_query(query)
    requests_state.check()
    try:
        primary=search_public(query)
        if primary:return primary
    except (PermissionError,requests_state.Cancelled):
        raise
    except Exception:
        _record_failure('modules/research_providers.py:news_primary_search')
        requests_state.check()
    # Bing's time-range hint improves discovery only. Article dates still decide.
    recency=('&qft='+quote_plus('interval="'+('7' if window<=1 else '8')+'"')
             if window is not None and window<=7 else '')
    response=public_sources.fetch('https://www.bing.com/news/search?q='+quote_plus(query)+
                                  '&format=rss&setmkt=tr-TR&sortbydate=1'+recency)
    import xml.etree.ElementTree as ET
    body=response['body']
    if len(body)>public_sources.MAX_BYTES or re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b',body,re.I):
        raise ValueError('public_news_rss_invalid: RSS boyut/varlık bildirimi reddedildi.')
    root=ET.fromstring(body)
    if root.tag!='rss' or root.find('channel') is None:
        raise ValueError('public_news_rss_invalid: RSS haber kanalı bulunamadı.')
    from email.utils import parsedate_to_datetime
    from datetime import datetime,timezone,timedelta
    today=datetime.now(timezone(timedelta(hours=3))).date()
    results=[];seen=set()
    for item in root.findall('./channel/item')[:50]:
        # RSS dates guide discovery only; missing/invalid dates do not prove age.
        if window is not None:
            try:
                stamp=parsedate_to_datetime(item.findtext('pubDate') or '')
                if stamp.tzinfo is not None and (today-stamp.astimezone(timezone(timedelta(hours=3))).date()).days>window:
                    continue
            except (ValueError,TypeError,OverflowError):pass
        href=item.findtext('link') or '';parsed=urlsplit(href)
        if parsed.hostname=='www.bing.com' and parsed.path=='/news/apiclick.aspx':
            targets=parse_qs(parsed.query).get('url',[])
            if len(targets)!=1:continue
            href=targets[0]
        try:target=public_sources.address(href)
        except ValueError:continue
        if urlsplit(target).hostname in {'www.bing.com','bing.com'}:continue
        title=(item.findtext('title') or '').strip()
        if not title or target in seen:continue
        seen.add(target)
        results.append({'provider':'bing_news_rss','url':target,'title':title[:400],
                        'snippet':'','source_kind':'web','verified':False})
        if len(results)>=10:break
    if not results:
        raise ValueError('public_news_rss_empty: Bing RSS item='+str(len(root.findall('./channel/item')))+'; kullanılabilir yayıncı adresi=0')
    return results


def extract_request(url: str, *, provider: str = "public_sources") -> dict:
    """Build a separate extraction request; search results never imply article proof."""
    normalized = public_sources.address(url)
    if provider not in _EXTRACTORS:
        raise ValueError("İçerik çıkarma sağlayıcısı desteklenmiyor.")
    return {"provider": provider, "operation": "extract", "method": "POST" if provider == "firecrawl" else "GET", "url": normalized}


def extract_source(url: str, *, fetcher=None) -> dict:
    """Read one public source through the existing bounded HTTPS reader."""
    request = extract_request(url)
    if fetcher is None:
        # Preserve the existing browser reader's bounded, user-flow semantics.
        from modules.browser import page_text
        return {"url": request["url"], "text": page_text(request["url"]), "content_type": ""}
    response = fetcher(request["url"])
    if not isinstance(response, dict) or response.get("url") != request["url"] or not isinstance(response.get("body"), bytes):
        raise ValueError("Kaynak okuyucu geçerli yanıt üretmedi.")
    return {"url": request["url"], "text": public_sources.text(response["body"]), "content_type": response.get("content_type", "")}


def normalize_results(provider: str, payload: dict, *, limit: int = 10) -> list[dict]:
    """Normalize provider payloads into evidence candidates, not verified claims."""
    if provider not in _SEARCH_PROVIDERS or not isinstance(payload, dict):
        raise ValueError("Arama sağlayıcı yanıtı geçersiz.")
    limit = _limit(limit)
    rows = payload.get("results") or payload.get("items") or payload.get("organic_results") or []
    if not isinstance(rows, list):
        raise ValueError("Arama sonuç listesi geçersiz.")
    normalized = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        url = row.get("url") or row.get("link")
        title = row.get("title") or row.get("name")
        if not isinstance(url, str) or not isinstance(title, str) or not title.strip():
            continue
        normalized.append({"provider": provider, "title": title.strip()[:400], "url": url.strip(), "snippet": str(row.get("snippet") or row.get("text") or row.get("content") or "")[:4000], "source_kind": "academic" if provider == "arxiv" else "web", "verified": False})
    return normalized


def search_all(query: str, *, providers=("searxng", "duckduckgo", "tavily", "exa"), transport, limit: int = 10) -> list[dict]:
    """Run injected read-only provider transports and normalize their candidates."""
    query = _query(query)
    if not callable(transport):
        raise ValueError("Arama taşıyıcısı callable olmalı.")
    output = []
    for provider in providers:
        request = search_request(query, provider=provider, limit=limit)
        payload = transport(request)
        output.extend(normalize_results(provider, payload, limit=limit))
    return rank_results(output)[:limit]


def rank_results(results: list[dict], *, preferred_kinds=("official", "academic", "web")) -> list[dict]:
    if not isinstance(results, list):
        raise ValueError("Araştırma sonuçları liste olmalı.")
    preference = {kind: len(preferred_kinds) - index for index, kind in enumerate(preferred_kinds)}
    clean = [deepcopy(row) for row in results if isinstance(row, dict) and isinstance(row.get("url"), str) and isinstance(row.get("title"), str)]
    return sorted(clean, key=lambda row: (-preference.get(row.get("source_kind"), 0), -int(bool(row.get("verified"))), row["title"].casefold()))


def independent_candidates(candidates: list[dict], *, limit: int = 3) -> list[dict]:
    """Deterministic, host-distinct source selection bounded for a single research run.

    Keeps the ranked candidate order and takes at most one row per hostname up to ``limit``, so a
    normal research worker can gather a few independent sources for structured claims without ever
    becoming a broad crawl. Sources are never fabricated; empty/invalid rows are skipped.
    """
    if not isinstance(candidates, list) or type(limit) is not int or limit < 1:
        raise ValueError("Bağımsız aday listesi geçersiz.")
    chosen: list[dict] = []
    seen_hosts: set[str] = set()
    from modules import publisher_news
    for row in candidates:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        host = publisher_news.publisher_key(url)
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        chosen.append(deepcopy(row))
        if len(chosen) >= limit:
            break
    return chosen


_TRANSLATE = str.maketrans({'ç': 'c', 'Ç': 'c', 'ğ': 'g', 'Ğ': 'g', 'ı': 'i', 'İ': 'i',
                            'ö': 'o', 'Ö': 'o', 'ş': 's', 'Ş': 's', 'ü': 'u', 'Ü': 'u',
                            'â': 'a', 'î': 'i', 'û': 'u', 'é': 'e'})
_NUMBER = re.compile(r'\d+(?:[.,]\d+)?')


def _norm(text) -> str:
    """Casefolded, Turkish-folded, whitespace-collapsed text used for structural keys."""
    return ' '.join(str(text or '').translate(_TRANSLATE).casefold().split())


def _token(text) -> str:
    core = re.sub(r'[^0-9a-z ]+', ' ', _norm(text))
    return ' '.join(core.split())


def _numbers(text) -> list[str]:
    out = []
    for match in _NUMBER.finditer(str(text or '')):
        raw = match.group(0).replace(',', '.')
        try:
            value = float(raw)
        except ValueError:
            continue
        out.append(f'{value:g}')
    return out


def _canon_value(value) -> tuple[str, str]:
    if isinstance(value, bool):
        return 'token', str(value).lower()
    if isinstance(value, (int, float)):
        return 'num', f'{float(value):g}'
    token = _token(value)
    numbers = _numbers(token)
    if numbers and numbers[0] == token:
        return 'num', numbers[0]
    return 'token', token


def _row_key(row: dict) -> tuple[str, str, str]:
    """Comparable identity: same subject AND same scope AND same reference time."""
    subject = _norm(row.get('subject') or row.get('entity') or row.get('metric') or '')
    scope = _norm(row.get('scope') or '')
    as_of = _norm(row.get('as_of') or row.get('date') or '')
    return subject, scope, as_of


def _row_value(row: dict) -> tuple[str, str]:
    if row.get('value') is not None:
        return _canon_value(row['value'])
    text = _norm(row.get('claim') or row.get('text') or '')
    numbers = _numbers(text)
    if numbers:
        return 'num', numbers[0]
    return 'token', _token(text)


def _float_or_str(canon: str):
    try:
        return float(canon)
    except ValueError:
        return canon


def compare_sources(sources: list[dict]) -> dict:
    """Structural cross-source verdict: wording, time and scope differences are not contradictions.

    Two sources conflict only when they are comparable (same subject+scope+reference time) and carry
    different values. Free-text claims fall back to numeric+unit extraction before a token compare so
    'yüzde 10 arttı' vs 'yaklaşık %10 yükseldi' is agreement, while '%40' vs '%45' is a real conflict.
    """
    if not isinstance(sources, list) or not sources:
        raise ValueError("Karşılaştırılacak kaynak gerekli.")
    rows = [row for row in sources if isinstance(row, dict)]
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        if row.get('evidence') and (not row.get('scope') or not row.get('as_of')):
            continue
        key = _row_key(row)
        kind, canon = _row_value(row)
        groups.setdefault(key, []).append({'kind': kind, 'canon': canon, 'url': str(row.get('url', ''))})
    comparisons = []
    for key in sorted(groups):
        entries = groups[key]
        distinct = sorted({(entry['kind'], entry['canon']) for entry in entries})
        urls = sorted({entry['url'] for entry in entries if entry['url']})
        comparisons.append({'subject': key[0], 'scope': key[1], 'as_of': key[2],
                            'values': [canon for _kind, canon in distinct], 'urls': urls,
                            'conflict': len(distinct) > 1})
    has_claims = any(entries for entries in groups.values())
    status = 'conflict' if any(group['conflict'] for group in comparisons) else 'agreement' if has_claims else 'insufficient'
    distinct_values = {canon for group in comparisons for canon in group['values']}
    return {'status': status, 'reason': ('Kaynaklar aynı olgu için farklı değer taşıyor.' if status == 'conflict'
            else 'Kaynaklar çelişmiyor; farklı ifadeler aynı olguyu anlatıyor olabilir.' if status == 'agreement'
            else 'Karşılaştırılacak yapılandırılmış iddia yok.'),
            'sources': deepcopy(sources), 'claim_count': len(distinct_values),
            'needs_review': status == 'conflict', 'comparisons': comparisons}


def verify_conflict(query: str, comparison: dict, *, search, extract, read_value=None, max_extra: int = 1) -> dict:
    """Bounded extra verification for a genuine conflict, reusing the keyless search/extract flow.

    Reads at most ``max_extra`` independent sources. Resolves only when every independent source
    confirms the same single disputed value; otherwise leaves the conflict explicitly unresolved and
    never picks a side. No-op for non-conflict comparisons (agreement must not trigger any network).
    """
    base = deepcopy(comparison)
    if base.get('status') != 'conflict':
        return base
    if max_extra <= 0:
        return {**base,'status':'unresolved_conflict','needs_review':True,'supported':None,
                'verification':{'performed':False,'independent_sources':0,
                                'reason':'Ek doğrulama bütçesi yok; yeni arama veya okuma yapılmadı.'}}
    disputed = {canon for group in base.get('comparisons', []) if group.get('conflict') for canon in group['values']}
    reader = read_value or (lambda source: _numbers(_norm(source.get('text') if isinstance(source, dict) else '')))
    from modules import publisher_news, requests_state
    used = {publisher_news.publisher_key(row['url']) for row in base.get('sources', [])
            if isinstance(row, dict) and row.get('url')}
    candidates = []
    for row in search(query) or []:
        if not isinstance(row, dict) or not row.get('url'):
            continue
        key = publisher_news.publisher_key(row['url'])
        if not key or key in used:
            continue
        used.add(key)
        candidates.append(row)
        if len(candidates) >= max(0, max_extra):
            break
    if not candidates:
        return {**base, 'status': 'unresolved_conflict', 'needs_review': True, 'supported': None,
                'verification': {'performed': True, 'independent_sources': 0,
                                 'reason': 'Bağımsız ek kaynak bulunamadı; çelişki taraf seçilmeden açık bırakıldı.'}}
    votes: list[str] = []
    supporting: list[str] = []
    ambiguous = False
    for candidate in candidates:
        requests_state.check()
        try:
            source = extract(candidate['url'])
        except (requests_state.Cancelled, PermissionError):
            raise
        except Exception:
            _record_failure('modules/research_providers.py:verify_conflict_extract')
            ambiguous = True
            continue
        text = _norm(source.get('text', '') if isinstance(source, dict) else '')
        context = [group for group in base.get('comparisons', []) if group.get('conflict')]
        if read_value is None and any(
                field and _norm(field) not in text
                for group in context for field in (group.get('scope'), group.get('as_of'))):
            ambiguous = True
            continue
        hits = [canon for canon in (reader(source) or []) if canon in disputed]
        if len(set(hits)) != 1:
            ambiguous = True
            continue
        votes.append(hits[0])
        supporting.append(candidate['url'])
    if ambiguous or not votes or len(set(votes)) != 1 or len(disputed) != 2:
        return {**base, 'status': 'unresolved_conflict', 'needs_review': True, 'supported': None,
                'verification': {'performed': True, 'independent_sources': len(candidates),
                                 'reason': 'Ek doğrulama çelişkiyi kesinleştirmedi; tek taraf nihai gerçek olarak seçilmedi.'}}
    chosen = votes[0]
    return {**base, 'status': 'resolved_conflict', 'needs_review': False,
            'supported': {'value': _float_or_str(chosen), 'canon': chosen, 'urls': sorted(set(supporting))},
            'verification': {'performed': True, 'independent_sources': len(candidates),
                             'reason': 'Bağımsız kaynak çelişkili taraflardan birini doğruladı.'}}


def format_citation(result: dict, number: int) -> str:
    if not isinstance(result, dict) or type(number) is not int or number < 1:
        raise ValueError("Kaynak gösterimi geçersiz.")
    return f"[{number}] {result.get('title', 'Başlıksız')} — {result.get('url', '')}"


@dataclass
class ResearchContext:
    max_chars: int = 12000
    _items: list[dict] = field(default_factory=list)
    characters: int = 0

    def __post_init__(self):
        if type(self.max_chars) is not int or not 100 <= self.max_chars <= 200000:
            raise ValueError("Araştırma bağlam sınırı geçersiz.")

    def add(self, item: dict) -> None:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str) or not isinstance(item.get("text"), str):
            raise ValueError("Araştırma kanıtı geçersiz.")
        remaining = max(0, self.max_chars - self.characters)
        copy = deepcopy(item)
        copy["text"] = copy["text"][:remaining]
        if copy["text"]:
            self._items.append(copy)
            self.characters += len(copy["text"])

    def sources(self) -> list[str]:
        return [item["url"] for item in self._items]

    def items(self) -> list[dict]:
        return deepcopy(self._items)


def weekly_research_request(topic: str) -> dict:
    return {"query": _query(topic), "window_days": 7, "cadence": "weekly", "source_policy": "cite-and-compare"}

