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
        for t in ('sonraki konuya geç', 'Sonraki adıma geçelim', 'geç', 'ilerleyelim'):
            self.assertEqual(hoca.intent(t), 'next', t)
        for t in ('konuyu değiştir', 'başka konuya geçelim', 'dersi bitir'):
            self.assertEqual(hoca.intent(t), 'change', t)
        for t in ('mitokondri ne işe yarar', 'bir örnek ver', 'IĞDIR nerede', 'Osmanlı geç dönem nedir', 'devam eden süreç ne', 'geç kaldım', 'devam', 'devam et'):  # çıplak devam hedef motorunundur
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


TEACH = '{"text":"Hücre canlının yapı birimidir.","question":"Hücre neyin birimi?","answer":"Canlının yapı birimi"}'


class HocaChatTests(unittest.TestCase):
    def setUp(self):
        self.p = Profile()

    def _start(self):
        with patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]):
            return hoca.handle(self.p, 'hoca modu: hücre')

    def test_start_phrases_and_disabled_flag(self):
        out = self._start()
        self.assertIn('Hücre canlının yapı birimidir', out)
        self.assertIn('Hücre neyin birimi?', out)
        self.assertIn('cevap:', out)
        p2 = Profile()
        with patch.object(hoca.llm, 'ask') as ask:
            self.assertIsNone(hoca.handle(p2, 'hoca modu: hücre', enabled=False))
            self.assertIsNone(hoca.handle(p2, 'mitokondri konusunu öğret', enabled=False))
        ask.assert_not_called()
        p3 = Profile()
        with patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]):
            self.assertIn('Hücre neyin birimi?', hoca.handle(p3, 'Mitokondri konusunu öğret'))
        self.assertEqual(hoca.active(p3)['topic'], 'mitokondri')

    def test_no_topic_asks_for_one_without_model(self):
        with patch.object(hoca.llm, 'ask') as ask:
            out = hoca.handle(self.p, 'hoca modu')
        ask.assert_not_called()
        self.assertIn('Hangi konu', out)

    def test_unrelated_sentences_go_normal_path(self):
        self._start()
        with patch.object(hoca.llm, 'ask') as ask:
            for t in ('hava nasıl', 'yarın toplantı var mı', 'mitokondri ne işe yarar', 'ışığı kapat', 'cevap vermek zor'):
                self.assertIsNone(hoca.handle(self.p, t), t)
        ask.assert_not_called()
        self.assertEqual(hoca.current_step(self.p)['title'], 'Hücre nedir')

    def test_no_active_lesson_means_no_interception(self):
        with patch.object(hoca.llm, 'ask') as ask:
            for t in ('sonraki konuya geç', 'cevap: bir şey', 'devam', 'bilmiyorum', 'zayıf konularım'):
                self.assertIsNone(hoca.handle(self.p, t), t)
        ask.assert_not_called()

    def test_correct_answer_moves_on_with_next_explanation(self):
        self._start()
        nxt = '{"text":"Organeller hücrenin organlarıdır.","question":"Çekirdek ne yapar?","answer":"Yönetir"}'
        with patch.object(hoca.llm, 'ask', side_effect=['{"correct":true,"feedback":"Doğru."}', nxt]):
            out = hoca.handle(self.p, 'cevap: canlının yapı birimi')
        self.assertIn('Doğru.', out)
        self.assertIn('Organeller', out)
        self.assertIn('Çekirdek ne yapar?', out)

    def test_wrong_answer_shows_expected_and_stays(self):
        self._start()
        with patch.object(hoca.llm, 'ask', return_value='{"correct":false,"feedback":"Eksik."}'):
            out = hoca.handle(self.p, 'cevabım: organ')
        self.assertIn('Canlının yapı birimi', out)
        self.assertEqual(hoca.current_step(self.p)['title'], 'Hücre nedir')
        self.assertEqual(len(hoca.weak_topics(self.p)), 1)

    def test_give_up_marks_weak_without_model_call(self):
        self._start()
        with patch.object(hoca.llm, 'ask') as ask:
            out = hoca.handle(self.p, 'bilmiyorum')
        ask.assert_not_called()
        self.assertIn('Canlının yapı birimi', out)
        self.assertEqual(len(hoca.weak_topics(self.p)), 1)

    def test_next_and_change_commands(self):
        self._start()
        nxt = '{"text":"T2","question":"Q2?","answer":"A2"}'
        with patch.object(hoca.llm, 'ask', return_value=nxt):
            out = hoca.handle(self.p, 'sonraki adıma geç')
        self.assertIn('Q2?', out)
        self.assertEqual(hoca.current_step(self.p)['title'], 'Organeller')
        out = hoca.handle(self.p, 'konuyu değiştir')
        self.assertIn('bıraktım', out)
        self.assertIsNone(hoca.active(self.p))

    def test_model_error_is_shown_not_swallowed(self):
        self._start()
        with patch.object(hoca.llm, 'ask', side_effect=RuntimeError('429')):
            out = hoca.handle(self.p, 'cevap: x')
        self.assertIn('hazırlanamadı', out)
        self.assertEqual(hoca.current_step(self.p)['title'], 'Hücre nedir')

    def test_last_step_finishes_lesson(self):
        with patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]):
            hoca.handle(self.p, 'hoca modu: hücre')
        hoca.advance(self.p); hoca.advance(self.p)
        out = hoca.handle(self.p, 'sonraki adıma geç')
        self.assertIn('Ders bitti', out)
        self.assertIsNone(hoca.active(self.p))

    def test_weak_list_command(self):
        self._start()
        hoca.handle(self.p, 'bilmiyorum')
        out = hoca.handle(self.p, 'zayıf konularım')
        self.assertIn('Hücre nedir', out)


class HocaEngineHookTests(unittest.TestCase):
    """engine_tools._study_intent: hoca satırları, yalnız açık söyleniş ve aktif ders yakalanır."""

    def _runtime(self, profile):
        import re
        from types import SimpleNamespace
        return SimpleNamespace(profile=profile, re=re, emit=lambda *a: None, _record_failure=lambda *a: None,
                               _MEDIA_Q=re.compile(r"(?!x)x"), _study_media_topic=lambda t: '')

    def _call(self, profile, text, enabled=True):
        from modules import engine_tools
        with patch('config.load_settings', return_value={'hoca_enabled': enabled}):
            return engine_tools._study_intent(self._runtime(profile), text)

    def test_hoca_closed_open_unrelated_and_active_rows(self):
        p = Profile()
        rows_none = [('hoca modu: hücre', False), ('hava nasıl', True), ('sonraki konuya geç', True), ('cevap: x', True)]
        with patch.object(hoca.llm, 'ask') as ask, patch('modules.study._state', return_value={'docs': []}):
            for text, enabled in rows_none:
                self.assertIsNone(self._call(p, text, enabled), text)
        ask.assert_not_called()
        with patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]):
            self.assertIn('Hücre neyin birimi?', self._call(p, 'hoca modu: hücre'))
        with patch.object(hoca.llm, 'ask') as ask, patch('modules.study._state', return_value={'docs': []}):
            self.assertIsNone(self._call(p, 'hava nasıl'))
            self.assertIsNone(self._call(p, 'bugün hangi konuya çalışayım'))
        ask.assert_not_called()
        nxt = '{"text":"T2","question":"Q2?","answer":"A2"}'
        with patch.object(hoca.llm, 'ask', return_value=nxt):
            self.assertIn('Q2?', self._call(p, 'sonraki adıma geç'))


class HocaSnapshotTests(unittest.TestCase):
    def test_snapshot_without_lesson_and_with_lesson(self):
        p = Profile()
        self.assertEqual(hoca.snapshot(p, enabled=False), {'enabled': False, 'lesson': None, 'weak': []})
        with patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]) as ask:
            hoca.handle(p, 'hoca modu: hücre')
            n = ask.call_count
            snap = hoca.snapshot(p)
            self.assertEqual(ask.call_count, n)  # model çağırmaz
        self.assertEqual(snap['lesson']['step'], 1)
        self.assertEqual(snap['lesson']['total'], 3)
        self.assertEqual(snap['lesson']['question'], 'Hücre neyin birimi?')
        self.assertEqual(snap['lesson']['steps'], ['Hücre nedir', 'Organeller', 'Zar'])
        hoca.handle(p, 'bilmiyorum')
        w = hoca.snapshot(p, now=0)['weak'][0]
        self.assertFalse(w['due_now'])
        self.assertTrue(hoca.snapshot(p, now=w['due'])['weak'][0]['due_now'])


class HocaBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_privacy_voice_and_pending  # noqa: F401 - web içe aktarımı için donanım adaptörleri (test_local_stt gibi)

    def test_settings_save_stores_flag_as_real_boolean(self):
        import web
        bridge = web.Bridge.__new__(web.Bridge)
        with patch.object(web.config, 'save_settings') as save, patch.object(web, '_wakeword'):
            bridge.settings_save({'hoca_enabled': False})
            save.assert_called_once_with(hoca_enabled=False)
            bridge.settings_save({'hoca_enabled': 1})
            save.assert_called_with(hoca_enabled=True)

    def test_study_overview_carries_hoca_snapshot_without_model_call(self):
        from types import SimpleNamespace
        import web_study_exams
        p = Profile()
        with patch.object(hoca.llm, 'ask', side_effect=[PLAN, TEACH]):
            hoca.handle(p, 'hoca modu: hücre')
        ex = SimpleNamespace(stats=lambda p: {}, courses=lambda p: [], selected=lambda p: [], focus=lambda p, n: [],
                             plan=lambda p: {}, today=lambda p: {}, wrong_summary=lambda p: {}, mock_status=lambda p: {})
        services = SimpleNamespace(exams=ex, study=SimpleNamespace(status=lambda p: {}), current_profile=lambda: p)
        owner = SimpleNamespace(_study_dependencies=services, _hoca_snapshot=lambda prof: web_study_exams.WebStudyExams._hoca_snapshot(None, prof))
        with patch.object(hoca.llm, 'ask') as ask, patch('config.load_settings', return_value={'hoca_enabled': False}):
            out = web_study_exams.WebStudyExams.study_overview(owner)
        ask.assert_not_called()
        self.assertEqual(out['hoca']['lesson']['topic'], 'hücre')
        self.assertFalse(out['hoca']['enabled'])


class HocaParsePlanBoundaryTests(unittest.TestCase):
    @staticmethod
    def _plan(count):
        return '{"steps":[' + ','.join(
            f'{{"title":"T{i}","goal":"G{i}"}}' for i in range(1, count + 1)) + ']}'

    def test_one_valid_step_is_rejected(self):
        with self.assertRaises(hoca.HocaError):
            hoca.parse_plan(self._plan(1))

    def test_exactly_two_valid_steps_are_returned(self):
        steps = hoca.parse_plan(self._plan(2))
        self.assertEqual(len(steps), 2)
        self.assertEqual([step['title'] for step in steps], ['T1', 'T2'])

    def test_nine_valid_steps_are_capped_at_first_eight(self):
        steps = hoca.parse_plan(self._plan(9))
        self.assertEqual(len(steps), 8)
        self.assertEqual([step['title'] for step in steps], [f'T{i}' for i in range(1, 9)])

    def test_blank_title_or_goal_items_do_not_count(self):
        plan = ('{"steps":['
                '{"title":"T1","goal":"G1"},'
                '{"title":"","goal":"boş başlık"},'
                '{"title":"boş hedef","goal":""},'
                '{"title":"   ","goal":"   "},'
                '{"title":"T2","goal":"G2"}]}')
        steps = hoca.parse_plan(plan)
        self.assertEqual(len(steps), 2)
        self.assertEqual([step['title'] for step in steps], ['T1', 'T2'])

    def test_non_json_text_is_rejected(self):
        with self.assertRaises(hoca.HocaError):
            hoca.parse_plan('Bu bir JSON ders planı değil.')
