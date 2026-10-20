"""General news source scope and real reader chain, without external network/model."""
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from unittest.mock import patch
import unittest
from modules import publisher_news, goal_tools, goal_executor as goals
import test_goal_executor as fixture

GENERAL = ['https://www.aa.com.tr/tr/gundem', 'https://www.bbc.com/turkce',
           'https://www.dw.com/tr/', 'https://tr.euronews.com/']


class NewsSourceScopeTests(unittest.TestCase):
    def test_general_and_topical_news_use_general_publishers(self):
        for request in ('son dakika haberleri', 'Türkiye haberleri', 'deprem haberlerini araştır', 'yapay zekâ haberleri'):
            with self.subTest(request=request):
                self.assertEqual([r['url'] for r in publisher_news.sources_for(request)], GENERAL)
                self.assertEqual(publisher_news.recovery_indexes(request, []), GENERAL)

    def test_institution_scope_and_explicit_urls_are_not_broadened(self):
        self.assertEqual([r['url'] for r in publisher_news.sources_for('Üniversitelerin araştırma haberleri')], [r['url'] for r in publisher_news.SOURCES])
        seed = ['https://haberler.bogazici.edu.tr/']
        self.assertEqual(publisher_news.recovery_indexes('Boğaziçi Üniversitesi haberleri', seed), seed)
        self.assertEqual(publisher_news.recovery_indexes('Sadece https://example.org/haberler haberleri', ['https://example.org/haberler']), ['https://example.org/haberler'])

    def test_old_institution_seed_does_not_trap_general_news(self):
        self.assertEqual(publisher_news.recovery_indexes('son dakika haberleri', ['https://tubitak.gov.tr/tr/haberler']), GENERAL)

    def test_planner_receives_request_scoped_sources(self):
        rows = goal_tools.planner_catalog('son dakika haberleri')['known_news_sources']
        self.assertEqual([r['url'] for r in rows], GENERAL)
        self.assertTrue(all(r['live_connection_tested'] is False for r in rows))

    def test_registered_index_is_not_permission_to_invent_article_urls(self):
        self.assertEqual(publisher_news.candidate_url(GENERAL[0], 'son dakika haberleri', {}), GENERAL[0])
        with self.assertRaises(ValueError):
            publisher_news.candidate_url('https://www.aa.com.tr/tr/gundem/uydurulmus-haber/123', 'son dakika haberleri', {})
        with self.assertRaises(ValueError):
            publisher_news.candidate_url('https://127.0.0.1/story', 'son dakika haberleri', {})

    def run_recovery(self, *, same_publisher=False, stale=False, fail_first=False):
        case = fixture.GoalTests();case.setUp();self.addCleanup(case.doCleanups)
        day = (datetime.now(timezone(timedelta(hours=3))).date() - timedelta(days=20 if stale else 0)).isoformat()
        case.responses(case.plan('Güncel haberleri araştır'), RuntimeError('Taklit sağlayıcı kullanılamıyor'))
        fetched = []
        def fetch(url):
            fetched.append(url)
            if url in GENERAL:
                if fail_first and url == GENERAL[0]:
                    raise OSError('Taklit kaynak erişim hatası')
                if same_publisher and url != GENERAL[0]:
                    return {'url': url, 'body': b'<p>Okunabilir haber yok</p>'}
                return {'url': url, 'body': b'<a href="/story/one">Son dakika deprem haberi bir</a><a href="/story/two">Son dakika deprem haberi iki</a>'}
            host = urlsplit(url).hostname
            if not any(host == urlsplit(index).hostname for index in GENERAL):
                raise AssertionError('Beklenmeyen kaynak: '+url)
            text = ('Deprem sonrası ilgili kurumlar sahadaki incelemelerin sonuçlarını kamuoyuna açıkladı. '
                    'Bölgedeki ekipler çalışmalarını sürdürürken yetkililer doğrulanmış yeni bilgileri paylaştı. '
                    'Kullanıcının isteğine ilişkin ayrıntılar haberin kendi metninde yer alıyor.')
            body = f'<article><h1>{host} deprem haberi</h1><time itemprop="datePublished" datetime="{day}"></time><p>{text}</p></article>'
            return {'url':url,'body':body.encode()}
        with patch('modules.public_sources.fetch', side_effect=fetch), patch('modules.privacy.blocked', return_value=None):
            reply = goals.run(case.runtime, 'son dakika deprem haberleri')
        self.assertEqual(case.ask.call_count, 2)
        self.assertLessEqual(sum(bool(s.get('recovery')) for s in goals.latest('alice')['steps']), 10)
        return goals.latest('alice'), fetched, reply

    def test_provider_failure_recovers_real_dated_articles_from_two_publishers(self):
        job, fetched, reply = self.run_recovery()
        self.assertEqual(job['state'], 'done', reply)
        self.assertIn(GENERAL[0], fetched);self.assertIn(GENERAL[1], fetched)
        articles = [o['news_article'] for o in job['outputs'].values() if o.get('news_article')]
        self.assertGreaterEqual(len({publisher_news.publisher_key(a['url']) for a in articles}), 2)
        self.assertTrue(all('source_quotes' in o for o in job['outputs'].values() if o.get('news_article')))

    def test_two_articles_from_one_publisher_do_not_complete_general_news(self):
        job, _, _ = self.run_recovery(same_publisher=True)
        self.assertNotEqual(job['state'], 'done')
        self.assertTrue(all(g['state'] != 'done' for g in job['goals']))

    def test_stale_articles_do_not_complete_latest_news(self):
        job, _, _ = self.run_recovery(stale=True)
        self.assertNotEqual(job['state'], 'done')

    def test_failed_first_publisher_does_not_prevent_two_other_publishers(self):
        job, fetched, reply = self.run_recovery(fail_first=True)
        self.assertEqual(job['state'], 'done', reply)
        self.assertIn(GENERAL[2], fetched)
