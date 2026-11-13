"""Bounded resume/cancel contracts through the real Brain State Gate -> Engine.

The old raw EngineContext.handle call without a bound Brain turn is not a
production entry point. A real prepare/bind is mandatory in these tests;
existing goal/job workers are mocked, and the general model must not be called.
"""
import time
import unittest
import uuid
from datetime import datetime
from unittest.mock import Mock, patch

from test_mail_calendar_fixes import ProfileCase, _runtime
from modules import brain_context, goal_executor, task_agents
from modules.diagnostics import record_failure as _record_failure

NOW = time.time()


def _task(state, age=60):
    return {'state': state, 'id': 'tt1', 'tasks': [], 'outputs': {}, 'instruction': 'rapor', 'updated': NOW - age}


class JobFrontTests(ProfileCase):
    def _run(self, text, goal=None, task=None, pending=None, photo_pending=False, forbid_model=False,
             canonical=True):
        rt = _runtime(self, self.profile, datetime(2026, 10, 18, 9, 0))
        if photo_pending:
            rt._pending_photo[rt.profile.slug] = {'t': time.time(), 'path': 'fake-photo.jpg'}
            self.addCleanup(rt._pending_photo.pop, rt.profile.slug, None)
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

        def execute():
            if not canonical:
                return rt.handle(text)
            from modules import brain_entry, requests_state
            rid = 'rid-job-front-' + uuid.uuid4().hex[:12]
            self.assertTrue(requests_state.register(rt.profile.slug, rid))
            with requests_state.activate(rt.profile.slug, rid):
                entry = brain_entry.prepare(
                    rt,
                    owner=rt.profile.slug,
                    request_id=rid,
                    text=text,
                    source='telefon',
                )
                with brain_entry.bind(entry):
                    return rt.handle(text)

        # PR10c: `modules.router` sınıfleyicisi kaldırıldı. Aynı bekçi model kapılarının
        # kendisinde: bu komutlar deterministik yoldan geçer, hiçbir model çağrısına düşmez.
        model = Mock(side_effect=RuntimeError('sohbete düştü'))
        with patch.object(brain_context, '_default_goal_reader', return_value=g), \
                patch.object(goal_executor, 'latest', return_value=g), \
                patch.object(goal_executor, 'run', side_effect=lambda *a, **k: calls.append('goal.run') or 'G'), \
                patch.object(goal_executor, '_save', side_effect=goal_save), \
                patch.object(goal_executor, 'render', return_value='G-render'), \
                patch.object(task_agents, 'recent', return_value=task), \
                patch.object(task_agents, 'continue_job', side_effect=task_continue), \
                patch.object(task_agents, 'cancel_job', side_effect=task_cancel), \
                patch.object(rt, 'ask', model), patch.object(rt, 'chat', model):
            try:
                reply = execute()
            except Exception:                       # sahte bekleyen durum sonraki yolları bozabilir; önemli olan çağrılar
                _record_failure('tests/test_job_front.py:_run')
                reply = 'SOHBET'
            if forbid_model:
                model.assert_not_called()
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
                    self.assertEqual(reply, 'İptal edilecek açık görev yok.')   # Kart 58'in istediği kesin metin; eşitlik korunur.

    def test_card58_empty_cancel_words_never_reach_model_or_app_action(self):
        for text in ('iptal', 'vazgeç.', 'boşver'):
            with self.subTest(text=text), patch('modules.app_actions.voice') as action:
                calls, reply = self._run(text, forbid_model=True)
                self.assertEqual(reply, 'İptal edilecek açık görev yok.')
                self.assertEqual(calls, [])
                action.assert_not_called()

    def test_card58_pending_shutdown_keeps_confirmation_response(self):
        calls, reply = self._run('iptal', pending={'pending_confirm': 'shutdown'}, forbid_model=True)
        self.assertEqual(reply, 'Tamam, vazgeçtim.')
        self.assertEqual(calls, [])

    def test_card58_pending_photo_keeps_photo_cancel_response(self):
        # Photo cancel is now an exact canonical state protocol; keep the same user-visible behavior
        # while exercising the real bound Brain entry instead of the retired surface regex authority.
        calls, reply = self._run('iptal', photo_pending=True, forbid_model=True, canonical=True)
        self.assertEqual(reply, 'Tamam, fotoğrafla bir şey yapmıyorum.')
        self.assertEqual(calls, [])

    def test_card58_continue_and_open_goal_still_fall_through(self):
        from types import SimpleNamespace
        from modules import job_front
        with patch.object(goal_executor, 'active', return_value=False), patch.object(job_front, '_goal_open', return_value=False), patch.object(task_agents, 'recent', return_value=None):
            self.assertIsNone(job_front.route(self.profile.slug, lambda *a: None, 'devam', SimpleNamespace()))
            with patch.object(job_front, '_goal_open', return_value=True):
                self.assertIsNone(job_front.route(self.profile.slug, lambda *a: None, 'iptal', SimpleNamespace()))

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
