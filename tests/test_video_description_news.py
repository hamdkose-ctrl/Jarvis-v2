"""Video-page written descriptions: explicit identity/date binding, never video viewing."""
import json
import unittest
from unittest.mock import patch
from modules import model_free_news, research_evidence as evidence, research_delivery, task_results


class VideoDescriptionNewsTests(unittest.TestCase):
    url='https://example.org/software-story--123'
    title='Yapay zekâ ile yazılım araştırması'
    paragraph='Yapay zekâ ile geliştirilen açık kaynak uygulamalarının kapsamı bu sayfanın yazılı açıklamasında anlatılıyor. Bu açıklama videonun tamamının dökümü değildir.'

    def response(self, *, canonical=None, schema=None, extra='', body=None):
        metadata={'@type':'VideoObject','name':self.title,'url':self.url,'uploadDate':'2026-10-18T12:01:20+03:00'}
        if schema is not None:metadata=schema
        html=('<html><head><link rel="canonical" href="'+(canonical or self.url)+'">'
              '<meta property="og:type" content="article"><script type="application/ld+json">'+json.dumps({'@graph':[metadata]},ensure_ascii=False)+
              '</script></head><body><main><div><h1>'+self.title+'</h1></div><article id="123-content">'
              '<div><p>Yazar kartı</p><a href="/other">İlgisiz yazar haberi</a></div>'+
              (body if body is not None else '<section id="123-text"><p>'+self.paragraph+'</p></section>')+
              '</article>'+extra+'</main></body></html>')
        return {'url':self.url,'body':html.encode()}

    def test_single_video_description_binds_sibling_title_and_upload_date(self):
        article=evidence.article(self.response())
        self.assertEqual(article['title'],self.title);self.assertEqual(article['published'],'2026-10-18')
        self.assertEqual(article['kind'],'video_description');self.assertIn(self.paragraph,article['text'])
        self.assertNotIn('Yazar kartı',article['text']);self.assertNotIn('İlgisiz',article['text'])

    def test_foreign_identity_missing_date_and_modified_date_are_not_publication_proof(self):
        base={'@type':'VideoObject','name':self.title,'url':self.url,'uploadDate':'2026-10-18'}
        cases=[self.response(canonical='https://example.org/other'),
               self.response(schema={**base,'url':'https://example.org/other'}),
               self.response(schema={**base,'name':'Başka video'}),
               self.response(schema={k:v for k,v in base.items() if k!='uploadDate'}),
               self.response(schema={**{k:v for k,v in base.items() if k!='uploadDate'},'dateModified':'2026-10-20'}),
               self.response(schema={**base,'uploadDate':'2026-02-31'}),
               self.response(schema={k:v for k,v in base.items() if k!='uploadDate'},
                             body='<meta itemprop="datePublished" content="2026-10-20"><section><p>'+self.paragraph+'</p></section>')]
        for response in cases:
            with self.subTest(response=response),self.assertRaises(ValueError):evidence.article(response)

    def test_ambiguous_or_missing_written_body_is_rejected(self):
        for response in (self.response(extra='<article><p>İlgili kart</p></article>'),
                         self.response(body='<section><p>Kısa</p></section>'),
                         self.response(body='<section><p>'+self.paragraph+'</p></section><section><p>'+self.paragraph+'</p></section>')):
            with self.subTest(response=response),self.assertRaises(ValueError):evidence.article(response)

    def test_missing_canonical_or_multiple_video_objects_are_rejected(self):
        response=self.response()
        for body in (response['body'].replace(('<link rel="canonical" href="'+self.url+'">').encode(),b''),
                     response['body'].replace(b'</script>',b'</script><script type="application/ld+json">{"@type":"VideoObject","name":"Other"}</script>')):
            with self.subTest(body=body),self.assertRaises(ValueError):evidence.article({**response,'body':body})

    def test_receipt_chat_and_report_identify_written_description_not_video_viewing(self):
        with patch('modules.public_sources.fetch',return_value=self.response()),patch('modules.privacy.blocked',return_value=None):
            output=model_free_news.run('alice',{'url':self.url},'2026 yapay zekâ haberleri',source_only=True)
        self.assertTrue(task_results.verify(output));self.assertEqual(evidence.news_receipt(output)['kind'],'video_description')
        for text in (evidence.preview(output),evidence.news_report({'r':output}),research_delivery.synthesize(output,'haberleri')['text']):
            self.assertIn('Video izlenmedi',text);self.assertIn('yazılı açıklama',text)
        invalid={**output,'news_article':{**output['news_article'],'kind':'watched_video'}}
        with self.assertRaises(ValueError):evidence.news_receipt(invalid)
