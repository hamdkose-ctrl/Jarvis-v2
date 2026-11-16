"""Official exact-model context cards are time-bound, not API-native or free-tier claims."""
import time
import unittest
from modules import model_capabilities as caps

REVIEWED=1794855600
EXPIRES=1795460400

class OfficialModelCardsTests(unittest.TestCase):
    def test_exact_groq_context_and_output_cards(self):
        for model in ('openai/gpt-oss-120b','openai/gpt-oss-20b'):
            with self.subTest(model=model):
                row=caps.CATALOG[('groq',model)]
                self.assertTrue(row['source_url'].startswith('https://console.groq.com/docs/model/'))
                found=caps.check('groq',model,min_context_tokens=131072,
                                 requested_output=65536,now=REVIEWED+120)
                self.assertTrue(found['ok'])
                self.assertEqual(found['context_limit'],131072)
                self.assertEqual(found['features'],frozenset())
                self.assertEqual(caps.check('groq',model,min_context_tokens=131073,
                                 now=REVIEWED+120)['reason_code'],
                                 'MODEL_CONTEXT_LIMIT_UNVERIFIED')
                self.assertEqual(caps.check('groq',model,requested_output=65537,
                                 now=REVIEWED+120)['reason_code'],
                                 'MODEL_OUTPUT_LIMIT_EXCEEDED')
                self.assertEqual(caps.check('groq',model,native_features={'native_json_schema'},
                                 now=REVIEWED+120)['reason_code'],
                                 'MODEL_NATIVE_FEATURE_UNSUPPORTED')
                self.assertEqual(caps.check('groq',model,min_context_tokens=1,
                                 now=EXPIRES+1)['reason_code'],
                                 'MODEL_CAPABILITY_EVIDENCE_MISSING')

    def test_provider_or_model_name_similar_does_not_inherit_claim(self):
        for provider,model in (('groq','openai/gpt-oss-120b-latest'),
                               ('gemini','openai/gpt-oss-120b'),
                               ('groq','openai/gpt-oss-1b')):
            with self.subTest(provider=provider,model=model):
                self.assertEqual(caps.check(provider,model,min_context_tokens=128,
                                 now=REVIEWED+120)['reason_code'],
                                 'MODEL_CAPABILITY_EVIDENCE_MISSING')

    def test_no_catalog_card_silently_expires_under_real_clock(self):
        # An expired card silently stops supplying evidence at runtime; this keeps
        # the renewal promise loud in CI instead of a quiet capability regression.
        now = time.time()
        for (provider, model), row in caps.CATALOG.items():
            with self.subTest(provider=provider, model=model):
                self.assertLessEqual(row['verified_at'], now, 'gelecekte doğrulanmış kart')
                self.assertGreater(row['expires_at'], now, 'süresi dolmuş kart: resmî karttan yenile')
                self.assertIsNotNone(caps.evidence(provider, model, now=now))

if __name__ == '__main__':
    unittest.main()
