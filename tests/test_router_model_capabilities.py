"""Evidence-based native model feature gate. No provider, OS or user files."""
import unittest
from unittest.mock import patch
from modules import model_capabilities as catalog
from modules import smart_router as router

PROVIDER='groq'
MODEL='exact-model-id'

def verified(**changes):
    row={'features':frozenset({'native_json_schema','native_tool_calling'}),
         'context_limit':32768,'output_limit':4096,
         'source_url':'https://provider.example/docs/model-spec'}
    row.update(changes)
    return row

class ModelCapabilityEvidenceTests(unittest.TestCase):
    def setUp(self):
        patched=patch.object(catalog,'CATALOG',{})
        patched.start()
        self.addCleanup(patched.stop)

    def test_unknown_advanced_requirement_rejected_without_network(self):
        self.assertEqual(catalog.check(PROVIDER,MODEL,native_features={'native_json_schema'})
                         ['reason_code'],'MODEL_CAPABILITY_EVIDENCE_MISSING')
        self.assertEqual(catalog.check(PROVIDER,MODEL,min_context_tokens=10000)
                         ['reason_code'],'MODEL_CAPABILITY_EVIDENCE_MISSING')
        self.assertTrue(catalog.check(PROVIDER,MODEL,requested_output=1000)['ok'])

    def test_exact_model_feature_and_context_claim(self):
        catalog.CATALOG[(PROVIDER,MODEL)]=verified()
        ok=catalog.check(PROVIDER,MODEL,native_features={'native_json_schema'},
                         min_context_tokens=32000,requested_output=2000)
        self.assertTrue(ok['ok'])
        self.assertEqual(ok['context_limit'],32768)
        self.assertEqual(ok['features'],frozenset({'native_json_schema','native_tool_calling'}))
        self.assertEqual(catalog.check(PROVIDER,'another-model',
                         native_features={'native_json_schema'})['reason_code'],
                         'MODEL_CAPABILITY_EVIDENCE_MISSING')
        self.assertEqual(catalog.check('other',MODEL,
                         min_context_tokens=10)['reason_code'],
                         'MODEL_CAPABILITY_EVIDENCE_MISSING')

    def test_context_output_and_native_mismatch_fail_closed(self):
        catalog.CATALOG[(PROVIDER,MODEL)]=verified()
        self.assertEqual(catalog.check(PROVIDER,MODEL,min_context_tokens=32769)
                         ['reason_code'],'MODEL_CONTEXT_LIMIT_UNVERIFIED')
        self.assertEqual(catalog.check(PROVIDER,MODEL,requested_output=4097)
                         ['reason_code'],'MODEL_OUTPUT_LIMIT_EXCEEDED')
        self.assertEqual(catalog.check(PROVIDER,MODEL,native_features={'verified_vision'})
                         ['reason_code'],'MODEL_NATIVE_FEATURE_UNSUPPORTED')

    def test_unverified_or_bad_source_never_grants_features(self):
        for changes in ({'source_url':'http://not-secure.example/model'},
                        {'source_url':'https://user:password@provider.example/'},
                        {'source_url':'invalid'},
                        {'features':{'native_json_schema','forged_feature'}},
                        {'context_limit':True}):
            with self.subTest(changes=changes):
                catalog.CATALOG[(PROVIDER,MODEL)]=verified(**changes)
                self.assertEqual(catalog.check(PROVIDER,MODEL,
                                 native_features={'native_json_schema'})['reason_code'],
                                 'MODEL_CAPABILITY_EVIDENCE_MISSING')

    def test_malformed_native_and_context_contract_rejected_early(self):
        with self.assertRaises(ValueError):
            catalog.check(PROVIDER,MODEL,native_features={'invented_feature'})
        for bad in (0,-1,True,2.5,2_000_001):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                catalog.check(PROVIDER,MODEL,min_context_tokens=bad)

    def test_router_skips_only_missing_evidence_not_ordinary_text(self):
        specs=['groq','cloudflare']
        with patch.object(router,'selection',return_value={'candidates':specs,'skipped':[]}), \
             patch.object(router,'_model_for',side_effect=lambda _owner,prov: MODEL):
            original=router.plan(router.ModelRequest(owner='alice'))
            self.assertEqual([s.provider for s in original.candidates],specs)
            self.assertTrue(all(s.context_limit is None for s in original.candidates))
            native=router.plan(router.ModelRequest(owner='alice',
                    native_features=frozenset({'native_json_schema'}),min_context_tokens=20000))
            self.assertEqual(native.candidates,())
            self.assertEqual([row['reason_code'] for row in native.skipped],
                             ['MODEL_CAPABILITY_EVIDENCE_MISSING']*2)
            catalog.CATALOG[('groq',MODEL)]=verified()
            admitted=router.plan(router.ModelRequest(owner='alice',
                      native_features=frozenset({'native_json_schema'}),min_context_tokens=20000))
            self.assertEqual([s.provider for s in admitted.candidates],['groq'])
            self.assertEqual(admitted.candidates[0].context_limit,32768)

if __name__=='__main__':
    unittest.main()
