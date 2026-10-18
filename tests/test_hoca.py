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


class HocaCheckTests(unittest.TestCase):
    def setUp(self):
        self.p = Profile()
        with patch.object(hoca.llm, 'ask', return_value=PLAN):
            hoca.start(self.p, 'Hücre')

    def test_control_words_are_explicit_not_topic_guessing(self):
        for t in ('sonraki konuya geç', 'Sonraki adıma geçelim', 'devam et', 'geç'):
            self.assertEqual(hoca.intent(t), 'next', t)
        for t in ('konuyu değiştir', 'başka konuya geçelim', 'dersi bitir'):
            self.assertEqual(hoca.intent(t), 'change', t)
        for t in ('mitokondri ne işe yarar', 'bir örnek ver', 'IĞDIR nerede', 'Osmanlı geç dönem nedir', 'devam eden süreç ne', 'geç kaldım'):
            self.assertEqual(hoca.intent(t), 'stay', t)

    def test_question_is_one_call_and_stored_for_grading(self):
        with patch.object(hoca.llm, 'ask', return_value='{"question":"Hücre neyin birimi?","answer":"Canlının yapı birimi"}') as ask:
            q = hoca.check_question(self.p)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(q, 'Hücre neyin birimi?')
        again = hoca.check_question(self.p)  # bekleyen soru yeniden sorulur, model çağrılmaz
        self.assertEqual(again, q)

    def test_correct_answer_advances_and_logs_score(self):
        with patch.object(hoca.llm, 'ask', return_value='{"question":"S?","answer":"A"}'):
            hoca.check_question(self.p)
        with patch.object(hoca.llm, 'ask', return_value='{"correct":true,"feedback":"Güzel."}'):
            r = hoca.grade(self.p, 'canlının yapı birimi')
        self.assertTrue(r['correct'])
        self.assertEqual(hoca.current_step(self.p)['title'], 'Organeller')
        self.assertEqual(hoca.weak_topics(self.p), [])

    def test_wrong_answer_stays_and_marks_weak_with_spacing(self):
        with patch.object(hoca.llm, 'ask', return_value='{"question":"S?","answer":"A"}'):
            hoca.check_question(self.p)
        with patch.object(hoca.llm, 'ask', return_value='{"correct":false,"feedback":"Tekrar bak."}'):
            r = hoca.grade(self.p, 'bilmem', now=1000)
        self.assertFalse(r['correct'])
        self.assertEqual(hoca.current_step(self.p)['title'], 'Hücre nedir')
        w = hoca.weak_topics(self.p)
        self.assertEqual(w[0]['title'], 'Hücre nedir')
        self.assertEqual(w[0]['due'], 1000 + 86400)
        self.assertEqual(hoca.due_reviews(self.p, now=1000), [])
        self.assertEqual(len(hoca.due_reviews(self.p, now=1000 + 86400)), 1)

    def test_grade_without_question_or_bad_json_is_explicit(self):
        with self.assertRaises(hoca.HocaError):
            hoca.grade(self.p, 'x')
        with patch.object(hoca.llm, 'ask', return_value='{"question":"S?","answer":"A"}'):
            hoca.check_question(self.p)
        with patch.object(hoca.llm, 'ask', return_value='tamam'):
            with self.assertRaises(hoca.HocaError):
                hoca.grade(self.p, 'x')
        self.assertEqual(hoca.current_step(self.p)['title'], 'Hücre nedir')  # hata ilerletmez

    def test_repeat_wrong_extends_interval_and_two_correct_reviews_clear_it(self):
        def q(): 
            with patch.object(hoca.llm, 'ask', return_value='{"question":"S?","answer":"A"}'):
                hoca.check_question(self.p)
        def g(ok, now):
            with patch.object(hoca.llm, 'ask', return_value='{"correct":%s,"feedback":"."}' % ('true' if ok else 'false')):
                return hoca.grade(self.p, 'a', now=now)
        q(); g(False, 0)
        w = hoca.weak_topics(self.p)[0]
        hoca.review_result(self.p, w['id'], True, now=86400)
        hoca.review_result(self.p, w['id'], True, now=86400 + 3 * 86400)
        self.assertEqual(hoca.weak_topics(self.p), [])
