"""Immutable, registered RSS publication-date receipts for news articles."""
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from modules import public_sources


PROVIDERS = {
    'anadolu_ajansi': {'feed_url': 'https://www.aa.com.tr/tr/rss/default?cat=guncel', 'host': 'www.aa.com.tr'},
    'ntv': {'feed_url': 'https://www.ntv.com.tr/turkiye.rss', 'host': 'www.ntv.com.tr'},
    'trt_haber': {'feed_url': 'https://www.trthaber.com/sondakika_articles.rss', 'host': 'www.trthaber.com'},
}


def provider_for_feed(feed_url):
    """Return the registered provider id for an exact normalized feed URL."""
    normalized=public_sources.address(feed_url)
    for provider_id,provider in PROVIDERS.items():
        if public_sources.address(provider['feed_url'])==normalized:return provider_id
    return None


def receipt(*, provider_id, feed_url, entry, article_url):
    """Bind a registered feed entry's publication date to its exact article URL."""
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError('Kayıtlı RSS sağlayıcısı bulunamadı.')
    expected_feed = public_sources.address(provider['feed_url'])
    if public_sources.address(feed_url) != expected_feed:
        raise ValueError('RSS makbuzu kayıtlı sağlayıcı akışıyla eşleşmiyor.')
    if not isinstance(entry, dict):
        raise ValueError('RSS girdisi geçersiz.')
    url = public_sources.address(article_url)
    if public_sources.address(entry.get('url', '')) != url:
        raise ValueError('RSS girdisi tekil haber bağlantısıyla eşleşmiyor.')
    if urlsplit(url).hostname != provider['host']:
        raise ValueError('RSS makbuzu başka alan adına ait olamaz.')
    title = entry.get('title')
    published = entry.get('published')
    if not isinstance(title, str) or not title.strip() or not isinstance(published, str):
        raise ValueError('RSS başlığı veya yayın tarihi geçersiz.')
    try:
        try:day=datetime.fromisoformat(published.replace('Z', '+00:00')).date().isoformat()
        except ValueError:day=parsedate_to_datetime(published).date().isoformat()
    except (TypeError,ValueError) as exc:
        raise ValueError('RSS yayın tarihi ISO-8601 veya RFC 2822 olmalı.') from exc
    return {'provider_id': provider_id, 'feed_url': expected_feed, 'article_url': url,
            'title': title.strip(), 'published': day}


def from_headlines(feed_url, entries):
    """Create exact-URL receipts only when headlines came from a registered RSS feed."""
    provider_id=provider_for_feed(feed_url)
    if provider_id is None:return {}
    result={}
    for entry in entries:
        if not isinstance(entry,dict) or not entry.get('published'):continue
        try:
            bound=receipt(provider_id=provider_id,feed_url=feed_url,entry=entry,article_url=entry.get('url',''))
        except (TypeError,ValueError):
            continue
        result[bound['article_url']]=bound
    return result
