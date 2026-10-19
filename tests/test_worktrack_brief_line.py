import unittest
from unittest.mock import patch

from modules import worktrack


class WorktrackBriefLineTests(unittest.TestCase):
    def test_brief_line_explains_read_mail_and_seven_day_reply_window(self):
        recent = [
            {'direct': True},
            {'direct': True},
            {'direct': False},
        ]
        facts = {
            'recent': recent,
            'cc_only': 1,
            'dated': [],
            'vip': [],
        }
        seven_days = [{'id': 1}, {'id': 2}, {'id': 3}, {'id': 4}]
        waiting = [{'id': 1}, {'id': 2}]

        with patch.object(worktrack, 'facts', return_value=facts) as facts_mock, \
             patch.object(worktrack, 'collect', return_value=seven_days) as collect_mock, \
             patch.object(worktrack, 'needs_reply', return_value=waiting) as reply_mock:
            line = worktrack.brief_line()

        self.assertIn('son 24 saatte 3 iş maili geldi', line)
        self.assertIn('okunmuş olanlar dahil; 2 doğrudan sana, 1 bilgide', line)
        self.assertIn('son 7 günde cevap bekleyen 2', line)
        facts_mock.assert_called_once_with(1)
        collect_mock.assert_called_once_with(7)
        reply_mock.assert_called_once_with(seven_days)

    def test_brief_line_keeps_zero_counts_readable(self):
        facts = {'recent': [], 'cc_only': 0, 'dated': [], 'vip': []}
        with patch.object(worktrack, 'facts', return_value=facts), \
             patch.object(worktrack, 'collect', return_value=[]), \
             patch.object(worktrack, 'needs_reply', return_value=[]):
            line = worktrack.brief_line()

        self.assertEqual(
            line,
            'İş takibi: son 24 saatte 0 iş maili geldi (okunmuş olanlar dahil; 0 doğrudan sana, 0 bilgide), '
            'son 7 günde cevap bekleyen 0.'
        )


if __name__ == '__main__':
    unittest.main()
