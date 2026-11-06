"""Güncel haber/skor istekleri model sınıfleyicisine düşmeden canonical araştırma planı olur."""
import unittest

from modules import brain_core_map, brain_understanding
from modules.brain_contracts import ActiveContext, RequestKind


def decide(text: str):
    semantic = brain_understanding.understand(
        owner="hamdi", request_id="rid-news", text=text,
        active_context=ActiveContext(owner="hamdi", request_id="rid-news"),
        candidates=(), references=())
    return semantic, brain_core_map.core_plan(semantic.capability_hint, semantic.arguments)


class FreshResearchRoutingTests(unittest.TestCase):
    def test_istanbul_current_news_goes_to_task_without_model_router(self):
        text = 'istanbul güncel haberler nelerdir'
        _semantic, plan = decide(text)
        self.assertEqual(plan, ("task", {"query": text, "route": "PRIVATE"}))

    def test_latest_news_variants_go_to_task(self):
        for text in ('İstanbul son haberler neler?', 'Bugün İstanbul haberlerinde ne var?',
                     'Türkiye yapay zekâ son gelişmelerini anlat'):
            with self.subTest(text=text):
                self.assertEqual(decide(text)[1][0], "task")

    def test_static_explanation_stays_chat_capable(self):
        semantic, plan = decide('Haber nedir?')
        self.assertIsNone(plan)
        self.assertIs(semantic.request_kind, RequestKind.CHAT)

    def test_explanation_about_a_fresh_topic_is_not_a_data_request(self):
        # "nasıl anlaşılır" ve "niye" soruları haber/kur kelimesi geçse de açıklama ister;
        # tazelik işareti taşımayan bu cümleler araştırma planına dönüşürse yanıt hep eskidir.
        for text in ('Rica etsem haberlerde kaynak güvenilirliği nasıl anlaşılır anlatır mısın?',
                     'Kur artınca ithal ürün niye pahalanıyor?'):
            with self.subTest(text=text):
                semantic, plan = decide(text)
                self.assertIsNone(plan, text)
                self.assertIs(semantic.request_kind, RequestKind.CHAT, text)

    def test_an_explicitly_fresh_how_question_still_gets_live_data(self):
        # Tazelik işareti ("bugünkü", "son") açıklama sorusunu bastırır: kullanıcı güncel veriyi ister.
        # BRAIN-03 dilim 3: kur/fiyat sorusunun canlı veri sahibi finans domain'idir; cevap oradan
        # gelir, arama görevi açılmaz. Araştırma kanalı ancak kullanıcı "araştır" derse seçilir.
        self.assertEqual(decide('bugünkü dolar kuruna nasıl bakılır')[1],
                         ("finance_read", {"kind": "rate", "source": "USD", "target": "TRY"}))
        self.assertEqual(decide('bugünkü dolar kuruna nasıl bakılır araştır')[1][0], "task")
        self.assertEqual(decide('son haberlerdeki gelişmeyi nasıl özetlersin')[1][0], "task")

    def test_the_research_prompt_carries_no_chat_escape_hint(self):
        # Eski SYSTEM prompt'u kaldırıldı; taze dış veri hükmü artık kanonik tanıyıcıda yaşıyor.
        import inspect
        from engine_source import source
        self.assertNotIn('genel güncel internet aramaları için intent="chat"', source())
        self.assertIn('_needs_fresh_external_data', inspect.getsource(brain_understanding))


if __name__ == '__main__':
    unittest.main()
