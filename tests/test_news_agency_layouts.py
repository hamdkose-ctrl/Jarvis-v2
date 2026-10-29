import unittest
from modules import research_evidence

class AgencyLayouts(unittest.TestCase):
    def page(self,agency,*,stamp=None,extra='',ref=None):
        if agency=='iha':
            url='https://www.iha.com.tr/example-story-12345'
            stamp='28 Ekim 2026 Çarşamba 16:21' if stamp is None else stamp
            html=f'<link rel="canonical" href="{ref or url}"><div class="widget_General_News_Detail"><h1>Article title</h1><span>{stamp}</span><div class="news-detail__content"><p>{"Real article text. "*20}</p></div>{extra}</div>'
        else:
            url='https://ilkha.com/dunya/example-story-12345'
            stamp='28.10.2026 16:21:00' if stamp is None else stamp
            html=f'<meta property="og:url" content="{ref or url}"><div class="post-layout-top-content-3"><div class="post-content"><h3 class="title">Article title</h3></div><div class="post-categories"><ul class="author-social"><li class="cat-red">{stamp}</li></ul></div><a href="https://twitter.com/share?url={url}">Share</a><div class="post-text"><p>{"Real article text. "*20}</p></div>{extra}</div>'
        return {'url':url,'body':('<html><body><header>01.01.2030</header>'+html+'<aside>01.01.2031</aside></body></html>').encode()}
    def test_scoped_date_ignores_external_dates(self):
        for a in ('iha','ilkha'):
            self.assertEqual(research_evidence.article(self.page(a))['published'],'2026-10-28')
    def test_missing_date_rejected(self):
        for a in ('iha','ilkha'):
            with self.subTest(a=a),self.assertRaises(ValueError):research_evidence.article(self.page(a,stamp=''))
    def test_conflicting_identity_rejected(self):
        for a in ('iha','ilkha'):
            with self.subTest(a=a),self.assertRaises(ValueError):research_evidence.article(self.page(a,ref='https://other.com/article'))
    def test_multiple_dates_rejected(self):
        for a,extra in [('iha','<span>27 Ekim 2026 Salı 15:00</span>'),('ilkha','<div class="post-categories"><ul class="author-social"><li class="cat-red">27.10.2026 15:00:00</li></ul></div>')]:
            with self.subTest(a=a),self.assertRaises(ValueError):research_evidence.article(self.page(a,extra=extra))
    def test_multiple_bodies_rejected(self):
        for a,extra in [('iha','<div class="news-detail__content">Other story</div>'),('ilkha','<div class="post-text">Other story</div>')]:
            with self.subTest(a=a),self.assertRaises(ValueError):research_evidence.article(self.page(a,extra=extra))
