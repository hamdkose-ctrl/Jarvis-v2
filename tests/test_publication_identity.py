"""Schema identity regression shapes from live publisher diagnostics; no copied page body."""
import json,unittest
from modules import research_evidence

class PublicationIdentityTests(unittest.TestCase):
    url='https://example.org/story'
    body='Türkiye yapay zekâ araştırmasının sonuçları Ankara merkezindeki uzmanlar tarafından kamuoyuna ayrıntılarıyla açıklandı.'
    def page(self,*,canonical=True,foreign=False,anchor=True,named_date=False,modified_only=False):
        schema={'@type':'NewsArticle','headline':'SEO başlığı farklıdır',
                'mainEntityOfPage':{'url':'https://other.example/story' if foreign else self.url},
                'articleBody':self.body if anchor else 'Bağımsız başka bir sayfadan alınmış ve bu sayfada bulunmayan yeterince uzun bir haber metni.'}
        if not named_date and not modified_only:schema['datePublished']='2026-10-28T12:00:00+03:00'
        if modified_only:schema['dateModified']='2026-10-28T12:00:00+03:00'
        meta='<meta name="datePublished" content="2026-10-28T12:00:00+03:00">' if named_date else ''
        if named_date:schema={}
        html=('<html><head>'+('<link rel="canonical" href="'+self.url+'">' if canonical else '')+
              meta+'<script type="application/ld+json">'+json.dumps(schema)+'</script></head>'+
              '<body><article><h1>Görünür haber başlığı</h1><p>'+self.body+'</p></article></body></html>')
        return {'url':self.url,'body':html.encode()}
    def test_url_object_canonical_and_body_bind_different_seo_title(self):
        self.assertEqual(research_evidence.article(self.page())['published'],'2026-10-28')
    def test_foreign_page_identity_is_not_accepted(self):
        with self.assertRaises(ValueError):research_evidence.article(self.page(foreign=True))
    def test_title_mismatch_requires_canonical(self):
        with self.assertRaises(ValueError):research_evidence.article(self.page(canonical=False))
    def test_title_mismatch_requires_literal_dom_body_anchor(self):
        with self.assertRaises(ValueError):research_evidence.article(self.page(anchor=False))
    def test_named_date_published_is_read(self):
        self.assertEqual(research_evidence.article(self.page(named_date=True))['published'],'2026-10-28')
    def test_modified_date_never_substitutes_for_publication(self):
        with self.assertRaises(ValueError):research_evidence.article(self.page(modified_only=True))
