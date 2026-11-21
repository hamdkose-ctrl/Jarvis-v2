"""Official exact-model context and output limits."""
import unittest
from modules import model_capabilities as caps

class OfficialModelCardsTests(unittest.TestCase):
    def test_exact_groq_context_and_output_cards(self):
        for model in ('openai/gpt-oss-120b','openai/gpt-oss-20b'):
            with self.subTest(model=model):
                row=caps.CATALOG[('groq',model)]
                self.assertTrue(row['source_url'].startswith('https://console.groq.com/docs/model/'))
                found=caps.check('groq',model,min_context_tokens=131072,
                                 requested_output=65536)
                self.assertTrue(found['ok'])
                self.assertEqual(found['context_limit'],131072)
                self.assertEqual(found['features'],frozenset())
                self.assertEqual(caps.check('groq',model,min_context_tokens=131073)['reason_code'],
                                 'MODEL_CONTEXT_LIMIT_UNVERIFIED')
                self.assertEqual(caps.check('groq',model,requested_output=65537)['reason_code'],
                                 'MODEL_OUTPUT_LIMIT_EXCEEDED')
                self.assertEqual(caps.check('groq',model,native_features={'native_json_schema'})['reason_code'],
                                 'MODEL_NATIVE_FEATURE_UNSUPPORTED')

    def test_provider_or_model_name_similar_does_not_inherit_claim(self):
        for provider,model in (('groq','openai/gpt-oss-120b-latest'),
                               ('gemini','openai/gpt-oss-120b'),
                               ('groq','openai/gpt-oss-1b')):
            with self.subTest(provider=provider,model=model):
                self.assertEqual(caps.check(provider,model,min_context_tokens=128)['reason_code'],
                                 'MODEL_CAPABILITY_EVIDENCE_MISSING')


if __name__ == '__main__':
    unittest.main()
