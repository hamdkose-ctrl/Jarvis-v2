"""Model-bağımsız haber hattı: keşif → kaynak sağlığı → süzme → kümeleme → doğrulama → deterministik teslim.

Bu modül yeni bir sağlayıcı, arama servisi veya model yolu kurmaz. Haber bulma, doğrulama ve
teslim etme yeteneği Gemini/Groq/Ollama varlığına bağlı değildir; model yalnız son sentez
katmanında kullanılır ve yoksa deterministik rapor üretilir. Başlık benzerliği hiçbir zaman
claim anlaşması sayılmaz; doğrulama mevcut tekil makale okuyucusundan gelir.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import re
import threading
import time
from urllib.parse import urlsplit

from modules import publisher_news, public_sources, research_evidence, research_providers
from modules.diagnostics import record_failure as _record_failure

# Article reader and independent-host selection are the existing authorities, not re-implementations.
article_reader = research_evidence.article
independent = research_providers.independent_candidates

CACHE_SECONDS = 600
DEFAULT_WINDOW = 7
MAX_WINDOW = 90
MAX_SOURCES = 8
# A user news request may inspect the whole configured discovery pool; utility probes stay bounded.
BROAD_MAX_SOURCES = 20
MAX_ITEMS_PER_SOURCE = 12
MAX_WORKERS = 8
SOURCE_SECONDS = 4
MIN_VERIFIED = 2
# Page reads are bounded per run: the budget is read count, never a longer timeout.
MAX_ARTICLE_READS = 36

UNKNOWN = 'bilinmeyen'
CATEGORIES = ('gündem', 'ekonomi', 'teknoloji', 'bilim', 'dünya', 'sağlık', 'spor', 'kültür/sanat')
_CATEGORY_WORDS = {
    'spor': ('spor', 'futbol', 'voleybol', 'basketbol', 'maç', 'takım', 'teknik direktör', 'olimpik',
             'saha', 'lig', 'puan', 'şampiyon', 'fenerbahçe', 'galatasaray', 'beşiktaş', 'trabzonspor'),
    'ekonomi': ('ekonomi', 'faiz', 'enflasyon', 'borsa', 'dolar', 'euro', 'banka', 'bütçe', 'ihracat', 'sanayi'),
    'teknoloji': ('teknoloji', 'yapay zek', 'yapay zeka', 'bilgisayar', 'telefon', 'uygulama', 'yazilim', 'yazılım',
                 'internet', 'robot', 'çip', 'chip', 'ai'),
    'bilim': ('bilim', 'uzay', 'teleskop', 'galaksi', 'astronomi', 'araştırma laboratuvar', 'arkeoloji'),
    'sağlık': ('sağlık', 'hastane', 'vaka', 'salgın', 'ilaç', 'doktor', 'hasta', 'aşı'),
    'dünya': ('dünya', 'parlamento', 'dış politika', 'abd', 'avrupa birliği', 'otan', 'savaş', 'seçim'),
    'kültür/sanat': ('kültür', 'sanat', 'tiyatro', 'sergi', 'konser', 'sinema', 'festival', 'müze', 'kitap'),
    'gündem': ('gündem', 'deprem', 'valilik', 'kaymakamlık', 'belediye', 'cumhuriyet başsavcılığı'),
}
# Explicit user wording that names a category, used for "sadece X" / "X yok" filters.
_CATEGORY_ALIASES = {
    'gündem': ('gündem', 'gundem'),
    'ekonomi': ('ekonomi', 'finans', 'para'),
    'teknoloji': ('teknoloji', 'yapay zek', 'yapay zeka', 'bilişim', 'digital', 'dijital', 'ai'),
    'bilim': ('bilim', 'uzay'),
    'dünya': ('dünya', 'dış haber', 'dis haber'),
    'sağlık': ('sağlık', 'salgın'),
    'spor': ('spor', 'futbol'),
    'kültür/sanat': ('kültür', 'sanat'),
}

_lock = threading.Lock()
_CACHE: dict[tuple, tuple[float, list[dict]]] = {}


def cache_clear() -> None:
    with _lock:
        _CACHE.clear()


def cached_urls() -> list[str]:
    with _lock:
        return sorted({key[1] for key in _CACHE})


def _fold(value) -> str:
    return ' '.join(str(value or '').casefold().replace('ı', 'i').replace('\u0307', '').split())


def catalog(request=None) -> list[dict]:
    """Configured publisher indexes only; a catalog row is never live-access evidence."""
    return publisher_news.sources_for(request)


def headline_reader(owner, query=None):
    """The existing single-index read, as a per-source callable for the pipeline."""
    from modules import domain_tools

    def read(url):
        kwargs = {'query': query[:300]} if query else {}
        return domain_tools.headlines(owner, url, **kwargs)['items']

    return read


def source_name(url) -> str:
    known = {row['url']: row['name'] for row in publisher_news.GENERAL_SOURCES}
    if url in known:
        return known[url]
    return (urlsplit(url).hostname or str(url)).removeprefix('www.')


def parse_date(value):
    """Feed dates only; an absent date is never filled with the current time."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()[:100]
    match = re.match(r'^(\d{4}-\d{2}-\d{2})', text)
    if match:
        try:
            return date.fromisoformat(match[1])
        except ValueError:
            return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is not None:
        return parsed.date()
    months = {'ocak': 1, 'şubat': 2, 'mart': 3, 'nisan': 4, 'mayıs': 5, 'haziran': 6, 'temmuz': 7,
              'ağustos': 8, 'eylül': 9, 'ekim': 10, 'kasım': 11, 'aralık': 12}
    match = re.match(r'^(\d{1,2})\s+([\wÇĞİÖŞÜçğıöşü]+)\s+(\d{4})', text)
    if match and match[2].casefold() in months:
        try:
            return date(int(match[3]), months[match[2].casefold()], int(match[1]))
        except ValueError:
            return None
    return None


def window_days(request, *, default=DEFAULT_WINDOW) -> int:
    """Last seven days unless the user explicitly asked for a wider window; never more than 90."""
    try:
        requested = research_evidence.news_window(request)
    except (TypeError, ValueError):
        requested = None
    if requested is None:
        return default
    return max(1, min(MAX_WINDOW, int(requested)))


def category_of(*values) -> str:
    text = ' '.join(_fold(value) for value in values if isinstance(value, str))
    for category, words in _CATEGORY_WORDS.items():
        if any(_fold(word) in text for word in words if _fold(word)):
            return category
    return UNKNOWN


def normalize(row, *, source, now=None) -> dict:
    """One discovery candidate with explicit date status; unknown category never discards a row."""
    url = str(row.get('url') or '')
    published = parse_date(row.get('published'))
    today = now or _today()
    title = ' '.join(str(row.get('title') or '').split())[:400]
    summary = ' '.join(str(row.get('summary') or '').split())[:4000]
    explicit = row.get('category')
    return {
        'url': url,
        'title': title,
        'summary': summary,
        'source': source,
        'published_at': published.isoformat() if published else None,
        'date_status': 'present' if published else 'missing',
        'age_days': (today - published).days if published else None,
        'category': _fold(explicit) if isinstance(explicit, str) and _fold(explicit) in CATEGORIES
                    else category_of(summary, title),
        'verification': 'discovery_only',
    }


def requested_filter(request) -> tuple[set[str], set[str]]:
    """Deterministic include/exclude sets from the user's own words; no model involved."""
    text = _fold(request)
    only: set[str] = set()
    exclude: set[str] = set()
    for category, aliases in _CATEGORY_ALIASES.items():
        if re.search(r'(sadece|yalnız|yalniz|only)\s+[\w\s/]{0,20}' + re.escape(_fold(aliases[0])), text):
            only.add(category)
        if re.search(re.escape(_fold(aliases[0])) + r'[\w\s/]{0,12}(yok|olmasın|olmasin|hariç|haric|istemiyorum)', text):
            exclude.add(category)
    if only:
        exclude = set(CATEGORIES) - only
    return only, exclude


def filter_candidates(candidates, request) -> list[dict]:
    only, exclude = requested_filter(request)
    kept = [row for row in candidates if row['category'] not in exclude]
    if not kept and (only or exclude):
        # A filter that would leave the user with nothing is reported, not silently widened.
        return []
    return kept


def _terms(value) -> list[str]:
    stop = {'haberi', 'haberi', 'son', 'güncel', 'guncel', 'bugün', 'bugun', 'yeni', 'kaydedildi', 'açıkladı'}
    return [word for word in re.findall(r'[\wçğıöşü-]+', _fold(value)) if len(word) > 2 and word not in stop]


def cluster(candidates) -> list[dict]:
    """Candidate grouping only: same-event rows share an id and expose other_sources.

    Title overlap never means the claims agree; verification stays with the article reader and
    the existing #436 claim line. Grouping is deterministic over the input order.
    """
    rows = [dict(row) for row in candidates]
    for row in rows:
        row.setdefault('event_cluster_id', None)
        row.setdefault('other_sources', [])
    for index, row in enumerate(rows):
        if row['event_cluster_id']:
            continue
        group = [row]
        own = set(_terms(row['title']))
        for other in rows[index + 1:]:
            if other['event_cluster_id'] or other['url'] == row['url']:
                continue
            shared = set(_terms(other['title']))
            overlap = len(own & shared) / max(1, len(own | shared))
            if overlap < 0.5:
                continue
            if other['category'] != row['category'] and UNKNOWN not in (other['category'], row['category']):
                continue
            if not _near(row, other):
                continue
            group.append(other)
        if len(group) < 2:
            continue
        ident = hashlib.sha256('|'.join(sorted(item['url'] for item in group)).encode()).hexdigest()[:12]
        names = []
        for item in group:
            if item['source'] not in names:
                names.append(item['source'])
        for item in group:
            item['event_cluster_id'] = ident
            item['other_sources'] = [name for name in names if name != item['source']]
    return rows


def _near(left, right) -> bool:
    if not (left.get('published_at') and right.get('published_at')):
        return True
    gap = abs(date.fromisoformat(left['published_at']) - date.fromisoformat(right['published_at'])).total_seconds()
    return gap <= 48 * 3600


def _rotate(rows, slots, *, now=None):
    """Kalan kaynak yuvalarını saatlik döndürür; her kaynak eninde sonunda taranır."""
    if not rows or slots <= 0:
        return []
    if len(rows) <= slots:
        return list(rows)
    saat = int((now or time.time()) // 3600)
    offset = saat % len(rows)
    donen = list(rows[offset:]) + list(rows[:offset])
    return donen[:slots]


def discover(sources, *, reader=None, owner=None, query=None, now=None, max_sources=MAX_SOURCES) -> tuple[list[dict], list[dict]]:
    """Parallel per-source read with isolation: one dead index cannot drop the whole run.

    Results honour the bounded cache. A source that fails entirely is never cached, so an offline
    moment is not remembered as "no news".
    """
    from modules import requests_state
    default_reader = reader is None
    reader = reader or headline_reader(owner, query)
    rows = list(catalog(query) if sources is None else sources)
    if sources is None and len(rows) > max_sources:
        # Katalog tarama bütçesinden büyük: ilk dört kaynak (ajans/ana akış) her turda kalır,
        # kalan yuvalar saatlik döner. Yoksa sıranın sonundaki kaynaklar (DonanımHaber,
        # Webtekno gibi teknoloji indeksleri) hiç taranmıyordu (#439).
        rows = rows[:4] + _rotate(rows[4:], max_sources - 4)
    rows = rows[:max_sources]
    if not rows:
        return [], []
    today = now or _today()
    results: dict[str, tuple[list[dict], dict]] = {}

    def read(source):
        url = source['url']
        name = source.get('name') or source_name(url)
        requests_state.check()
        if default_reader:
            from modules import privacy, service_store
            service_store.identity(owner)
            if blocked := privacy.blocked('web'):
                if not privacy.public_read(str(url)):
                    raise PermissionError(blocked)
        key = (owner, url, query or '')
        with _lock:
            hit = _CACHE.get(key)
        if hit and hit[0] > time.monotonic():
            return url, ([dict(row) for row in hit[1]], {'source': name, 'url': url, 'status': 'ok',
                                                            'item_count': len(hit[1]), 'reason': None, 'cache': True})
        try:
            with requests_state.budget(SOURCE_SECONDS):
                items = list(reader(url) or [])[:MAX_ITEMS_PER_SOURCE]
        except (requests_state.Cancelled, PermissionError):
            raise
        except Exception as exc:
            _record_failure('modules/news_pipeline.py:discover_source')
            return url, ([], {'source': name, 'url': url, 'status': 'failed', 'item_count': 0,
                              'reason': _safe_reason(exc)})
        candidates = [dict(normalize(item, source=name, now=today), feed=url)
                      for item in items if isinstance(item, dict) and item.get('url')]
        status = 'ok' if candidates else 'partial'
        if candidates:
            with _lock:
                _CACHE[key] = (time.monotonic() + CACHE_SECONDS, candidates)
        return url, (candidates, {'source': name, 'url': url, 'status': status,
                                  'item_count': len(candidates), 'reason': None})

    if len(rows) == 1:
        collected = [read(rows[0])]
    else:
        # Independent indexes are read in parallel; the caller's request context is copied so a
        # cancel still reaches every worker, and each read isolates its own failures.
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(rows)), thread_name_prefix='jarvis-news') as pool:
            collected = [future.result() for future in
                         [pool.submit(copy_context().run, read, source) for source in rows]]
    by_url = {url: pair for url, pair in collected}
    candidates, health = [], []
    for source in rows:
        items, row = by_url[source['url']]
        health.append(row)
        candidates.extend(items)
    return candidates, health


def _safe_reason(exc) -> str:
    """Kaynak hatası kullanıcıya iner: anahtar ve benzeri ayrıntı maskelenir, metin kısaltılır."""
    from modules import privacy
    from modules import requests_state
    if isinstance(exc, requests_state.LocalDeadline):
        return 'Kaynak ayrılan sürede yanıt vermedi.'
    text = ' '.join(str(exc or '').split())
    return privacy.redact(text, force=True)[:200] or type(exc).__name__


def _today():
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=3))).date()


def in_window(row, days, today) -> bool:
    if not row.get('published_at'):
        return False
    age = (today - date.fromisoformat(row['published_at'])).days
    return 0 <= age <= days


def verify(row, *, request, fetcher, today, days) -> dict:
    """Open the single article page; an RSS summary alone is never final evidence.

    Freshness uses the run's own reference date, so a fixed `now` stays deterministic and a page
    without its own publication date is rejected by the article reader instead of being filled in.
    """
    fetcher = fetcher or public_sources.fetch
    # model_free_news yalnız burada çağrılır: modül üstünde içe aktarmak privacy→config döngüsünü
    # bu hat üzerinden kırar, çünkü config anahtarı okumak için tam yüklenmiş privacy ister.
    from modules import model_free_news, requests_state
    candidate = dict(row)
    try:
        requests_state.check()
        with requests_state.budget(SOURCE_SECONDS):
            article = article_reader(fetcher(row['url']))
        published = date.fromisoformat(article['published'])
        if published > today:
            raise ValueError('Haberin yayın tarihi gelecekte; taze haber olarak sunulmadı.')
        if (today - published).days > days:
            raise ValueError('Haber istenen pencerenin dışında; eski haber eklenmedi.')
        if re.search(r'son\s+dakika|son\s+\d+\s+saat|bug[uü]n|bu\s+sabah|yar[iı]n',request,re.I):
            research_evidence.news_date(article,request)
        quotes = model_free_news.quotes(article, request)
    except (requests_state.Cancelled, PermissionError):
        raise
    except Exception as exc:
        _record_failure('modules/news_pipeline.py:verify_article')
        candidate['reason'] = _safe_reason(exc)
        return candidate
    candidate.update(verification='verified', news_article=article, quotes=quotes,
                    published_at=article['published'], date_status='present',
                    other_sources=list(candidate.get('other_sources') or []))
    return candidate


def _read_plan(candidates, limit) -> list[dict]:
    """Host-diverse, bounded page-read order: publishers take turns, so one index cannot eat the budget.

    Deterministic over the input order; a host is never read more than its own candidate count, and
    the total is capped by `limit`.
    """
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for row in candidates:
        host = publisher_news.publisher_key(row['url'])
        if host not in groups:
            groups[host] = []
            order.append(host)
        groups[host].append(row)
    plan: list[dict] = []
    for index in range(max((len(groups[host]) for host in order), default=0)):
        for host in order:
            if index < len(groups[host]):
                plan.append(groups[host][index])
    return plan[:max(0, int(limit))]


def enough_evidence(verified, request=None) -> bool:
    """One completion contract; explicit single-source work stays within its scope."""
    wanted = str(request or '')
    explicit = {url.rstrip(".,!?)\"'”") for url in re.findall(r'https?://[^\s<>|]+', wanted)}
    single = bool(explicit or re.search(r'\b(?:tek|bir)\s+(?:haber|kaynak)|\bhaber(?:i|ini)\b', wanted, re.I))
    plural = bool(re.search(r'(?:iki|2)\s+(?:ayrı|ayri|farklı|farkli|bağımsız|bagimsiz)', wanted, re.I))
    minimum = 1 if single and not plural else MIN_VERIFIED
    urls = {row.get('news_article', {}).get('url') for row in verified if isinstance(row, dict)} - {None, ''}
    hosts = {publisher_news.publisher_key(url) for url in urls}
    if explicit and not plural:
        requested_hosts={publisher_news.publisher_key(url) for url in explicit}
        return len(urls)>=len(explicit) and requested_hosts.issubset(hosts)
    return len(urls) >= minimum and len(hosts - {''}) >= minimum


def _verify_plan(rows, *, request, fetcher, today, days, previous=()) -> list[dict]:
    """Read bounded batches and return as soon as the publisher evidence is sufficient."""
    from modules import requests_state
    from functools import partial

    checked: list[dict] = []
    verified = [row for row in previous if row['verification'] == 'verified']
    read = partial(verify, request=request, fetcher=fetcher, today=today, days=days)
    breaking = bool(re.search(r'\bson\s+dakika\b', request, re.I))
    for start in range(0, len(rows), MAX_WORKERS):
        batch = rows[start:start + MAX_WORKERS]
        pool = ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix='jarvis-news')
        try:
            futures = [pool.submit(copy_context().run, read, row) for row in batch]
            for future in as_completed(futures) if breaking else futures:
                requests_state.check()
                row = future.result()
                checked.append(row)
                if row['verification'] == 'verified':
                    verified.append(row)
                    if breaking and enough_evidence(verified, request):
                        return checked
        finally:
            # Unneeded reads carry the same owner and bounded source timeouts.
            # Their future results are never used after this evidence set is closed.
            pool.shutdown(wait=False, cancel_futures=True)
        if enough_evidence(verified, request):
            break
    return checked


def status(health, *, verified, model_status='unavailable', request=None) -> dict:
    """news_status is about sources and evidence; model_status never overwrites it."""
    total = len(health)
    failed = sum(1 for row in health if row['status'] == 'failed')
    if enough_evidence(verified, request):
        news = 'complete'
    elif verified:
        news = 'partial'
    elif total and failed == total:
        news = 'unavailable'
    else:
        news = 'empty'
    return {'news_status': news, 'model_synthesis_status': model_status}


def report(result) -> str:
    """Deterministic user-facing delivery: title, source, date, link, evidence, no model needed."""
    days = result.get('window_days', DEFAULT_WINDOW)
    health = result['source_health']
    verified = result['verified']
    request=str(result.get('request',''))
    hours=re.search(r'son\s+(\d+)\s+saat',request,re.I)
    if hours:
        label=f'Son {int(hours[1])} saat'
    elif re.search(r'son\s+dakika',request,re.I):
        label='Son 1 saat'
    elif re.search(r'bu\s+sabah',request,re.I):
        label='Bu sabah (İstanbul saati)'
    elif re.search(r'bug[uü]n',request,re.I):
        label='Bugün (İstanbul saati)'
    else:
        label=f'Son {days} gün'
    precise=bool(re.search(r'son\s+\d+\s+saat|son\s+dakika|bu\s+sabah|bug[uü]n',request,re.I))
    lines = ([f'İstenen yayın aralığı: {label}. {result["sources_total"]} kaynak tarandı.'] if precise
             else [f'Son {days} günde {result["sources_total"]} kaynak tarandı.'])
    lines.append(f'{result["sources_ok"]} kaynak yanıt verdi'
                 + (f', {result["sources_failed"]} kaynak erişilemedi.' if result['sources_failed'] else '.'))
    if result['sources_partial']:
        lines.append(f'{result["sources_partial"]} kaynak yanıt verdi ancak başlık listesi boş döndü.')
    lines.append(f'{result["articles_discovered"]} aday bulundu, {result.get("articles_read", 0)} tekil sayfa '
                 f'okundu, {len(verified)} haber doğrulandı.')
    missing = sum(1 for row in result['candidates'] if row['date_status'] == 'missing')
    if missing:
        lines.append(f'{missing} aday için yayın tarihi doğrulanamadı; taze haber listesine alınmadı.')
    if result['news_status'] == 'unavailable':
        lines.append('Hiçbir kayıtlı kaynak yanıt vermedi; haber sonuçları kullanılamıyor. '
                     'Bu bir model hatası değil, kaynak erişim hatasıdır.')
    elif not verified:
        lines.append('Doğrulanmış haber bulunamadı; eski veya tarihsiz adaylar haber olarak sunulmadı.')
    if result['model_synthesis_status'] == 'unavailable':
        lines.append('Model tabanlı sentez kullanılamıyor; aşağıdaki haberler doğrulanmış kaynak '
                     'kanıtıyla olduğu gibi teslim edildi.')
    if verified:
        lines.append('')
        lines.append('Doğrulanmış haberler:')
        for index, row in enumerate(verified, 1):
            article = row['news_article']
            lines.append('')
            lines.append(f'{index}. {article["title"]}')
            lines.append(f'Kaynak: {row["source"]}')
            lines.append(f'Tarih: {article.get("published_at") or article["published"]}')
            lines.append(f'Bağlantı: {article["url"]}')
            lines.append('Kanıt: ' + ' '.join(row['quotes'])[:700])
            if row.get('other_sources'):
                lines.append('Diğer kaynaklar: ' + ', '.join(row['other_sources']))
    if result.get('conflict_note'):
        lines.append('')
        lines.append(result['conflict_note'])
    lines.append('')
    lines.append('Durum: ' + result['news_status'] + ' · doğrulanmış ' + str(len(verified)) + ' haber.')
    return '\n'.join(lines)


def verified_from_outputs(outputs) -> list[dict]:
    """Reuse already sealed receipts so a later model request does not re-crawl the web."""
    rows = []
    for output in (outputs or {}).values():
        if not isinstance(output, dict) or output.get('state') != 'done':
            continue
        article = output.get('news_article')
        if isinstance(article, dict) and article.get('url') and isinstance(output.get('source_quotes'), list):
            rows.append({'url': article['url'], 'title': article.get('title', ''), 'summary': '',
                         'source': source_name(article['url']), 'published_at': article.get('published'),
                         'date_status': 'present', 'category': category_of(article.get('title')),
                         'verification': 'verified', 'news_article': article,
                         'quotes': output['source_quotes'], 'other_sources': [], 'reused': True})
    return rows


def synthesis_input(result) -> dict:
    """Only structured pipeline evidence reaches a synthesis model."""
    return {'request': result.get('request', ''), 'window_days': result.get('window_days', DEFAULT_WINDOW),
            'articles': [{'title': row['news_article']['title'], 'url': row['news_article']['url'],
                          'published': row['news_article']['published'], 'source': row['source'],
                          'quotes': row['quotes'], 'other_sources': row.get('other_sources', [])}
                         for row in result.get('verified', [])]}


_NUMBER = re.compile(r'\d+(?:[.,]\d+)?')
_QUOTE = re.compile(r'[“"\'«]([^”"\'»]{6,400})[”"\'»]')


def _values(text) -> set[str]:
    out = set()
    for match in _NUMBER.finditer(str(text or '')):
        try:
            out.add(f'{float(match.group(0).replace(",", ".")):g}')
        except ValueError:
            continue
    return out


def _sentences(text) -> list[str]:
    return [part.strip() for part in re.split(r'(?<=[.!?])\s+', str(text or '')) if part.strip()]


def verify_synthesis(text, evidence) -> dict:
    """Numbers and quotes in a briefing must exist in the evidence; otherwise safe downgrade.

    A failed check never fails the news task: the unsupported sentence is dropped and the
    remaining factual text is delivered. Nothing invented is shown.
    """
    joined = ' '.join(str((row.get('news_article') or {}).get(k, '')) for row in evidence or {}
                      for k in ('title', 'text', 'published', 'url'))
    for row in evidence or []:
        joined += ' ' + ' '.join(str(quote) for quote in row.get('quotes') or [])
    allowed = _values(joined)
    normalized = ' '.join(str(text or '').split())
    unsupported = [value for value in _NUMBER.findall(normalized)
                   if f'{float(value.replace(",", ".")):g}' not in allowed]
    kept, dropped_quote = [], False
    for sentence in _sentences(normalized):
        numbers = _values(sentence)
        if numbers and not numbers <= allowed:
            continue
        if any(_fold(quote) and _fold(quote) not in _fold(joined) for quote in _QUOTE.findall(sentence)):
            dropped_quote = True
            continue
        kept.append(sentence)
    clean = ' '.join(kept).strip()
    ok = not unsupported and not dropped_quote
    if not clean:
        clean = 'Model tabanlı sentez doğrulanamadı; uydurma sayı veya alıntı gösterilmedi. ' \
                'Yalnız doğrulanmış kanıt raporunda.'
    return {'ok': ok, 'text': clean, 'unsupported_numbers': unsupported,
            'dropped_unsupported_quote': dropped_quote}


def external_candidates(rows):
    """Bound discovery reads to distinct publishers and non-directory URLs."""
    chosen=[];publishers=set()
    for row in rows or []:
        if not isinstance(row,dict) or not row.get('url'):continue
        try:url=public_sources.address(row['url'])
        except ValueError:continue
        path=urlsplit(url).path.casefold()
        if re.search(r'(?:^|/)(?:kategori|category|etiket|tag|haberleri|tum-haberler|son-dakika-haberler)(?:/|$)',path):continue
        key=publisher_news.publisher_key(url)
        if key in publishers:continue
        publishers.add(key);chosen.append(dict(row,url=url))
        if len(chosen)>=8:break
    return chosen


def run(request, *, owner=None, reader=None, fetcher=None, sources=None, days=None, now=None,
        reuse=None, source_health=None, model_status='unavailable', claim_review=None,
        max_sources=MAX_SOURCES, searcher=None) -> dict:
    """Model-free vertical: discover → filter → cluster → verify → deterministic report."""
    today = now or _today()
    window = window_days(request) if days is None else max(1, min(MAX_WINDOW, int(days)))
    external_discovery={'state':'not_attempted','candidates':0,'reason':None}
    reused = [dict(row) for row in (reuse or [])]
    health: list[dict] = [dict(row) for row in (source_health or [])]
    candidates: list[dict] = []
    if reuse is not None or source_health is not None:
        # İşten türetilen özet: kurtarma döngüsü kaynakları zaten okudu. Burada ikinci bir tarama
        # başlamaz; kimlik bekçisi olmayan bir istek (owner=None) asla katalog okumaz.
        candidates = [dict(row, in_window=in_window(row, window, today)) for row in reused]
        fresh = [row for row in candidates if row['in_window']]
        verified = []
        from modules import model_free_news
        for row in fresh:
            if row.get('verification') != 'verified' or not row.get('news_article'):
                continue
            try:
                if re.search(r'son\s+dakika|son\s+\d+\s+saat|bug[uü]n|bu\s+sabah|yar[iı]n',request,re.I):
                    research_evidence.news_date(row['news_article'],request)
                row['quotes'] = model_free_news.quotes(row['news_article'], request)
            except (ValueError, KeyError):
                continue
            verified.append(row)
        reused_count = len(verified)
        reads_count = 0
    else:
        explicit = list(dict.fromkeys(url.rstrip(".,!?)\"'”")
                        for url in re.findall(r'https?://[^\s<>|]+', str(request))))
        if explicit and sources is None:
            rows = [{'url': public_sources.address(url), 'name': source_name(url)} for url in explicit]
        else:
            rows = sources if sources is not None else catalog(request)
        candidates, health = discover(rows, reader=reader, owner=owner, query=request, now=today,
                                      max_sources=max_sources)
        if explicit and sources is None:
            for url in explicit:
                if not any(row['url'] == url for row in candidates):
                    candidates.insert(0, normalize({'url': url}, source=source_name(url), now=today))
        candidates = filter_candidates(candidates, request)
        candidates = cluster(candidates)
        for row in candidates:
            row['in_window'] = in_window(row, window, today)
        # A listing that prints no dates is not an undated story: the article page's own date is the
        # legitimate evidence, so only a feed date already outside the window cancels the read.
        stale = {row['url'] for row in candidates if row['published_at'] and not row['in_window']}
        expand = sources is None and not explicit and ((owner is not None and reader is None) or searcher is not None)
        catalog_budget = MAX_ARTICLE_READS - 8 if expand else MAX_ARTICLE_READS
        reads = _read_plan([row for row in candidates if row['url'] not in stale], catalog_budget)
        checked_rows = _verify_plan(reads, request=request, fetcher=fetcher, today=today, days=window)
        verified = [row for row in checked_rows if row['verification'] == 'verified']
        if expand and not enough_evidence(verified, request):
            from modules import requests_state
            requests_state.check()
            try:
                extra = (searcher or research_providers.search_news_public)(request)
                seen = {row['url'] for row in checked_rows}
                additions = []
                for item in external_candidates(extra):
                    if not isinstance(item, dict) or not item.get('url'):
                        continue
                    try:
                        url = public_sources.address(item['url'])
                    except ValueError:
                        continue
                    if url in seen:
                        continue
                    seen.add(url)
                    additions.append(normalize(dict(item, url=url), source=source_name(url), now=today))
                    if len(additions) >= 8:
                        break
                external_discovery={'state':'candidates' if additions else 'empty','candidates':len(additions),'reason':None,
                                    'providers':sorted({str(row.get('provider','unknown')) for row in extra or [] if isinstance(row,dict)})}
                additions = filter_candidates(additions, request)
                candidates.extend(additions)
                checked_rows.extend(_verify_plan(additions, request=request, fetcher=fetcher,
                                                 today=today, days=window, previous=checked_rows))
                verified = [row for row in checked_rows if row['verification'] == 'verified']
            except (requests_state.Cancelled, PermissionError):
                raise
            except Exception as exc:
                _record_failure('modules/news_pipeline.py:public_discovery')
                external_discovery={'state':'failed','candidates':0,'reason':_safe_reason(exc)}
        by_url = {row['url']: row for row in checked_rows}
        for row in candidates:
            match = by_url.get(row['url'])
            if match is not None:
                if match['verification'] == 'verified':
                    row.update(verification='verified', news_article=match['news_article'], quotes=match['quotes'],
                               published_at=match['published_at'], date_status='present')
                elif 'reason' in match:
                    # Reddediği sayfanın gerekçesi adaya iner: kullanıcıye "neden haber değil" kanıtı gösterilir.
                    row['reason'] = match['reason']
            row['in_window'] = in_window(row, window, today)
        verified = [row for row in verified if in_window(row, window, today)]
        reads_count = len(checked_rows)
        reused_count = 0
    discovered = len(candidates)
    ok = sum(1 for row in health if row['status'] != 'failed')
    failed = sum(1 for row in health if row['status'] == 'failed')
    partial = sum(1 for row in health if row['status'] == 'partial')
    codes = status(health or [{'source': 'reuse', 'status': 'ok', 'item_count': len(verified), 'reason': None}],
                   verified=verified, model_status=model_status, request=request)
    result = {
        'request': request,
        'public_discovery': external_discovery,
        'window_days': window,
        'source_health': health,
        'sources_total': len(health),
        'sources_ok': ok,
        'sources_failed': failed,
        'sources_partial': partial,
        'candidates': candidates,
        'articles_discovered': discovered,
        'articles_read': reads_count,
        'articles_verified': len(verified),
        'verified': verified,
        'reused': reused_count,
        **codes,
    }
    if claim_review is not None:
        note = claim_review(verified)
        if note:
            result['conflict_note'] = note
    result['report'] = report(result)
    return result


_DISCOVERY = {'sources', 'headlines', 'news_search'}
_DEAD = {'failed', 'blocked', 'unavailable', 'error', 'review'}


def job_health(job) -> list[dict]:
    """Source health read back from the job's own steps; no second crawl is started here.

    The recovery loop already recorded which index answered, which came back empty and which
    failed, so the same per-source isolation the pipeline uses can be reported from that state.
    """
    rows: dict[str, dict] = {}
    outputs = job.get('outputs') or {}
    for step in job.get('steps') or []:
        if not isinstance(step, dict):
            continue
        data = step.get('input') if isinstance(step.get('input'), dict) else {}
        url = str(data.get('url') or '')
        research = step.get('tool') == 'research'
        discovery = step.get('tool') == 'data' and data.get('operation') in _DISCOVERY
        if not url or not (research or discovery):
            continue
        host = (urlsplit(url).hostname or url).lower()
        row = rows.setdefault(host, {'source': source_name(url), 'url': url, 'status': 'partial',
                                     'item_count': 0, 'reason': None})
        output = outputs.get(step.get('id')) or {}
        state = str(output.get('state') or step.get('state') or '')
        if state == 'done':
            if research:
                row['status'] = 'ok'
            else:
                items = ((output.get('structured') or {}).get('items') or [])
                row['item_count'] = max(row['item_count'], len(items))
                if items:
                    row['status'], row['reason'] = 'ok', None
        elif state in _DEAD:
            row['status'] = 'failed'
            row['reason'] = _safe_reason(output.get('text') or state)
    return list(rows.values())


def _record(job, result) -> None:
    """İşe yazılan özet: durumlar, kaynak sağlığı, kanıt listesi ve deterministik rapor.

    Yalnız özet saklanır; haber gövdeleri iş kaydına ikinci kez yazılmaz.
    """
    rejected = {}
    for row in result.get('candidates', []):
        if row.get('reason'):
            reason = _safe_reason(row['reason'])
            rejected[reason] = rejected.get(reason, 0) + 1
    job['news_pipeline'] = {
        'public_discovery': result.get('public_discovery',{'state':'not_attempted','candidates':0,'reason':None}),
        'rejected_candidates': [{'url':_safe_reason(row.get('url',''))[:240],
                                 'reason':_safe_reason(row['reason'])}
                                for row in result.get('candidates',[]) if row.get('reason')][:12],
        'articles_rejected': sum(rejected.values()),
        'rejection_reasons': [{'reason': reason, 'count': count}
                              for reason, count in sorted(rejected.items(), key=lambda item: (-item[1], item[0]))[:3]],
        'outside_window': sum(bool(row.get('published_at')) and row.get('in_window') is False
                              for row in result.get('candidates', [])),
        'window_days': result['window_days'],
        'news_status': result['news_status'],
        'model_synthesis_status': result['model_synthesis_status'],
        'sources_total': result['sources_total'],
        'sources_ok': result['sources_ok'],
        'sources_failed': result['sources_failed'],
        'sources_partial': result['sources_partial'],
        'articles_discovered': result['articles_discovered'],
        'articles_read': result['articles_read'],
        'articles_verified': result['articles_verified'],
        'reused': result['reused'],
        'source_health': result['source_health'],
        'evidence': [{'url': row['url'], 'source': row['source'], 'published_at': row['published_at']}
                     for row in result['verified']],
        'report': result['report'],
    }


def attach_job(job, *, model_status='unavailable', now=None) -> dict:
    """Modelsiz teslim kaydı: işin kendi mühürlü kanıtından üretilir, ağa çıkmaz."""
    request = str(job.get('request') or '')
    result = run(request, reuse=verified_from_outputs(job.get('outputs') or {}),
                 source_health=job_health(job), now=now, model_status=model_status)
    _record(job, result)
    return result


def deliver_job(job, *, model_status='unavailable', reader=None, fetcher=None, now=None,
                max_sources=MAX_SOURCES) -> dict:
    """Plan hiç yapılamadığında haberin modelsiz tam teslimi: paralel keşif + doğrulama + rapor.

    Çağrının kendi kaynak sınırları (timeout, bütçe, iptal) geçerlidir; hiçbir model istenmez.
    """
    result = run(str(job.get('request') or ''), owner=job.get('owner'), reader=reader, fetcher=fetcher,
                 now=now, model_status=model_status, max_sources=max_sources)
    _record(job, result)
    return result


def delivery_note(job) -> str:
    """Tek satırlık teslim durumu: haber sonuç durumu model durumunu ezmez."""
    record = job.get('news_pipeline')
    if not isinstance(record, dict):
        return ''
    verified = record.get('articles_verified') or 0
    reused = record.get('reused') or 0
    total = record.get('sources_total') or 0
    ok = record.get('sources_ok') or 0
    failed = record.get('sources_failed') or 0
    parts = [f"Haber durumu: {record.get('news_status', 'unavailable')}", f'doğrulanmış {verified} haber']
    if reused and not verified:
        parts.append(f'pencere dışında kalan {reused} eski kanıt')
    if total:
        parts.append(f'{ok}/{total} kaynak yanıt verdi' + (f', {failed} erişilemedi' if failed else ''))
    line = ' · '.join(parts) + '.'
    if record.get('model_synthesis_status') == 'unavailable':
        line += (' Model tabanlı sentez kullanılamıyor; haberler kaynak/tarih/link kanıtıyla '
                 'olduğu gibi teslim edildi.')
    return line


def render_lines(job) -> list[str]:
    """Modelsiz teslim satırları: kanıt satırı hiç yoksa deterministik rapor, her zaman durum satırı."""
    record = job.get('news_pipeline')
    if not isinstance(record, dict):
        return []
    lines = []
    has_evidence = any((goal.get('evidence') or goal.get('chat_evidence'))
                       for goal in (job.get('goals') or []) if isinstance(goal, dict))
    if not has_evidence and record.get('report'):
        lines.append(record['report'])
    note = delivery_note(job)
    if note:
        lines.append(note)
    return lines


