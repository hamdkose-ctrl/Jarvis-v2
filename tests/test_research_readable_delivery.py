"""Shared research presentation and semantic body extraction, without live services."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import unittest
from modules import browser, goal_executor, public_sources, research_evidence


class ResearchReadableDeliveryTests(unittest.TestCase):
    body = ('Araştırmacılar deney sonuçlarını açıkladı. Yeni yöntem enerji tüketimini azaltırken '
            'ölçüm doğruluğunu korudu ve sonuçlar bağımsız bir deneyde yeniden sınandı.')

    def html(self):
        day=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        return ('<html><body><div role="navigation">Favoriler ve oyunlar</div><article>'
                '<div>Haberler Teknoloji Eski menü</div><h1>Yeni yöntem</h1>'
                '<time itemprop="datePublished" datetime="'+day+'"></time>'
                '<button>Google tercihlerinize ekleyin</button><p>'+self.body+'</p>'
                '<aside>Reklam ve ilgili kartlar</aside></article></body></html>')

    def test_general_page_and_dated_article_share_body_cleanup(self):
        response={'url':'https://example.org/method','body':self.html().encode()}
        with patch.object(public_sources,'fetch',return_value=response) as fetch, \
             patch.object(browser.requests,'get',side_effect=AssertionError('unguarded HTTP reader')), \
             patch('modules.privacy.blocked',return_value=None):
            general=browser.page_text(response['url'])
        fetch.assert_called_once_with(response['url'])
        dated=research_evidence.article({'url':'https://example.org/story','body':self.html().encode()})
        for text in (general,dated['text'],public_sources.text(self.html().encode())):
            with self.subTest(text=text):
                self.assertIn(self.body,text)
                for junk in ('Favoriler','Eski menü','Google tercihlerinize','Reklam ve ilgili'):
                    self.assertNotIn(junk,text)

    def test_plain_and_table_pages_do_not_need_news_metadata(self):
        self.assertIn('Sadece düz metin',public_sources.text(b'Sadece d\xc3\xbcz metin'))
        self.assertIn(self.body,public_sources.text(('<main><div>'+self.body+'</div></main>').encode()))
        table=b'<main><h1>Measurements</h1><table><tr><td>Voltage</td><td>12 V</td></tr></table><pre>x = 12</pre></main>'
        text=public_sources.text(table)
        self.assertIn('Voltage',text);self.assertIn('12 V',text);self.assertIn('x = 12',text)

    def test_article_preview_is_structured_and_does_not_dump_raw_text(self):
        source={'url':'https://example.org/story','title':'Yeni yöntem','published':'2026-10-20','text':self.body}
        output={'news_article':source,'text':'HAM İNDEKS VE MENÜLER','source_quotes':[self.body]}
        text=research_evidence.preview(output)
        self.assertIn('Yeni yöntem',text);self.assertIn('2026-10-20',text)
        self.assertIn(self.body,text);self.assertIn('Kaynak: '+source['url'],text)
        self.assertNotIn('HAM İNDEKS',text)

    def test_general_research_hides_discovery_but_keeps_findings_and_file(self):
        job={'request':'Enerji tüketimini araştır','state':'done','steps':[
            {'id':'d','tool':'data','input':{'operation':'headlines'}},
            {'id':'r','tool':'research','input':{}},
            {'id':'w','tool':'writer','input':{}}],
            'goals':[{'text':'Enerji tüketimini araştır','state':'done','evidence':['d','r','r','w']}],
            'outputs':{'d':{'state':'done','text':'Favoriler ve oyunlar: KEŞİF DÖKÜMÜ'},
                       'r':{'state':'done','source':'https://example.org/method','text':'Doğrulanmış enerji bulgusu.\nKaynak: https://example.org/method'},
                       'w':{'state':'done','file':'report.md','text':'Rapor hazır'}}}
        text=goal_executor.render(job)
        self.assertNotIn('KEŞİF DÖKÜMÜ',text)
        self.assertEqual(text.count('Doğrulanmış enerji bulgusu'),1)
        self.assertIn('Dosya: report.md',text)
        job['goals'][0]['evidence']=['d']
        self.assertIn('KEŞİF DÖKÜMÜ',goal_executor.render(job))

    def test_general_research_keeps_complete_source_after_bounded_answer(self):
        url='https://example.org/'+('x'*1300)
        output={'source':url,'text':('Enerji ölçümleri açıklandı. '*100)+'\nKaynak: '+url}
        text=research_evidence.preview(output)
        self.assertIn('Enerji ölçümleri',text)
        self.assertIn('Kaynak: '+url,text)
        self.assertEqual(text.count(url),1)
        self.assertLess(len(text),len(output['text']))
