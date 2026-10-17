import unittest
from pathlib import Path

from modules import account_tools, diagnose, failure_policy, goal_tools, learning, router, smart_router, work_modes


class ServerNotFoundError(Exception):
    pass


class Http429(Exception):
    code = 429


class FakeProfile:
    def __init__(self):
        self.data = {
            'rules': [
                'Beni otomatik onaylama; yanlışsam açıkça söyle.',
                'Haber araştırırken yayın tarihini ve gerçek kaynağı doğrula.',
                'Excel görevlerinde hücredeki sonucu doğrula.',
                'Mail gönderirken alıcıyı iki kez kontrol et.',
            ],
            'facts': [],
            'items': [],
        }


class ExecutionPolicyTests(unittest.TestCase):
    def test_local_results_carry_outcome_contract(self):
        result = goal_tools.local_result('alice', 'system', 'Ses seviyesi: 30')
        self.assertEqual(result['outcome_contract']['id'], 'OUTCOME-PC-SYSTEM-VERIFIED')
        self.assertEqual(result['outcome_contract']['scope'], 'local')
        self.assertTrue(goal_tools.verify(result, 'alice'))

    def test_failure_policy_classifies_core_failures(self):
        dns = ServerNotFoundError('Unable to find the server at www.googleapis.com')
        self.assertEqual(failure_policy.classify(dns), failure_policy.DNS)
        self.assertTrue(failure_policy.network_unavailable(dns))
        self.assertTrue(account_tools._network_unavailable(dns))
        self.assertIn('DNS', diagnose.explain(dns))

        quota = Http429('RESOURCE_EXHAUSTED')
        self.assertEqual(failure_policy.classify(quota), failure_policy.RATE_LIMIT)
        self.assertEqual(smart_router.failure_kind(quota), 'quota')
        self.assertEqual(smart_router.cooldown('gemini', quota), 300)
        self.assertEqual(failure_policy.recovery_action(failure_policy.RATE_LIMIT, context='planner'), 'alternate_provider')

        self.assertEqual(failure_policy.classify(PermissionError('izin gerekli')), failure_policy.PERMISSION)
        self.assertEqual(failure_policy.classify(ValueError('Tekil haber kaynağı doğrulanamadı')), failure_policy.SOURCE_INVALID)

    def test_work_modes_are_do_first_without_forcing_spec(self):
        self.assertEqual(work_modes.classify('Ayarları aç ve Bluetooth’u kapat'), 'do')
        self.assertEqual(work_modes.classify('İstanbul güncel haberler nelerdir'), 'do')
        self.assertEqual(work_modes.classify('HTTP nedir?'), 'chat')
        self.assertEqual(work_modes.classify('Bu özellik için formal spec oluştur'), 'spec')

        answer = '{"intent":"chat","args":{}}'
        routed = router.classify('Ayarları aç ve Bluetooth’u kapat', lambda *_: answer)
        self.assertEqual(routed['intent'], 'task')

    def test_rules_are_scoped_by_query(self):
        profile = FakeProfile()
        research = learning.rules_prompt(profile, 'İstanbul güncel haberlerini araştır')
        self.assertIn('otomatik onaylama', research)
        self.assertIn('yayın tarihini', research)
        self.assertNotIn('Excel görevlerinde', research)
        self.assertNotIn('Mail gönderirken', research)

        pc = learning.rules_prompt(profile, 'Excel’i açıp A1 hücresine Merhaba yaz')
        self.assertIn('otomatik onaylama', pc)
        self.assertIn('Excel görevlerinde', pc)
        self.assertNotIn('yayın tarihini', pc)

        legacy = learning.rules_prompt(profile)
        self.assertIn('yayın tarihini', legacy)
        self.assertIn('Excel görevlerinde', legacy)
        self.assertIn('Mail gönderirken', legacy)

    def test_startup_update_check_is_non_blocking_and_measured(self):
        root = Path(__file__).resolve().parents[1]
        gui = (root / 'gui.py').read_text(encoding='utf-8')
        web = (root / 'web.py').read_text(encoding='utf-8')
        update_call = '\n    _start_update_check()\n'
        self.assertIn('def _start_update_check', gui)
        self.assertIn('threading.Thread(target=_check_updates_background', gui)
        self.assertIn(update_call, gui)
        self.assertLess(gui.index('import web'), gui.index(update_call))
        self.assertIn("startup_metrics.mark('web_imported')", gui)
        self.assertIn("startup_metrics.ready('window_open')", web)
        self.assertLess(web.index('open_window(url)'), web.index("startup_metrics.ready('window_open')"))


if __name__ == '__main__':
    unittest.main()
