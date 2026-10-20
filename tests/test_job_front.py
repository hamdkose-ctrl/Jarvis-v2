"""Tek giriş (motor birleştirme adım 3): çıplak "devam"/"iptal" yalnız hedef işi yoksa açık görev işine gider.

Gerçek EngineContext.handle kullanılır; iş kayıtları taklit, model çağrılmaz. Önceki davranış (hedef önceliği, "görev …"
ve "hedef …" önekleri, onay kelimeleri) aynen korunur.
"""
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from test_mail_calendar_fixes import ProfileCase, _runtime
from modules import goal_executor, task_agents

NOW = time.time()


def _task(state, age=60):
    return {'state': state, 'id': 'tt1', 'tasks': [], 'outputs': {}, 'instruction': 'rapor', 'updated': NOW - age}


class JobFrontTests(ProfileCase):
    def _run(self, text, goal=None, task=None, pending=None):
        rt = _runtime(self, self.profile, datetime(2026, 10, 18, 9, 0))
        for name, value in (pending or {}).items():
            setattr(rt._session(), name, value)
        calls = []
        g = {'state': goal, 'owner': rt.profile.slug, 'id': 'a' * 16, 'steps': [], 'goals': [], 'outputs': {}, 'waiting': None} if goal else None

        def goal_save(job):
            calls.append('goal.save:' + job['state'])

        def task_continue(*a, **k):
            calls.append('task.continue')
            return {**_task('done'), 'id': 'tt1'}

        def task_cancel(*a, **k):
            calls.append('task.cancel')
            return {**_task('cancelled'), 'id': 'tt1'}

        with patch.object(goal_executor, 'latest', return_value=g), \
                patch.object(goal_executor, 'run', side_effect=lambda *a, **k: calls.append('goal.run') or 'G'), \
                patch.object(goal_executor, '_save', side_effect=goal_save), \
                patch.object(goal_executor, 'render', return_value='G-render'), \
                patch.object(task_agents, 'recent', return_value=task), \
                patch.object(task_agents, 'continue_job', side_effect=task_continue), \
                patch.object(task_agents, 'cancel_job', side_effect=task_cancel), \
                patch('modules.router.classify', side_effect=RuntimeError('sohbete düştü')):
            try:
                reply = rt.handle(text)
            except Exception:                       # sahte bekleyen durum sonraki yolları bozabilir; önemli olan çağrılar
                reply = 'SOHBET'
        return calls, str(reply)

    def test_bare_continue_reaches_open_task_job_when_no_goal_is_open(self):
        for state in ('interrupted', 'incomplete', 'approval'):
            for text in ('devam', 'devam et', 'sürdür'):
                with self.subTest(state=state, text=text):
                    calls, reply = self._run(text, task=_task(state))
                    self.assertEqual(calls, ['task.continue'])
                    self.assertIn('Görev tt1', reply)

    def test_bare_cancel_reaches_open_task_job_instead_of_chat(self):
        for text in ('iptal', 'vazgeç', 'boşver'):
            with self.subTest(text=text):
                calls, reply = self._run(text, task=_task('interrupted'))
                self.assertEqual(calls, ['task.cancel'])
                self.assertNotEqual(reply, 'SOHBET')

    def test_open_goal_keeps_priority_for_bare_words(self):
        calls, _ = self._run('devam', goal='paused', task=_task('interrupted'))
        self.assertEqual(calls, ['goal.run'])
        calls, _ = self._run('iptal', goal='paused', task=_task('interrupted'))
        self.assertEqual(calls, ['goal.save:cancelled'])

    def test_finished_stale_or_running_task_jobs_are_not_taken(self):
        for task in (_task('done'), _task('cancelled'), _task('running'), _task('interrupted', age=2 * 86400), None):
            with self.subTest(task=task and (task['state'], task['updated'])):
                calls, _ = self._run('iptal', task=task)
                self.assertEqual(calls, [])

    def test_bare_cancel_with_nothing_open_answers_directly_not_via_model(self):
        for task in (None, _task('done'), _task('cancelled')):
            for text in ('iptal', 'vazgeç', 'boşver'):
                with self.subTest(text=text, task=task and task['state']):
                    calls, reply = self._run(text, task=task)
                    self.assertEqual(calls, [])
                    self.assertEqual(reply, 'Şu an iptal edilecek bir işlem yok.')   # SOHBET olsaydı model yoluna düşmüştü

    def test_pending_questions_keep_their_own_answers(self):
        for field in ('pending_confirm', 'pending_action', 'pending_msg', 'pending_organize', 'pending_desktop', 'pending_app'):
            with self.subTest(field=field):
                calls, _ = self._run('vazgeç', task=_task('interrupted'), pending={field: object()})
                self.assertNotIn('task.cancel', calls)

    def test_prefixed_commands_and_confirmation_words_are_unchanged(self):
        calls, _ = self._run('görev devam', goal='paused', task=_task('interrupted'))
        self.assertEqual(calls, ['task.continue'])
        calls, _ = self._run('görev iptal', task=_task('interrupted'))
        self.assertEqual(calls, ['task.cancel'])
        calls, _ = self._run('hedef iptal', goal='paused', task=_task('interrupted'))
        self.assertEqual(calls, ['goal.save:cancelled'])
        calls, _ = self._run('evet', task=_task('approval'))      # dış gönderim onayı yalnız açık "işlem onayla <kimlik>" ile
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
