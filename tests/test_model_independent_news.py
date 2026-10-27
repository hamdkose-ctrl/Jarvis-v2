"""Model-bağımsız haber hattı kabul testleri (A–J).

Bu dosya news_pipeline'ın model sağlayıcılarından bağımsızlığını kilitler: Gemini/Groq/Ollama
kullanılamazken bile keşif, doğrulama ve deterministik teslim çalışmalı; model hataları haber
sonucundan ayrılmamalı. Ağ ve model çağrısı yoktur; yalnız taşıyıcılar taklit edilir.
"""
from datetime import date, datetime, time, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch
import unittest

from modules import news_pipeline, publisher_news, research_evidence, research_providers

DAY = date(2026, 10, 21)
NOW = DAY  # pipeline testlerinde sabit "bugün"; Date.now() asla kullanılmaz
GENERAL = [row['url'] for row in publisher_news.GENERAL_SOURCES]


def feed(source_url, rows):
    """Rows are (title, path, pubDate, category); links are host-rooted like a real publisher feed."""
    from urllib.parse import urlsplit
    from xml.sax.saxutils import escape
    root = 'https://' + urlsplit(source_url).hostname
    items = []
    for title, link, published, category in rows:
        items.append('<item><title>%s</title><link>%s</link>%s%s</item>' % (
            escape(title), root + link,
            ('<pubDate>%s</pubDate>' % escape(published)) if published else '',
            ('<category>%s</category>' % escape(category)) if category else ''))
    body = ('<?xml version="1.0"?><rss version="2.0"><channel>' + ''.join(items) + '</channel></rss>')
    return {'url': source_url, 'body': body.encode('utf-8')}


def article(url, title, published, text):
    stamp = ('<time itemprop="datePublished" datetime="%s"></time>' % published) if published else ''
    return {'url': url, 'body': ('<article><h1>%s</h1>%s<p>%s</p></article>' % (title, stamp, text)).encode('utf-8')}


BODY = ('Deprem sonrası ilgili kurumlar sahadaki incelemelerin sonuçlarını kamuoyuna açıkladı. '
        'Bölgedeki ekipler çalışmalarını sürdürürken yetkililer doğrulanmış yeni bilgileri paylaştı. '
        'Kullanıcının isteğine ilişkin ayrıntılar haberin kendi metninde yer alıyor.')

AA = 'https://www.aa.com.tr'
BBC = 'https://www.bbc.com'
DW = 'https://www.dw.com'
AA_INDEX = AA + '/tr/gundem'
BBC_INDEX = BBC + '/turkce'


def istanbul_today():
    """Goal-executor yolu araştırma adımında gerçek saati kullanır; o testte tarih gerçek bugüne sabitlenir."""
    from datetime import datetime, timezone
    return datetime.now(timezone(timedelta(hours=3))).date()


def two_source_feeds(failing=(), *, day=None, article_body=BODY):
    """Reader/fetcher pair: AA and BBC index + articles; optional source failure.

    Feed and article dates both come from `day`, so a test either pins a fixed reference date or
    anchors to the real one; nothing is ever filled in with the current time by the pipeline.
    """
    day = day or DAY
    published = format_datetime(datetime.combine(day, time(9, tzinfo=timezone.utc)), usegmt=True)
    rows = {
        AA_INDEX: feed(AA_INDEX, [('AA deprem haberi', '/tr/gundem/deprem-1', published, 'Gündem')]),
        BBC_INDEX: feed(BBC_INDEX, [('BBC deprem haberi', '/turkce/deprem-2', published, 'Gündem')]),
    }

    def reader(url):
        if url in failing:
            raise OSError('taklit kaynak zaman aşımı')
        if url not in rows:
            return []
        return entries(rows[url])

    def fetcher(url):
        if url == AA + '/tr/gundem/deprem-1':
            return article(url, 'AA deprem haberi', day.isoformat(), article_body)
        if url == BBC + '/turkce/deprem-2':
            return article(url, 'BBC deprem haberi', day.isoformat(), article_body)
        if url in rows:
            return rows[url]
        raise OSError('beklenmeyen adres: ' + url)

    return reader, fetcher


def entries(response):
    from modules import public_sources
    return public_sources.entries(response)


class AllProvidersUnavailableTests(unittest.TestCase):
    """A. Gemini 429 + Groq 429 + Ollama unavailable: haber hattı yine çalışır."""

    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_pipeline_delivers_verified_news_with_no_model_at_all(self):
        reader, fetcher = two_source_feeds()
        result = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                   sources=[{'name': 'AA', 'url': AA + '/tr/gundem'},
                                            {'name': 'BBC Türkçe', 'url': BBC + '/turkce'}],
                                   now=NOW, model_status='unavailable')
        self.assertEqual(result['news_status'], 'complete')
        self.assertEqual(result['model_synthesis_status'], 'unavailable')
        self.assertGreaterEqual(result['articles_verified'], 2)
        self.assertIn('Model tabanlı sentez kullanılamıyor', result['report'])
        for row in result['verified']:
            self.assertTrue(row['news_article']['url'].startswith('https://'))
            self.assertEqual(row['news_article']['published'], DAY.isoformat())
            self.assertTrue(row['quotes'])

    def test_no_model_is_called_by_the_pipeline(self):
        ask = Mock(side_effect=AssertionError('haber hattı model çağırmadı'))
        reader, fetcher = two_source_feeds()
        with patch('modules.model_wait.ask', ask), patch('modules.llm.ask', ask):
            result = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                       sources=[{'name': 'AA', 'url': AA + '/tr/gundem'}], now=NOW)
        ask.assert_not_called()
        self.assertEqual(result['news_status'], 'complete')

    def test_quota_cooldown_does_not_stop_a_news_request(self):
        import test_goal_executor as fixture
        from modules import goal_executor as goals
        case = fixture.GoalTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        reader, fetcher = two_source_feeds(day=istanbul_today())
        case.responses(case.plan('Son 7 gün deprem haberlerini araştır'), RuntimeError('Taklit sağlayıcı kullanılamıyor'))
        with patch('modules.llm.quota_wait_seconds', return_value=42), \
             patch('modules.public_sources.fetch', side_effect=fetcher), \
             patch('modules.domain_tools.headlines', side_effect=lambda owner, url, **kw: {'items': reader(url)}), \
             patch('modules.privacy.blocked', return_value=None):
            reply = goals.run(case.runtime, 'son 7 gün deprem haberleri')
        job = goals.latest('alice')
        self.assertIsNotNone(job, 'kota dolu diye haber işi hiç açılmadı')
        self.assertNotIn('kota', reply.casefold())
        self.assertEqual(job['state'], 'done', reply)
        self.assertEqual(job['news_pipeline']['model_synthesis_status'], 'unavailable')
        self.assertEqual(job['news_pipeline']['news_status'], 'complete')
        self.assertGreaterEqual(job['news_pipeline']['sources_total'], 1)
        self.assertGreaterEqual(job['news_pipeline']['articles_verified'], 2)
        self.assertIn('Model tabanlı sentez kullanılamıyor', reply)
        for row in job['news_pipeline']['evidence']:
            self.assertTrue(row['url'].startswith('https://'))
            self.assertTrue(row['published_at'])


    def test_total_outage_delivers_news_without_a_plan(self):
        """21. numara: plan hiç yapılamazsa haber hattı keşif, doğrulama ve teslimi modelsiz kendisi yapar."""
        import test_goal_executor as fixture
        from modules import goal_executor as goals
        case = fixture.GoalTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        reader, fetcher = two_source_feeds(day=istanbul_today())
        case.responses(RuntimeError('Gemini kota; Groq kota; Ollama yok'),
                       case.plan('Son 7 gün deprem haberlerini araştır'))
        with patch('modules.llm.quota_wait_seconds', return_value=90), \
             patch('modules.public_sources.fetch', side_effect=fetcher), \
             patch('modules.domain_tools.headlines', side_effect=lambda owner, url, **kw: {'items': reader(url)}), \
             patch('modules.privacy.blocked', return_value=None):
            reply = goals.run(case.runtime, 'son 7 gün deprem haberleri')
        job = goals.latest('alice')
        self.assertIsNotNone(job, 'plan yok diye haber işi kaybolmadı')
        self.assertEqual(job['news_pipeline']['model_synthesis_status'], 'unavailable')
        self.assertGreaterEqual(job['news_pipeline']['articles_verified'], 1)
        self.assertIn('Model tabanlı sentez kullanılamıyor', reply)
        self.assertIn(AA + '/tr/gundem/deprem-1', reply)
        self.assertIn(istanbul_today().isoformat(), reply)


class SourceIsolationTests(unittest.TestCase):
    """B ve C. Bir kaynak düşerse hat sürer; bütün kaynaklar düşerse cache'lenmez."""

    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_one_failing_source_is_reported_and_others_still_deliver(self):
        reader, fetcher = two_source_feeds(failing=(AA + '/tr/gundem',))
        result = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                   sources=[{'name': 'AA', 'url': AA + '/tr/gundem'},
                                            {'name': 'BBC Türkçe', 'url': BBC + '/turkce'}], now=NOW)
        self.assertEqual(result['news_status'], 'partial')
        self.assertEqual(result['sources_ok'], 1)
        self.assertEqual(result['sources_failed'], 1)
        failed = [row for row in result['source_health'] if row['status'] == 'failed']
        self.assertEqual([row['source'] for row in failed], ['AA'])
        self.assertTrue(failed[0]['reason'])
        self.assertGreaterEqual(result['articles_verified'], 1)

    def test_all_sources_failing_is_not_cached_as_empty_news(self):
        def reader(url):
            raise OSError('taklit ağ yok')
        calls = []
        fetcher = Mock(side_effect=lambda url: calls.append(url) or (_ for _ in ()).throw(OSError('yok')))
        for _ in range(2):
            result = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                       sources=[{'name': 'AA', 'url': AA + '/tr/gundem'}], now=NOW)
            self.assertEqual(result['news_status'], 'unavailable')
        self.assertEqual(result['verified'], [])
        self.assertEqual(len(news_pipeline.cached_urls()), 0, 'bütün kaynaklar başarısızken cache yazıldı')

    def test_healthy_window_cache_is_reused_for_ten_minutes(self):
        reader, fetcher = two_source_feeds()
        seen = []

        def counting(url):
            seen.append(url)
            return reader(url)

        sources = [{'name': 'AA', 'url': AA + '/tr/gundem'}]
        news_pipeline.run('son 7 gün deprem haberleri', reader=counting, fetcher=fetcher, sources=sources, now=NOW)
        first = len(seen)
        self.assertGreaterEqual(first, 1)
        news_pipeline.run('son 7 gün deprem haberleri', reader=counting, fetcher=fetcher, sources=sources, now=NOW)
        self.assertEqual(len(seen), first, 'cache var ama kaynak yeniden tarandı')
        self.assertEqual(sorted(news_pipeline.cached_urls()), sorted(s['url'] for s in sources))


class EmptyWindowTests(unittest.TestCase):
    """D. Kaynaklar çalışıyor ama son 7 günde haber yok: empty, unavailable değil."""

    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_old_articles_do_not_fill_the_window_and_status_is_empty(self):
        rows = [(AA + '/tr/gundem', [('Eski deprem haberi', '/tr/gundem/eski', 'Tue, 21 Jul 2026 09:00:00 GMT', 'Gündem')])]

        def reader(url):
            return entries(feed(url, rows[0][1]))

        def fetcher(url):
            return article(url, 'Eski deprem haberi', '2026-07-21', BODY)

        result = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                   sources=[{'name': 'AA', 'url': AA + '/tr/gundem'}], now=NOW)
        self.assertEqual(result['news_status'], 'empty')
        self.assertEqual(result['sources_failed'], 0)
        self.assertEqual(result['verified'], [])


class MissingDateTests(unittest.TestCase):
    """E. Yayın tarihi yoksa Date.now() ile doldurulmaz ve taze listeye girmez."""

    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_feed_without_date_keeps_date_status_missing(self):
        row = news_pipeline.normalize({'url': AA + '/tr/gundem/x', 'title': 'Tarihsiz haber', 'summary': '',
                                       'published': ''}, source='AA', now=NOW)
        self.assertIsNone(row['published_at'])
        self.assertEqual(row['date_status'], 'missing')

    def test_undated_article_is_never_verified_fresh_news(self):
        def reader(url):
            return entries(feed(url, [('Tarihsiz deprem haberi', '/tr/gundem/tarihsiz', None, 'Gündem')]))

        def fetcher(url):
            # Tekil sayfa da tarih vermiyor; hat "şimdi yayınlandı" diyemez.
            return article(url, 'Tarihsiz deprem haberi', None, BODY)

        result = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                   sources=[{'name': 'AA', 'url': AA + '/tr/gundem'}], now=NOW)
        self.assertEqual(result['verified'], [])
        self.assertTrue(result['candidates'])
        self.assertEqual(result['candidates'][0]['date_status'], 'missing')
        self.assertIn('yayın tarihi doğrulanamadı', result['report'])


class RssSummaryTests(unittest.TestCase):
    """F. RSS özü final kanıt değildir; tekil sayfa açılamazsa aday olarak kalır."""

    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_unreachable_article_page_leaves_a_discovery_candidate(self):
        def reader(url):
            return entries(feed(url, [('AA deprem haberi', '/tr/gundem/deprem-1',
                                       'Tue, 20 Oct 2026 09:00:00 GMT', 'Gündem')]))

        def fetcher(url):
            raise OSError('tekil sayfa okunamadı')

        result = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                   sources=[{'name': 'AA', 'url': AA + '/tr/gundem'}], now=NOW)
        self.assertEqual(result['articles_verified'], 0)
        self.assertEqual(result['news_status'], 'empty')
        candidate = result['candidates'][0]
        self.assertEqual(candidate['verification'], 'discovery_only')
        self.assertNotIn('verified', [row['url'] for row in result['verified']])


class CategoryAndTimeFilterTests(unittest.TestCase):
    """6 ve 7. Kategori/zaman süzümü modelsiz ve deterministik."""

    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_category_labels_and_unknown_fallback(self):
        cases = [('Fenerbahçe sahadan 3-1 ayrıldı', 'spor'),
                 ('Merkez Bankası faiz kararını açıkladı', 'ekonomi'),
                 ('Yeni yapay zekâ modeli tanıtıldı', 'teknoloji'),
                 ('Uzay teleskobu yeni bir galaksiyi görüntüledi', 'bilim'),
                 ('Grip vakaları için uyarı', 'sağlık'),
                 ('Parlamento dış politika tezkeresini oyladı', 'dünya'),
                 ('Şehir tiyatrosu sezonu açtı', 'kültür/sanat'),
                 ('Yeni bir gelişme kaydedildi', 'bilinmeyen')]
        for summary, expected in cases:
            with self.subTest(summary=summary):
                self.assertEqual(news_pipeline.category_of(summary), expected)
        row = news_pipeline.normalize({'url': AA + '/tr/gundem/x', 'title': 'Başlık', 'summary': '',
                                       'published': 'Tue, 20 Oct 2026 09:00:00 GMT'}, source='AA', now=NOW)
        self.assertEqual(row['category'], 'bilinmeyen')

    def test_user_categories_filter_without_a_model(self):
        rows = [('Spor haberi', '/spor', 'Tue, 20 Oct 2026 09:00:00 GMT', 'Spor'),
                ('Ekonomi haberi', '/ekonomi', 'Tue, 20 Oct 2026 09:00:00 GMT', 'Ekonomi'),
                ('Teknoloji haberi', '/teknoloji', 'Tue, 20 Oct 2026 09:00:00 GMT', 'Bilim & Teknoloji')]

        def reader(url):
            return entries(feed(url, rows))

        def fetcher(url):
            title = url.rsplit('/', 1)[-1].title() + ' haberi'
            return article(url, title, '2026-10-20', BODY)

        sources = [{'name': 'AA', 'url': AA + '/tr/gundem'}]
        # Açık daraltma ("sadece"/"hariç") modelsiz süzer; konu kelimesi tek başına aday haberleri discard etmez.
        for request, expected in (('spor hariç son 7 gün haberleri', {'ekonomi', 'teknoloji'}),
                                  ('sadece ekonomi haberleri', {'ekonomi'}),
                                  ('sadece yapay zekâ ve teknoloji haberleri', {'teknoloji'}),
                                  ('yapay zekâ ve teknoloji haberleri', {'spor', 'ekonomi', 'teknoloji'})):
            result = news_pipeline.run(request, reader=reader, fetcher=fetcher, sources=sources, now=NOW)
            self.assertEqual({row['category'] for row in result['candidates']}, expected, request)

    def test_default_window_is_seven_days_and_explicit_window_widens_it(self):
        self.assertEqual(news_pipeline.window_days('son 7 gün deprem haberleri'), 7)
        self.assertEqual(news_pipeline.window_days('deprem haberleri'), 7)
        self.assertEqual(news_pipeline.window_days('son 30 gün deprem haberleri'), 30)
        self.assertFalse(news_pipeline.window_days('son 30 gün') > 90)


class EventClusterTests(unittest.TestCase):
    """G ve 12. Başlık benzerliği yalnız aday kümesidir, claim anlaşması değil."""

    def test_similar_titles_cluster_with_other_sources_but_verify_nothing(self):
        candidates = [
            news_pipeline.normalize({'url': AA + '/tr/gundem/deprem-1', 'title': 'Elazığ depremi sonrası son durum',
                                     'summary': '', 'published': 'Tue, 20 Oct 2026 09:00:00 GMT'}, source='AA', now=NOW),
            news_pipeline.normalize({'url': BBC + '/turkce/deprem-1', 'title': 'Elazığ depremi sonrası son durum',
                                     'summary': '', 'published': 'Tue, 20 Oct 2026 10:00:00 GMT'}, source='BBC Türkçe', now=NOW),
            news_pipeline.normalize({'url': DW + '/turkce/mutfak', 'title': 'Yeni bir yemek tarifi yayınlandı bugün',
                                     'summary': '', 'published': 'Tue, 20 Oct 2026 09:30:00 GMT'}, source='DW Türkçe', now=NOW),
        ]
        clustered = news_pipeline.cluster(candidates)
        first, second, other = clustered
        self.assertEqual(first['event_cluster_id'], second['event_cluster_id'])
        self.assertNotEqual(first['event_cluster_id'], other['event_cluster_id'])
        self.assertEqual(first['other_sources'], ['BBC Türkçe'])
        self.assertEqual(first['verification'], 'discovery_only')
        self.assertFalse(first.get('claim_agreement', False))
        # Deterministik: aynı girdi aynı kümeyi üretir.
        again = news_pipeline.cluster(list(clustered))
        self.assertEqual([row['event_cluster_id'] for row in again],
                         [row['event_cluster_id'] for row in clustered])

    def test_clustering_never_replaces_the_conflict_line(self):
        claims = [{'subject': 'deprem', 'scope': 'Elazığ', 'as_of': '2026-10-20', 'value': '4.5', 'url': AA},
                  {'subject': 'deprem', 'scope': 'Elazığ', 'as_of': '2026-10-20', 'value': '5.1', 'url': BBC}]
        self.assertEqual(research_providers.compare_sources(claims)['status'], 'conflict')


class DifferentHostTests(unittest.TestCase):
    """10. Aynı hosttan kopyalar bağımsız kanıt sayılmaz; #436 reuse edilir."""

    def test_only_host_distinct_rows_are_independent(self):
        rows = [{'url': AA + '/a'}, {'url': AA + '/b'}, {'url': BBC + '/c'}]
        chosen = news_pipeline.independent(rows)
        self.assertEqual([row['url'] for row in chosen], [AA + '/a', BBC + '/c'])
        self.assertIs(news_pipeline.independent, research_providers.independent_candidates)


class EvidenceReuseTests(unittest.TestCase):
    """I. Doğrulanmış evidence sonradan gelen model için yeniden tarama gerektirmez."""

    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_second_request_reuses_verified_evidence_without_network(self):
        reader, fetcher = two_source_feeds()
        sources = [{'name': 'AA', 'url': AA + '/tr/gundem'}, {'name': 'BBC Türkçe', 'url': BBC + '/turkce'}]
        first = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                  sources=sources, now=NOW, model_status='unavailable')
        reader2 = Mock(side_effect=AssertionError('yeniden keşif yapıldı'))
        fetcher2 = Mock(side_effect=AssertionError('yeniden fetch yapıldı'))
        second = news_pipeline.run('bunları özetle', reader=reader2, fetcher=fetcher2, sources=sources,
                                   now=NOW, reuse=first['verified'])
        reader2.assert_not_called()
        fetcher2.assert_not_called()
        self.assertEqual(second['reused'], len(first['verified']))
        self.assertEqual(second['news_status'], 'complete')

    def test_stale_reuse_is_not_presented_as_fresh_news(self):
        reader, fetcher = two_source_feeds()
        sources = [{'name': 'AA', 'url': AA + '/tr/gundem'}]
        first = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                  sources=sources, now=DAY)
        later = news_pipeline.run('güncel deprem haberleri', reader=Mock(side_effect=AssertionError('ağ yok')),
                                  fetcher=Mock(side_effect=AssertionError('ağ yok')), sources=sources,
                                  reuse=first['verified'], now=DAY + timedelta(days=40))
        self.assertNotEqual(later['news_status'], 'complete')


class SynthesisAccuracyTests(unittest.TestCase):
    """J ve 17. Modelin uydurduğu sayı/alıntı factual kabul edilmez; güvenli downgrade."""

    def test_unsupported_number_is_dropped_from_the_briefing(self):
        evidence = [{'news_article': {'url': AA + '/tr/gundem/deprem-1', 'title': 'AA deprem haberi',
                                      'published': '2026-10-20', 'text': 'Ekipler 120 kişiye ulaştı.'}}]
        supported = 'Ekipler 120 kişiye ulaştı. Kaynak: ' + AA
        checked = news_pipeline.verify_synthesis(supported, evidence)
        self.assertTrue(checked['ok'])
        self.assertEqual(checked['unsupported_numbers'], [])
        invented = 'Ekipler 4500 kişiye ulaştı. Ayrıca 120 kişi tahliye edildi.'
        downgraded = news_pipeline.verify_synthesis(invented, evidence)
        self.assertFalse(downgraded['ok'])
        self.assertEqual(downgraded['unsupported_numbers'], ['4500'])
        self.assertNotIn('4500', downgraded['text'])
        self.assertIn('120', downgraded['text'])

    def test_quote_absent_from_evidence_is_not_shown_as_a_quote(self):
        evidence = [{'news_article': {'url': AA + '/x', 'title': 'Başlık', 'published': '2026-10-20',
                                      'text': 'Yetkililer çalışmaların sürdüğünü belirtti.'}}]
        result = news_pipeline.verify_synthesis('"Valizler hazır, herkes sahada." dedi', evidence)
        self.assertFalse(result['ok'])
        self.assertNotIn('Valizler', result['text'])
        self.assertIn('Model tabanlı sentez doğrulanamadı', result['text'])


class FailureSemanticsTests(unittest.TestCase):
    """19. model_synthesis_status, news_status'u ezmez."""

    def test_model_failure_never_marks_news_unavailable(self):
        status = news_pipeline.status(
            [{'source': 'AA', 'status': 'ok', 'item_count': 3, 'reason': None}],
            verified=[{'url': AA + '/x'}], model_status='unavailable')
        self.assertEqual(status['news_status'], 'complete')
        self.assertEqual(status['model_synthesis_status'], 'unavailable')

    def test_network_wipe_is_unavailable_not_empty(self):
        status = news_pipeline.status([{'source': 'AA', 'status': 'failed', 'item_count': 0, 'reason': 'dns'}],
                                      verified=[], model_status='unavailable')
        self.assertEqual(status['news_status'], 'unavailable')


class JobDeliveryTests(unittest.TestCase):
    """11, 15 ve 16. İş kanıtından deterministik teslim: sağlık listesi, yeniden kullanım, ağ yok."""

    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def job(self, reader, fetcher, *, day=DAY):
        from modules import task_results
        sources = [{'name': 'AA', 'url': AA_INDEX}, {'name': 'BBC Türkçe', 'url': BBC_INDEX}]
        result = news_pipeline.run('son 7 gün deprem haberleri', reader=reader, fetcher=fetcher,
                                   sources=sources, now=day)
        outputs = {}
        for index, row in enumerate(result['verified'], 1):
            outputs['s%d' % index] = task_results.seal('research', {
                'state': 'done', 'text': row['title'], 'source': row['url'],
                'source_chars': len(row['news_article']['text']), 'source_quotes': row['quotes'],
                'source_only': True, 'news_article': row['news_article']})
        steps = [{'id': 's%d' % index, 'tool': 'research', 'state': 'done',
                  'input': {'url': row['url'], 'question': 'deprem'}}
                 for index, row in enumerate(result['verified'], 1)]
        steps.append({'id': 's9', 'tool': 'data', 'state': 'failed',
                      'input': {'operation': 'headlines', 'url': DW + '/turkce'}})
        outputs['s9'] = {'state': 'failed', 'text': 'taklit kaynak zaman aşımı'}
        return {'owner': 'alice', 'request': 'son 7 gün deprem haberleri', 'state': 'paused',
                'goals': [], 'steps': steps, 'outputs': outputs}, result

    def test_attach_job_reports_source_health_without_a_second_crawl(self):
        reader, fetcher = two_source_feeds()
        job, result = self.job(reader, fetcher)
        crawl = Mock(side_effect=AssertionError('modelsiz teslim yeniden ağa çıkmadı'))
        with patch('modules.public_sources.fetch', crawl), patch('modules.domain_tools.headlines', crawl):
            news_pipeline.attach_job(job, model_status='unavailable', now=DAY)
            note = news_pipeline.delivery_note(job)
        crawl.assert_not_called()
        self.assertEqual(job['news_pipeline']['news_status'], 'partial')
        self.assertEqual(job['news_pipeline']['model_synthesis_status'], 'unavailable')
        self.assertEqual(job['news_pipeline']['articles_verified'], len(result['verified']))
        failed = [row for row in job['news_pipeline']['source_health'] if row['status'] == 'failed']
        self.assertEqual([row['url'] for row in failed], [DW + '/turkce'])
        self.assertIn('Model tabanlı sentez kullanılamıyor', note)
        self.assertIn('haber durumu', note.lower())

    def test_record_is_json_serialisable_and_bounded(self):
        import json
        reader, fetcher = two_source_feeds()
        job, _ = self.job(reader, fetcher)
        news_pipeline.attach_job(job, model_status='unavailable', now=DAY)
        encoded = json.dumps(job['news_pipeline'], ensure_ascii=False, sort_keys=True)
        self.assertLess(len(encoded), 20000)
        self.assertNotIn('news_article', job['news_pipeline'])
        self.assertTrue(job['news_pipeline']['report'].startswith('Son 7 günde'))

    def test_delivery_note_is_empty_without_a_pipeline_record(self):
        self.assertEqual(news_pipeline.delivery_note({'state': 'done'}), '')


class BoundaryTests(unittest.TestCase):
    """1 ve 2 numaralı bölüm: mevcut hatlar reuse ediliyor, yeniden kurulmuyor."""

    def test_article_verification_reuses_the_existing_reader(self):
        self.assertIs(news_pipeline.article_reader, research_evidence.article)

    def test_discovery_reuses_the_publisher_catalog_and_headlines(self):
        self.assertEqual([row['url'] for row in news_pipeline.catalog('son dakika haberleri')][:4], GENERAL[:4])
        self.assertTrue(hasattr(news_pipeline, 'headline_reader'))

    def test_pipeline_has_no_model_provider_or_secret_imports(self):
        import inspect
        source = inspect.getsource(news_pipeline)
        for forbidden in ('import llm', 'model_wait', 'smart_router', 'api_key', 'requests.post', 'tavily'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
