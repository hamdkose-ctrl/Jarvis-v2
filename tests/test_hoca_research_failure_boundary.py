import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import engine_tools, hoca, requests_state


class HocaResearchFailureBoundaryTests(unittest.TestCase):
    def runtime(self):
        return SimpleNamespace(profile=SimpleNamespace(data={}, slug='hoca-test'),
                               re=re, _MEDIA_Q=re.compile('never-match'),
                               _record_failure=lambda *_: None)

    def test_search_failure_returns_hoca_error_instead_of_generic_planner_fallthrough(self):
        error = ValueError('public_search_blocked: https://example.test/?key=private-secret')
        runtime = self.runtime()
        with patch('config.load_settings', return_value={}), \
             patch('modules.research_providers.search_public', side_effect=error) as search, \
             patch.object(hoca.llm, 'ask') as model:
            reply = engine_tools._study_intent(runtime, 'hoca modu: araştır fotosentez')
        self.assertIsInstance(reply, str)
        self.assertIn('Kaynak araması', reply)
        self.assertNotIn('private-secret', reply)
        self.assertEqual(search.call_count, 1)
        model.assert_not_called()
        self.assertIsNone(hoca.active(runtime.profile))

    def test_permission_and_cancellation_do_not_fall_through_hoca_bridge(self):
        for error in (PermissionError('denied'), requests_state.Cancelled('stop')):
            with self.subTest(error=type(error).__name__), \
                 patch('config.load_settings', return_value={}), \
                 patch('modules.research_providers.search_public', side_effect=error), \
                 patch.object(hoca.llm, 'ask') as model:
                with self.assertRaises(type(error)):
                    engine_tools._study_intent(self.runtime(), 'hoca modu: araştır fotosentez')
                model.assert_not_called()

    def test_unrelated_chat_still_returns_none(self):
        with patch('config.load_settings', return_value={}), \
             patch.object(hoca.llm, 'ask') as model:
            self.assertIsNone(engine_tools._study_intent(self.runtime(), 'merhaba'))
        model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
