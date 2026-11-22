"""P0-1: PUBLIC/PRIVATE provenansı istek yolunda.

Kapanan boşluk: `privacy_sources` kuralları ve testleri vardı ama hiçbir istek yolu onu
çağırmıyordu; yani araştırma sayfası gibi gerçekten kamuya açık içerik de PRIVATE rota
sayılıyor, `mark_public` ile etiket üretilmiyordu.

Kural (tek yön): kanıt verilirse rota sınıfı **kanıttan** gelir. Hepsi gerçek ve izinli
PUBLIC değilse PRIVATE. PUBLIC iddiası kanıtla desteklenmiyorsa düşer; kanıt asla
PUBLIC'e yükseltilmez.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules import cloudflare_chat, llm, privacy_sources as ps, smart_router as router

PUB, PRIV = 'PUBLIC_RESEARCH', 'PRIVATE_GENERAL'
SOURCE_TEXT = ('Kamuya açık kaynak sayfasının metni burada yer alıyor; araştırma cevabı yalnız '
               'bu metinle sınırlı kalır ve alıntı gerçekten sayfada bulunur. ' * 2)


class ProvenanceRouteTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        for name, value in [('_STORE', Path(directory)), ('_HEALTH', {})]:
            self.enterContext(patch.object(router, name, value))
        for target, name, value in [
            (router.privacy, 'mode', 'normal'), (llm, 'user_key', 'gem-key'),
            (llm, 'user_groq_key', 'groq-key'), (llm, 'active_model', 'gem-model'),
            (llm, 'groq_model', 'groq-model'), (cloudflare_chat, 'configured', True),
            (llm, 'current_user', 'alice'), (llm, 'provider', 'auto'),
        ]:
            self.enterContext(patch.object(target, name, return_value=value))
        for name, fn in [('protect', lambda s: 'enc:' + s), ('unprotect', lambda s: s.removeprefix('enc:'))]:
            self.enterContext(patch.object(router.privacy, name, side_effect=fn))
        self.enterContext(patch('modules.usage_meter.observed_exhaustion', return_value=None))
        router.configure('alice', gemini_scopes=[])

    def request(self, **kwargs):
        return router.ModelRequest(owner='alice', profile='conversation', **kwargs)

    def route(self, **kwargs):
        return router.request_route(self.request(**kwargs))

    def test_evidence_none_keeps_the_caller_route(self):
        self.assertEqual(self.route(), PRIV)
        self.assertEqual(self.route(route=PUB), PUB)

    def test_all_public_evidence_makes_the_request_public(self):
        label = ps.mark_public('web_search', 'kamuya açık sayfa')
        self.assertEqual(self.route(evidence=(label,)), PUB)
        public = [spec.provider for spec in router.plan(self.request(evidence=(label,))).candidates]
        private = [spec.provider for spec in router.plan(self.request()).candidates]
        self.assertEqual(public[0], 'gemini')                 # PUBLIC rotada Gemini başta
        self.assertNotIn('gemini', private)                   # etiketsiz istek Gemini'ye gitmez

    def test_one_private_item_taints_the_whole_request(self):
        items = (ps.mark_public('web_search', 'sayfa'), ps.mark_private('history', 'sohbet'))
        self.assertEqual(self.route(evidence=items), PRIV)

    def test_forged_or_unknown_public_claims_are_demoted(self):
        forged = ({'privacy': 'PUBLIC', 'route': 'PUBLIC'},)          # düz sözlük PUBLIC üretemez
        unknown = (ps.mark_public('bilinmeyen_kaynak', 'x'),)          # izin listesinde olmayan kaynak
        for items in (forged, unknown):
            # Çağıran açıkça PUBLIC_RESEARCH yazsa bile kanıt desteklemiyorsa PUBLIC olmaz.
            self.assertEqual(self.route(evidence=items, route=PUB), PRIV, items)

    def test_empty_evidence_is_not_public(self):
        self.assertEqual(self.route(evidence=()), PRIV)

    def test_research_worker_labels_the_public_page_and_routes_public(self):
        """Bağlama noktası: kaynak metni etiketlenir ve model çağrısı PUBLIC rotaya gider."""
        from modules import model_wait, research_providers, task_workers
        captured = {}

        def fake_ask(prompt, system='', max_tokens=2000, **kwargs):
            captured['evidence'] = kwargs.get('evidence')
            captured['route'] = router.request_route(
                router.ModelRequest(owner='alice', profile='public_research', evidence=kwargs.get('evidence')))
            quote = SOURCE_TEXT[10:90]
            return ('{"supported":true,"answer":"cevap","quotes":["' + quote + '"]}')

        with patch('modules.privacy.blocked', return_value=None), \
             patch.object(research_providers, 'academic_requested', return_value=False), \
             patch.object(research_providers, 'search_public', return_value=[{'url': 'https://example.org/a'}]), \
             patch.object(research_providers, 'extract_source',
                          return_value={'url': 'https://example.org/a', 'text': SOURCE_TEXT}), \
             patch.object(research_providers, 'independent_candidates', return_value=[]), \
             patch.object(model_wait, 'ask', side_effect=fake_ask):
            task_workers.run('alice', {'agent': 'research', 'input': {'query': 'konu'},
                                       'execution': {'request': 'konu hakkında araştır'}}, {})

        evidence = captured['evidence']
        self.assertEqual(len(evidence), 1)
        self.assertIs(ps.item_route(evidence[0]), ps.RouteClass.PUBLIC)
        self.assertEqual(evidence[0].source_id, 'public_page_reader')
        self.assertEqual(captured['route'], PUB)


class PrivacySourcesContractTests(unittest.TestCase):
    """Mevcut sözleşme korunuyor: PUBLIC yalnız mark_public + izinli kaynak."""

    def test_allowlist_is_closed(self):
        self.assertEqual(ps.PUBLIC_SOURCE_ALLOWLIST, frozenset({'web_search', 'news_pipeline', 'public_page_reader'}))
        self.assertIs(ps.item_route(ps.mark_public('web_search', 1)), ps.RouteClass.PUBLIC)
        self.assertIs(ps.item_route({'route': 'PUBLIC'}), ps.RouteClass.PRIVATE)
        self.assertIs(ps.item_route('kamuya açık metin'), ps.RouteClass.PRIVATE)
        self.assertIs(ps.classify([]), ps.RouteClass.PRIVATE)


if __name__ == '__main__':
    unittest.main()
