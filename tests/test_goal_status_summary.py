from types import SimpleNamespace
import unittest
from unittest.mock import patch
from modules import goal_executor as goals


class StatusSummaryTests(unittest.TestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        self.body = 'MAKALE_GOVDESI_GIZLI_' * 170
        self.job = {'state': 'done', 'request': 'Son haftanın haberleri ' * 20,
                    'goals': [{'state': 'done', 'text': 'Haber araştır', 'evidence': ['a','b']}],
                    'steps': [{'state': state} for state in ('done','done','done','failed')],
                    'outputs': {'a': {'news_article': {'url': 'https://example.com/a'}, 'text': self.body},
                                'b': {'news_article': {'url': 'https://example.com/b'}, 'text': self.body},
                                'report': {'file': 'C:\\fake\\rapor.md', 'text': self.body}}}

    def handle(self, command):
        with patch.object(goals, 'latest', return_value=self.job), patch.object(goals, 'run', side_effect=AssertionError('Hedef yürütülmemeli')):
            return goals.handle(self.runtime, command)

    def test_status_short_counts_no_tool_body_and_report_path(self):
        response = self.handle('hedef durumu')
        self.assertLess(len(response), 600)
        self.assertIn('3/4 adım', response)
        self.assertIn('2 kaynak', response)
        self.assertIn('Rapor dosyası: C:\\fake\\rapor.md', response)
        self.assertNotIn(self.body[:40], response)
        self.assertLessEqual(len(response.splitlines()), 2)

    def test_running_cancelled_approval_question_paused_states(self):
        for state, label in [('running','çalışıyor'), ('cancelled','iptal'), ('approval','onay bekliyor'), ('question','soru bekliyor'), ('paused','duraklatıldı')]:
            with self.subTest(state=state):
                self.job['state'] = state
                self.assertIn(label, self.handle('hedef durumu'))

    def test_no_job_and_status_alias(self):
        self.assertEqual(self.handle('işin durumu'), self.handle('hedef durumu'))
        self.job = None
        for command in ('hedef durumu','işin durumu','hedef ayrıntıları'):
            self.assertEqual(self.handle(command), 'Kayıtlı hedef yok.')

    def test_details_still_use_original_render(self):
        with patch.object(goals, '_check_news_completion'):
            expected = goals.render(self.job)
            self.assertEqual(self.handle('hedef ayrıntıları'), expected)
            self.assertIn(self.body, expected)

    def test_duplicate_sources_and_missing_legacy_fields(self):
        self.job['outputs']['duplicate'] = dict(self.job['outputs']['a'])
        self.assertIn('2 kaynak', self.handle('hedef durumu'))
        self.job = {'state': 'done', 'request': 'Eski hedef'}
        self.assertIn('0 kaynak', self.handle('hedef durumu'))
        self.assertIn('0/0 adım', self.handle('hedef durumu'))


if __name__ == '__main__':
    unittest.main()
