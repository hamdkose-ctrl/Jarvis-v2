"""Turkish casing regressions; no network, model, screen or real profile writes."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class TurkishTextTests(unittest.TestCase):
    def test_lower_turkish_and_safe_values(self):
        from modules.turkish_text import lower
        for original, expected in [('IĞDIR', 'ığdır'), ('İSTANBUL', 'istanbul'),
                                   ('ISPARTA', 'ısparta'), ('Işık İlk', 'ışık ilk'),
                                   ('I\u0307STANBUL', 'istanbul'), (None, ''), ('', ''),
                                   (42, '42'), (False, ''), ('C\u0327', 'ç')]:
            with self.subTest(original=original):
                self.assertEqual(lower(original), expected)

    def test_fold_turkish_ascii(self):
        from modules.turkish_text import fold
        for original, expected in [('IĞDIR', 'igdir'), ('İSTANBUL', 'istanbul'),
                                   ('Işık İlk', 'isik ilk'), ('ÇĞİÖŞÜ', 'cgiosu'),
                                   (None, ''), ('', '')]:
            with self.subTest(original=original):
                self.assertEqual(fold(original), expected)

    def test_history_search_normalizes_query_and_saved_text(self):
        from modules import history
        with TemporaryDirectory() as folder, patch.object(history, 'DIR', Path(folder)):
            history.append('fixture', 'user', 'IĞDIR yolculuğu')
            history.append('fixture', 'user', 'ığdır dönüşü')
            self.assertEqual(len(history.read('fixture', 'IĞDIR')), 2)
            self.assertEqual(len(history.read('fixture', 'ığdır')), 2)

    def test_tasks_complete_matching_uppercase_igdir(self):
        from modules import tasks
        for query, saved in [('IĞDIR', 'ığdır'), ('ığdır', 'IĞDIR')]:
            with self.subTest(query=query):
                profile = SimpleNamespace(data={'tasks': [{'id': 1, 'text': saved, 'done': False}]}, save=Mock())
                result = tasks.complete_exact(profile, query)
                self.assertTrue(profile.data['tasks'][0]['done'], result)
                profile.save.assert_called_once()

    def test_translation_grammar_uppercase_reference_selects_igdir_source(self):
        from modules import translation_request as translation
        rows = [{'id': 1, 'role': 'user', 'text': 'IĞDIR', 'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}]
        command = 'çevir: YAZDIĞIMI'
        request = translation.parse(command)
        self.assertEqual(translation.pick_source(request, command, rows)[0], 'IĞDIR')
        self.assertFalse(translation.is_source('TEŞEKKÜRLER'))

    def test_pc_guide_normalizes_followup_without_changing_goal(self):
        from modules import pc_guide as guide
        profile = SimpleNamespace(slug='fixture')
        session = SimpleNamespace(profile=profile, owner='fixture', closed=Event(), check=Mock(return_value='tamam'))
        with patch.object(guide, '_ACTIVE', session), patch.object(guide, '_RUNTIME', None):
            for command in ('IĞDIR kontrol et', 'Jarvis, IĞDIR kontrol et'):
                self.assertEqual(guide.handle(profile, command), 'tamam')
                session.check.assert_called_with('ığdır kontrol et', automatic=False)

    def test_math_tutor_matches_turkish_capitals_in_request(self):
        from modules import math_tutor
        self.assertTrue(math_tutor.wants_solution('IĞDIR sorusunu ÇÖZER MİSİN'))
        self.assertFalse(math_tutor.wants_solution('IĞDIR sorusunu ÇÖZMENİ İSTEMİYORUM'))

    def test_handoff_prefers_correct_turkish_match_over_wrong_dotted_spelling(self):
        from modules import handoff
        service = Mock()
        with patch.object(handoff, 'pending', return_value=[{'id': 'wrong', 'text': 'iğdir'},
                                                           {'id': 'right', 'text': 'ığdır'}]), \
                patch.object(handoff, '_svc', return_value=service), patch.object(handoff, '_lid', return_value='list'):
            self.assertEqual(handoff.complete('IĞDIR'), 'ığdır')
        service.tasks.return_value.patch.assert_called_once_with(
            tasklist='list', task='right', body={'status': 'completed'})


if __name__ == '__main__':
    unittest.main()
