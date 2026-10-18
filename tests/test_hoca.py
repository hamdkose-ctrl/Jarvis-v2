import unittest
from unittest.mock import patch

from modules import hoca


class Profile:
    slug = 'hoca-fixture'

    def __init__(self):
        self.data = {}
        self.saves = 0

    def save(self):
        self.saves += 1


PLAN = '```json\n{"steps":[{"title":"Hücre nedir","goal":"Tanım"},{"title":"Organeller","goal":"Çekirdek, mitokondri"},{"title":"Zar","goal":"Geçirgenlik"}]}\n```'


class HocaLessonTests(unittest.TestCase):
    def setUp(self):
        self.p = Profile()

    def test_start_builds_plan_with_one_model_call(self):
        with patch.object(hoca.llm, 'ask', return_value=PLAN) as ask:
            lesson = hoca.start(self.p, 'Hücre', level='başlangıç')
        self.assertEqual(ask.call_count, 1)
        self.assertEqual([s['title'] for s in lesson['steps']], ['Hücre nedir', 'Organeller', 'Zar'])
        self.assertEqual(lesson['active'], 0)
        self.assertEqual(lesson['topic'], 'Hücre')
        self.assertGreaterEqual(self.p.saves, 1)

    def test_bad_model_output_is_explicit_error_and_stores_nothing(self):
        for bad in ('', 'Merhaba', '{"steps":[]}', '{"steps":[{"title":"x"}]}'):
            with patch.object(hoca.llm, 'ask', return_value=bad):
                with self.assertRaises(hoca.HocaError):
                    hoca.start(self.p, 'Hücre')
        self.assertIsNone(hoca.active(self.p))

    def test_model_failure_is_explicit(self):
        with patch.object(hoca.llm, 'ask', side_effect=RuntimeError('429')):
            with self.assertRaises(hoca.HocaError) as cm:
                hoca.start(self.p, 'Hücre')
        self.assertIn('plan', str(cm.exception).lower())

    def test_empty_topic_rejected_without_model_call(self):
        with patch.object(hoca.llm, 'ask') as ask:
            with self.assertRaises(hoca.HocaError):
                hoca.start(self.p, '   ')
        ask.assert_not_called()

    def test_advance_and_finish(self):
        with patch.object(hoca.llm, 'ask', return_value=PLAN):
            hoca.start(self.p, 'Hücre')
        self.assertEqual(hoca.current_step(self.p)['title'], 'Hücre nedir')
        hoca.advance(self.p)
        self.assertEqual(hoca.current_step(self.p)['title'], 'Organeller')
        hoca.advance(self.p); hoca.advance(self.p)
        self.assertIsNone(hoca.current_step(self.p))
        self.assertTrue(hoca.active(self.p) is None or hoca.active(self.p)['done'])

    def test_new_start_replaces_unfinished_lesson_and_users_are_separate(self):
        other = Profile(); other.slug = 'baska'
        with patch.object(hoca.llm, 'ask', return_value=PLAN):
            hoca.start(self.p, 'Hücre'); hoca.start(self.p, 'Genetik'); hoca.start(other, 'Optik')
        self.assertEqual(hoca.active(self.p)['topic'], 'Genetik')
        self.assertEqual(hoca.active(other)['topic'], 'Optik')

    def test_long_topic_and_step_text_are_capped(self):
        big = '{"steps":[' + ','.join('{"title":"%s","goal":"g"}' % ('a' * 500) for _ in range(20)) + ']}'
        with patch.object(hoca.llm, 'ask', return_value=big):
            lesson = hoca.start(self.p, 'T' * 500)
        self.assertLessEqual(len(lesson['steps']), 8)
        self.assertLessEqual(len(lesson['steps'][0]['title']), 120)
        self.assertLessEqual(len(lesson['topic']), 120)


if __name__ == '__main__':
    unittest.main()
