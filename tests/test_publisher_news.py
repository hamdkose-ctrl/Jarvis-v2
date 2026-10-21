import unittest
from modules import publisher_news as p

class PublisherNewsTests(unittest.TestCase):
    def test_general_recovery_replaces_old_guessed_paths_with_real_indexes(self):
        seeds=['https://tubitak.gov.tr/tr/bilim-kalkinimi/yapay-zeka','https://www.veri']
        result=p.recovery_indexes('Türkiye yapay zekâ gelişmelerini araştır',seeds)
        self.assertEqual(result[0],'https://www.mynet.com/haber/')
        self.assertEqual(set(result),{'https://www.mynet.com/haber/','https://tr.investing.com/news/','https://www.aa.com.tr/tr/gundem','https://www.trthaber.com/','https://www.ntv.com.tr/'})
        self.assertNotIn(seeds[0],result)

    def test_actual_discovery_or_user_url_required_for_article(self):
        url='https://example.org/news/ai'
        with self.assertRaises(ValueError):p.candidate_url(url,'Türkiye haberleri',{})
        with self.assertRaises(ValueError):p.candidate_url(url,'Türkiye haberleri',{'s1':{'state':'failed','source':url}})
        outputs={'s1':{'state':'done','structured':{'items':[{'title':'Yapay zeka','url':url}]}}}
        self.assertEqual(p.candidate_url(url,'Türkiye haberleri',outputs),url)
        self.assertEqual(p.candidate_url(url,'Şu kaynağı oku: '+url,{}),url)
    url='https://www.yildiz.edu.tr/universite/haberler/proje'
    def page(self,canonical=None,stamp='14 Ekim 2026 Çarşamba 09:37',extra=''):
        body=f'''<link rel="canonical" href="{canonical or self.url}"><h1>Yeni proje</h1>
        <div id="block-ytu-content"><article class="modern-news-article">
        <header class="mn-header"><h1 class="mn-title">Yeni proje</h1><span class="mn-meta-date">{stamp}</span></header>
        <div class="mn-body"><p>Üniversite yapay zekâ araştırma projesini bilimsel sonuçlarıyla birlikte kamuoyuna duyurdu. Çalışmanın ayrıntıları açıklandı.</p>{extra}</div>
        </article></div><aside><time>2099-01-01</time></aside>'''
        return {'url':self.url,'body':body.encode()}
    def test_own_date_and_body_exclude_related_cards(self):
        result=p.article(self.page());self.assertEqual(result['published'],'2026-10-14')
        self.assertNotIn('2099',result['text']);self.assertNotIn('09:37',result['text'])
    def test_wrong_identity_invalid_date_and_nested_card_rejected(self):
        for response in [self.page(canonical='https://evil.org/proje'),self.page(stamp='31 Şubat 2026'),self.page(extra='<article>Başka haber</article>')]:
            with self.subTest(response=response),self.assertRaises(ValueError):p.article(response)
    def test_unknown_publisher_does_not_gain_layout_exception(self):
        response=self.page();response['url']='https://example.org/universite/haberler/proje'
        self.assertIsNone(p.article(response))
    def test_navigation_does_not_consume_story_limit(self):
        nav=''.join(f'<a href="/nav/{i}">Menu {i}</a>' for i in range(60))
        result=p.listing({'url':'https://haber.dpu.edu.tr/','body':(nav+'<a href="/tr/haber_oku/abc/proje">Proje</a>').encode()})
        self.assertNotIn(b'Menu',result['body']);self.assertIn(b'Proje',result['body'])
    def test_exclusive_source_never_broadens(self):
        seeds=['https://example.org/haberler']
        self.assertEqual(p.recovery_indexes('Sadece Türkiye üniversite haberleri',seeds),seeds)
        self.assertEqual(p.recovery_indexes('Türkiye yapay zekâ haberleri',[]),[s['url'] for s in p.sources_for('Türkiye haberleri')[:5]])

    def test_named_university_keeps_its_own_scope_without_exclusive_word(self):
        seeds=['https://haberler.bogazici.edu.tr/']
        self.assertEqual(p.recovery_indexes('Boğaziçi Üniversitesi yapay zekâ haberleri',seeds),seeds)
        self.assertEqual(p.recovery_indexes('Türkiye Boğaziçi Üniversitesi haberleri',[]),[])
        self.assertEqual(p.recovery_indexes('Türkiye haberleri',seeds),[s['url'] for s in p.sources_for('Türkiye haberleri')[:5]])
        self.assertEqual(p.recovery_indexes('Türkiye Ankara Üniversitesi yapay zekâ haberleri',[]),[])
