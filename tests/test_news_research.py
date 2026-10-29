"""Single article/date proof and deterministic report; no live network/model."""
import copy
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from modules import research_evidence as evidence, task_agents, task_results, nxapi, llm


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        self.url='https://example.org/duyuru/yapay-zeka-projesi'
        self.quote='Üniversitenin yapay zekâ araştırma projesi kamuoyuna duyuruldu.'
        self.html='<html><body><nav>Yapay Zeka Destek Akademik Ulusal destek programları</nav><article><h1>Yapay zekâ projesi</h1><time itemprop="datePublished" datetime="'+self.day+'"></time><p>'+self.quote+' Araştırma ekibi bilimsel sonuçları paylaştı.</p></article></body></html>'
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)
        p=patch.object(nxapi,'FILES_DIR',Path(self.tmp.name));p.start();self.addCleanup(p.stop)

    def response(self,html=None,url=None):return {'url':url or self.url,'body':(html or self.html).encode(),'content_type':'text/html'}

    def research(self):
        # Untrusted model prose invents a date and event. Only its matching quote survives.
        answer=json.dumps({'supported':True,'answer':'14 Ekim 1999 tarihinde uçan araba üretildi.','quotes':[self.quote]})
        with patch('modules.public_sources.fetch',return_value=self.response()),patch('modules.model_wait.ask',return_value=answer),patch('modules.privacy.blocked',return_value=None):
            return task_agents.worker('alice',{'agent':'research','input':{'url':self.url},'execution':{'request':'Son yapay zekâ gelişmelerini araştır'}},{})

    def test_index_page_with_other_news_date_is_rejected_before_model(self):
        html='<h1>Haberler</h1><article><time itemprop="datePublished" datetime="'+self.day+'"></time>'+self.quote+'</article>'
        for url in ['https://example.org/haberler','https://example.org/listing']:
            with self.subTest(url=url),patch('modules.public_sources.fetch',return_value=self.response(html,url)),patch('modules.model_wait.ask') as model,patch('modules.privacy.blocked',return_value=None):
                with self.assertRaises(ValueError):task_agents.worker('alice',{'agent':'research','input':{'url':url,'question':'Son haberler?'}},{})
                model.assert_not_called()

    def test_article_requires_own_published_date_not_modified_or_other_card(self):
        for html in [self.html.replace('<time itemprop="datePublished" datetime="'+self.day+'"></time>',''),
                     self.html.replace('<time itemprop="datePublished" datetime="'+self.day+'"></time>','<meta itemprop="dateModified" content="'+self.day+'">'),
                     self.html.replace('</article>','<time itemprop="datePublished" datetime="2000-01-01"></time></article>')]:
            with self.subTest(html=html),self.assertRaises(ValueError):evidence.article(self.response(html))

    def test_metadata_published_date_and_navigation_exclusion(self):
        html=self.html.replace('<time itemprop="datePublished" datetime="'+self.day+'"></time>','<meta property="article:published_time" content="'+self.day+'T10:00:00+03:00">')
        result=evidence.article(self.response(html))
        self.assertEqual(result['published'],self.day)
        self.assertNotIn('Akademik',result['text'])

    def test_unrelated_card_and_jsonld_dates_cannot_date_an_undated_article(self):
        undated=self.html.replace('<time itemprop="datePublished" datetime="'+self.day+'"></time>','')
        additions=['<aside><meta itemprop="datePublished" content="'+self.day+'"></aside>',
                   '<script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','headline':'Başka haber','datePublished':self.day})+'</script>',
                   '<script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','headline':'Yapay zekâ projesi','url':'https://example.org/other','datePublished':self.day})+'</script>']
        for added in additions:
            with self.subTest(added=added),self.assertRaises(ValueError):evidence.article(self.response(undated+added))

    def test_matching_article_jsonld_can_supply_published_date(self):
        undated=self.html.replace('<time itemprop="datePublished" datetime="'+self.day+'"></time>','')
        schema={'@type':'NewsArticle','headline':'Yapay zekâ projesi','url':self.url,'datePublished':self.day}
        result=evidence.article(self.response(undated+'<script type="application/ld+json">'+json.dumps(schema)+'</script>'))
        self.assertEqual(result['published'],self.day)

    def tubitak_page(self):
        url='https://tubitak.gov.tr/tr/haber/yapay-zeka-projesi'
        html=('<html><head><link rel="canonical" href="'+url+'"></head><body><div class="region-content">'
              '<div id="block-feza-gursey-page-title"><h1>Yapay zekâ projesi</h1></div>'
              '<div id="block-feza-gursey-content"><article><div class="node-date">21 Ağu 2026</div><p>'+self.quote+
              ' Araştırmanın bilimsel ayrıntıları kamuoyuyla paylaşıldı.</p></article></div></div>'
              '<aside><time itemprop="datePublished" datetime="2026-10-14"></time></aside></body></html>')
        return url,html

    def test_tubitak_sibling_title_and_own_turkish_date_are_bound_to_canonical_article(self):
        url,html=self.tubitak_page();result=evidence.article(self.response(html,url))
        self.assertEqual(result['published'],'2026-08-21');self.assertEqual(result['title'],'Yapay zekâ projesi')
        self.assertIn(self.quote,result['text']);self.assertNotIn('2026-10-14',result['text'])

    def test_tubitak_layout_does_not_exempt_foreign_canonical_or_multiple_articles(self):
        url,html=self.tubitak_page()
        variants=[(url,html.replace('href="'+url+'"','href="https://tubitak.gov.tr/tr/haber/other"')),
                  ('https://example.org/tr/haber/yapay-zeka-projesi',html),
                  (url,html.replace('</article>','</article><article><p>Other card</p></article>')),
                  (url,html.replace('class="region-content"','class="listing"'))]
        for target,page in variants:
            with self.subTest(target=target,page=page),self.assertRaises(ValueError):evidence.article(self.response(page,target))

    def test_tubitak_related_date_does_not_replace_missing_or_ambiguous_own_date(self):
        url,html=self.tubitak_page()
        for page in [html.replace('class="node-date"','class="unlabelled"'),
                     html.replace('21 Ağu 2026','31 Şub 2026'),
                     html.replace('</article>','<div class="node-date">22 Ağu 2026</div></article>')]:
            with self.subTest(page=page),self.assertRaises(ValueError):evidence.article(self.response(page,url))

    def test_notify_phrase_and_mail_or_finance_dependencies_do_not_become_news_reports(self):
        self.assertFalse(evidence.news_requested('Rapor hazır olunca haber ver'))
        self.assertFalse(evidence.news_requested('Haberleşme uygulamasını incele'))
        mail={'snapshot':{'operation':'read_message'}}
        self.assertFalse(evidence.news_report_requested('Son haberleri araştır ve mailime cevap yaz','Cevap taslağı',{'s1':mail}))
        self.assertFalse(evidence.news_report_requested('Haberleri araştır ve finans raporu yaz','Finans CSV raporu',{'s1':{'local_evidence':'data'}}))

    def test_future_and_out_of_range_dates_are_not_current_news(self):
        today=datetime.fromisoformat(self.day).date()
        for day in [today+timedelta(days=1),today-timedelta(days=91)]:
            with self.assertRaises(ValueError):evidence.news_date(day.isoformat(),'Son 30 gün; yetmezse son 90 güne genişlet')
        evidence.news_date((today-timedelta(days=60)).isoformat(),'Son 30 gün; yetmezse son 90 güne genişlet')

    def test_weekly_default_keeps_seven_days_and_longer_ranges_require_explicit_request(self):
        today=datetime.fromisoformat(self.day).date()
        for request in ['Son haberleri araştır','Güncel yapay zekâ gelişmeleri','Haftalık gündem','Bu hafta haberler','Yapay zekâ haberlerini araştır ve rapor dosyası oluştur','Gündemi araştır']:
            evidence.news_date((today-timedelta(days=7)).isoformat(),request)
            with self.subTest(request=request),self.assertRaises(ValueError):evidence.news_date((today-timedelta(days=8)).isoformat(),request)
        evidence.news_date((today-timedelta(days=29)).isoformat(),'Son 30 gün haberleri')
        self.assertIsNone(evidence.news_window('2020 haberlerini araştır'))

    def test_model_question_cannot_expand_user_weekly_date_window(self):
        old=(datetime.fromisoformat(self.day).date()-timedelta(days=8)).isoformat()
        task={'agent':'research','input':{'url':self.url,'question':'Son 90 gün haberlerinden alıntı ver'},'execution':{'request':'Son 7 gün haberlerini araştır','source_only':True}}
        with patch('modules.public_sources.fetch',side_effect=lambda *_:self.response(self.html.replace(self.day,old))),patch('modules.privacy.blocked',return_value=None),patch('modules.model_wait.ask') as model:
            with self.assertRaises(ValueError):task_agents.worker('alice',task,{})
        model.assert_not_called()

    def test_weekly_completion_rechecks_previously_verified_article_age(self):
        from modules import goal_executor
        output=self.research()
        job={'request':'Haftalık yapay zekâ haberlerini araştır','steps':[{'id':'s1','tool':'research','depends':[]}],'outputs':{'s1':output}}
        goal={'text':'Haberleri araştır'}
        future=datetime.now(timezone(timedelta(hours=3)))+timedelta(days=8)
        with patch('datetime.datetime') as clock:
            clock.now.return_value=future
            with self.assertRaises(ValueError):goal_executor._check_news_completion(job,goal,['s1'])

    def test_report_uses_only_article_date_links_and_quotes_without_writer_model(self):
        source=self.research()
        self.assertNotIn('1999',source['text']);self.assertNotIn('uçan araba',source['text'])
        with patch('modules.model_wait.ask',side_effect=AssertionError('Writer must not call a model')):
            result=task_agents.worker('alice',{'agent':'writer','input':{'instruction':'Tarihli haber raporu yaz','filename':'rapor.md'},'execution':{'request':'Son gelişmeleri araştır ve rapor dosyası oluştur'}},{'s1':source})
        text=Path(result['file']).read_text(encoding='utf-8')
        self.assertIn('Yayın tarihi: '+self.day,text);self.assertIn('<'+self.url+'>',text)
        self.assertIn(self.quote,text);self.assertNotIn('[[https',text);self.assertNotIn('1999',text)
        self.assertTrue(task_results.verify(result,owner='alice'))
        # Even a self-consistent changed file/hash cannot alter the evidence-bound report.
        import hashlib
        bad=copy.deepcopy(result);bad['text']=text+'\nUydurma haber';Path(bad['file']).write_text(bad['text'],encoding='utf-8');bad['sha256']=hashlib.sha256(Path(bad['file']).read_bytes()).hexdigest()
        with self.assertRaises(ValueError):task_results.verify(bad,owner='alice')

    def test_generic_headlines_or_legacy_research_cannot_be_news_report_evidence(self):
        with self.assertRaises(ValueError):evidence.news_report({'s1':{'state':'done','text':'Kategori sayfası özeti','source':self.url}})

    def test_menu_quote_cannot_be_article_evidence(self):
        answer=json.dumps({'supported':True,'answer':'Destek programı var.','quotes':['Yapay Zeka Destek Akademik Ulusal destek programları']})
        with patch('modules.public_sources.fetch',return_value=self.response()),patch('modules.model_wait.ask',return_value=answer),patch('modules.privacy.blocked',return_value=None):
            with self.assertRaises(ValueError):task_agents.worker('alice',{'agent':'research','input':{'url':self.url,'question':'Son gelişmeler?'}},{})

    def test_model_free_ai_quote_must_be_in_body_and_other_topics_are_not_inferred(self):
        article={'title':'Yapay zekâ haberleri','text':'Yapay zekâ haberleri Bu yazı yalnız futbol sonuçlarını içermektedir.'}
        from modules import model_free_news
        with self.assertRaises(ValueError):model_free_news.quotes(article,'Yapay zekâ son gelişmeleri')
        with self.assertRaises(ValueError):model_free_news.quotes(article,'Son finans haberleri')

