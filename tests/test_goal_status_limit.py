"""'hedef durumu' uzun sonucu sohbete dökmez; 'hedef ayrıntıları' tamamını verir."""
import types
import unittest
from unittest.mock import patch
from modules import goal_executor as ge


class GoalStatusLimitTests(unittest.TestCase):
    def _handle(self, command, text, job=True):
        runtime = types.SimpleNamespace(profile=types.SimpleNamespace(slug='alice'))
        fake = {'state': 'done', 'steps': [], 'goals': [], 'outputs': {}, 'waiting': None} if job else None
        with patch.object(ge, 'latest', return_value=fake), patch.object(ge, 'render', return_value=text):
            return ge.handle(runtime, command)

    def test_status_is_truncated_with_pointer_to_details(self):
        long = 'Makale metni. ' * 600
        for command in ('hedef durumu', 'işin durumu'):
            reply = self._handle(command, long)
            self.assertLess(len(reply), ge.STATUS_LIMIT + 120)
            self.assertIn('hedef ayrıntıları', reply)

    def test_short_status_and_details_are_untouched(self):
        self.assertEqual(self._handle('hedef durumu', 'Kısa sonuç'), 'Kısa sonuç')
        long = 'x' * 5000
        self.assertEqual(self._handle('hedef ayrıntıları', long), long)

    def test_no_goal_message_is_unchanged(self):
        self.assertEqual(self._handle('hedef durumu', 'x', job=False), 'Kayıtlı hedef yok.')


if __name__ == '__main__':
    unittest.main()
