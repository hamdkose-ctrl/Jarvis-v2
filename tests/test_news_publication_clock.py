import json,unittest
from modules import research_evidence as evidence

class PublicationClock(unittest.TestCase):
    def page(self,published='2026-10-29T09:15:00+03:00',modified=None,meta=None):
        schema={'@type':'NewsArticle','headline':'Actual headline','datePublished':published}
        if modified:schema['dateModified']=modified
        html='<script type="application/ld+json">'+json.dumps(schema)+'</script>'
        if meta:html+='<meta property="article:published_time" content="'+meta+'">'
        html='<html><head>'+html+'</head><body><article><h1>Actual headline</h1><p>'+('Actual source sentence. '*20)+'</p></article></body></html>'
        return {'url':'https://example.com/story','body':html.encode()}
    def test_clock_survives_real_parser(self):
        article=evidence.article(self.page())
        self.assertEqual(article['published_at'],'2026-10-29T09:15:00+03:00')
    def test_modified_does_not_replace_publication(self):
        article=evidence.article(self.page(modified='2026-10-29T10:00:00+03:00'))
        self.assertEqual(article['published_at'],'2026-10-29T09:15:00+03:00')
    def test_naive_or_day_only_does_not_invent_clock(self):
        for value in ['2026-10-29','2026-10-29T09:15:00']:
            self.assertNotIn('published_at',evidence.article(self.page(published=value)))
    def test_conflicting_clocks_not_presented_as_exact(self):
        self.assertNotIn('published_at',evidence.article(self.page(meta='2026-10-29T08:00:00+03:00')))

    def test_naive_conflicting_metadata_does_not_claim_precise_clock(self):
        self.assertNotIn('published_at',evidence.article(self.page(meta='2026-10-29T08:00:00')))
