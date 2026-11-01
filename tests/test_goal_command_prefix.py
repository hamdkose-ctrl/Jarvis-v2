"""Explicit command prefixes are syntax, not news topics; no real model/account."""
from datetime import datetime
from unittest.mock import patch
from test_mail_calendar_fixes import ProfileCase, _runtime
from modules import brain_entry, goal_executor as goals, model_free_news


class GoalCommandPrefixTests(ProfileCase):
    def test_engine_explicit_goal_prefix_is_removed_once_before_run(self):
        for command, expected in [('hedef son dakika haberleri', 'son dakika haberleri'),
                                  ('hedef: son dakika haberleri', 'son dakika haberleri'),
                                  ('hedef hedef belirleme konusunda rapor hazırla', 'hedef belirleme konusunda rapor hazırla')]:
            with self.subTest(command=command):
                rt = _runtime(self, self.profile, datetime(2026, 10, 20, 12))
                # PR10c: `hedef:` öneki canonical karar kapısından önce yürür; bu cümle için
                # brain_entry.route_command hiç çağrılmaz (tek sınıflandırma kapısı budur).
                with patch.object(goals, 'active', return_value=False), \
                     patch.object(goals, 'latest', return_value=None), \
                     patch.object(goals, 'run', return_value='Görev başlangıcı') as run, \
                     patch.object(brain_entry, 'route_command', return_value={'intent': 'task', 'args': {}}) as route:
                    self.assertEqual(rt.handle(command), 'Görev başlangıcı')
                run.assert_called_once_with(rt, expected)
                route.assert_not_called()
                if 'son dakika' in expected:
                    self.assertEqual(model_free_news.terms(run.call_args.args[1]), [])

    def test_explicit_goal_is_not_an_answer_to_an_older_question(self):
        rt = _runtime(self, self.profile, datetime(2026, 10, 20, 12))
        with patch.object(goals, 'latest', return_value={'state': 'question'}), \
             patch.object(goals, 'age', return_value=0), \
             patch.object(goals, 'run', return_value='Yeni istek') as run:
            self.assertEqual(goals.handle(rt, 'hedef son dakika haberleri'), 'Yeni istek')
        run.assert_called_once_with(rt, 'son dakika haberleri')

    def test_cancel_without_a_job_never_starts_a_goal_named_cancel(self):
        rt = _runtime(self, self.profile, datetime(2026, 10, 20, 12))
        with patch.object(goals, 'latest', return_value=None), patch.object(goals, 'run') as run:
            self.assertEqual(goals.handle(rt, 'hedef iptal'), 'Kayıtlı hedef yok.')
        run.assert_not_called()

    def test_reserved_controls_keep_their_existing_meaning(self):
        rt = _runtime(self, self.profile, datetime(2026, 10, 20, 12))
        with patch.object(goals, 'latest', return_value=None), patch.object(goals, 'run') as run:
            goals.handle(rt, 'hedef devam')
            run.assert_called_once_with(rt, 'hedef devam', resume=True)
            run.reset_mock()
            goals.handle(rt, 'hedef onayla')
            run.assert_called_once_with(rt, 'hedef onayla', resume=True, approve=True)
