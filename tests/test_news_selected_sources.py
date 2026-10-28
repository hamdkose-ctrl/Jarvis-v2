"""User-selected Turkish discovery indexes; no live network or model calls."""
import unittest
from modules import goal_tools, publisher_news


SELECTED = {
    'NTV': 'https://www.ntv.com.tr/',
    'T24': 'https://t24.com.tr/',
    'Bloomberg HT': 'https://www.bloomberght.com/',
    'Ekonomim': 'https://www.ekonomim.com/',
    'KAP': 'https://www.kap.org.tr/tr/',
    'DonanımHaber': 'https://www.donanimhaber.com/',
    'Webtekno': 'https://www.webtekno.com/',
    'TRT Haber': 'https://www.trthaber.com/',
}


class SelectedNewsSourcesTests(unittest.TestCase):
    def test_selected_sources_reach_planner_and_bounded_recovery(self):
        rows = goal_tools.planner_catalog('Türkiye haberleri')['known_news_sources']
        by_name = {row['name']: row for row in rows}
        for name, url in SELECTED.items():
            with self.subTest(name=name):
                if name=='KAP':
                    self.assertNotIn(name,by_name)
                    continue
                self.assertIn(name, by_name)
                self.assertEqual(by_name[name]['url'], url)
                self.assertFalse(by_name[name]['live_connection_tested'])
                recovered = publisher_news.recovery_indexes('Türkiye haberleri', [url])
                self.assertEqual(recovered[0], url)
                self.assertLessEqual(len(recovered), 4)
                self.assertEqual(publisher_news.candidate_url(url, 'Türkiye haberleri', {}), url)
                with self.assertRaises(ValueError):
                    publisher_news.candidate_url(url+'uydurulmus-haber', 'Türkiye haberleri', {})

    def test_kap_is_labelled_as_primary_company_disclosures(self):
        rows = goal_tools.planner_catalog('şirket haberleri')['known_news_sources']
        kap = next(row for row in rows if row['name']=='KAP')
        self.assertEqual(kap['scope'], 'Resmî şirket açıklamaları; genel haber bülteni değildir')

    def test_english_only_candidates_and_dpu_are_not_registered(self):
        urls = {row['url'] for row in publisher_news.sources_for('son dakika haberleri')}
        self.assertTrue((set(SELECTED.values())-{'https://www.kap.org.tr/tr/'}).issubset(urls))
        for host in ('reuters.com', 'apnews.com', 'techcrunch.com', 'haber.dpu.edu.tr'):
            self.assertFalse(any(host in url for url in urls), host)
        self.assertEqual(publisher_news.catalog_keys('Türkiye haberleri'),
                         {'mynet.com','investing.com','aa.com.tr','bbc.com'})
