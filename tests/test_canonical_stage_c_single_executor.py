"""Karar 2 Aşama C: Scheduler tek fiziksel yürütücüdür, eski yollar kapalıdır.

Gerçek UIA, tarayıcı veya model çağrısı yapılmaz; motorlar taklit edilir.
Ölçülen sözleşme: yeni masaüstü/etkileşimli tarayıcı işi yalnız canonical
hedef doğar, yürütme yetkisini yalnız Core onay kartı verir.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

if 'pyautogui' not in sys.modules:
    from unittest.mock import MagicMock
    _keyboard = types.ModuleType('pyautogui')
    _keyboard.__getattr__ = lambda _: MagicMock()
    sys.modules['pyautogui'] = _keyboard

from modules import (
    browser_agent, canonical_desktop_frontdoor, canonical_goal_flow, goal_tools,
    requests_state, task_agents, task_queue, task_tools, team_center,
    team_control_service,
)
from modules import desktop_agent as agent

OWNER = 'alice'
URL = 'https://example.org/form'
TYPED = 'PC görevi: Hesap Makinesi | 12 ile 7 topla'
SPOKEN = 'pc görevi Hesap Makinesi 12 ile 7 topla'
DESKTOP_NODE = {'id': 'pc', 'agent': 'desktop', 'depends': [],
                'input': {'target': 'Hesap Makinesi', 'goal': '12 ile 7 topla'}}
BROWSER_TEXT = 'tarayıcı görevi: https://example.org/form | formu doldur ve gönder'
BROWSER_INPUT = {'url': URL, 'instruction': 'formu doldur ve gönder', 'mode': 'interactive'}


class FrontDoorAdmissionTests(unittest.TestCase):
    def _call(self, command=TYPED, *, current=None, source='yazı', active=True, rid='rid-1'):
        token = requests_state._current.set((OWNER, rid) if rid is not None else None)
        self.addCleanup(requests_state._current.reset, token)
        create = mock.Mock(return_value=('a' * 16, 'Hedefin kaydedildi.'))
        with patch.object(task_queue, 'scheduler_active', return_value=active), \
             patch.object(canonical_goal_flow, 'try_create', create):
            reply = canonical_desktop_frontdoor.dispatch(OWNER, command, current=current, source=source)
        return reply, create

    def test_typed_task_becomes_one_canonical_goal(self):
        reply, create = self._call()
        self.assertEqual(reply, 'Hedefin kaydedildi.')
        create.assert_called_once_with(OWNER, 'rid-1', TYPED, direct_tasks=[DESKTOP_NODE])

    def test_spoken_typed_form_uses_the_same_admission(self):
        reply, create = self._call(SPOKEN)
        self.assertEqual(reply, 'Hedefin kaydedildi.')
        self.assertEqual(create.call_args.kwargs['direct_tasks'], [DESKTOP_NODE])

    def test_inactive_scheduler_creates_no_goal(self):
        reply, create = self._call(active=False)
        self.assertEqual(reply, 'Canonical Scheduler hazır değil; masaüstü görevi başlatılmadı.')
        create.assert_not_called()

    def test_missing_command_identity_is_refused(self):
        for rid in (None, ''):
            with self.subTest(rid=rid), self.assertRaises(PermissionError):
                self._call(rid=rid)

    def test_other_sentences_reach_the_engine(self):
        for command in ('pc görevi durumu', 'pc görevi ayrıntı', 'PC görevi iptal', 'PC izin ver',
                        'PC izinleri', 'hesap makinesi 12 ile 7 topla', 'PC görevi: yalnız hedef',
                        'PC görevi: hedef | ', 'pc görevi başka bir şey yapma'):
            with self.subTest(command=command):
                reply, create = self._call(command)
                self.assertIsNone(reply, command)
                create.assert_not_called()

    def test_phone_and_another_active_user_stay_with_the_engine(self):
        reply, create = self._call(source='telefon')
        self.assertIsNone(reply)
        create.assert_not_called()
        reply, create = self._call(current=lambda: 'bob')
        self.assertIsNone(reply)
        create.assert_not_called()


class DirectAdmissionGateTests(unittest.TestCase):
    """The planner-free admission accepts exactly the registry's typed roots."""

    def _tmp_root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def _try(self, node, text):
        from modules import goal_executor
        planned = mock.Mock(return_value=('jid', 'Planlandı'))
        with patch.object(goal_executor, '_root', return_value=self._tmp_root()), \
             patch.object(canonical_goal_flow, '_try_create_planned', planned):
            reply = canonical_goal_flow.try_create(OWNER, 'rid-' + node['id'], text, direct_tasks=[node])
        return reply, planned

    def test_registry_roots_pass_the_gate(self):
        cases = (
            (DESKTOP_NODE, TYPED),
            ({'id': 'browser', 'agent': 'browser', 'depends': [], 'input': dict(BROWSER_INPUT)}, BROWSER_TEXT),
            ({'id': 'video', 'agent': 'media', 'depends': [],
              'input': {'scenes': [{'caption': 'Sahne', 'duration': 3}]}},
             'video üret {"scenes":[{"caption":"Sahne","duration":3}]}'),
        )
        for node, text in cases:
            with self.subTest(id=node['id']):
                reply, planned = self._try(node, text)
                self.assertEqual(reply, ('jid', 'Planlandı'))
                planned.assert_called_once()

    def test_smuggled_roots_are_rejected_before_any_planning(self):
        good_input = {'target': 'calc', 'goal': '12 ile 7 topla'}
        cases = [
            ({'id': 'desktop', 'agent': 'desktop', 'depends': [], 'input': good_input}, TYPED),
            ({'id': 'pc', 'agent': 'browser', 'depends': [], 'input': dict(BROWSER_INPUT)}, TYPED),
            ({'id': 'pc', 'agent': 'desktop', 'depends': ['r'], 'input': good_input}, TYPED),
            ({'id': 'pc', 'agent': 'desktop', 'depends': [], 'input': good_input},
             'hesap makinesinde 12 ile 7 topla'),
            ({'id': 'pc', 'agent': 'desktop', 'depends': [], 'input': good_input}, BROWSER_TEXT),
            ({'id': 'browser', 'agent': 'browser', 'depends': [], 'input': dict(BROWSER_INPUT)}, TYPED),
        ]
        for node, text in cases:
            with self.subTest(id=node['id'], text=text[:24]), self.assertRaises(ValueError):
                canonical_goal_flow.try_create(OWNER, 'rid', text, direct_tasks=[node])
        for tasks in ([], [DESKTOP_NODE, DESKTOP_NODE], [{'agent': 'desktop'}], 'pc'):
            with self.subTest(tasks=str(tasks)), self.assertRaises(ValueError):
                canonical_goal_flow.try_create(OWNER, 'rid', TYPED, direct_tasks=tasks)


class SchedulerOnlyExecutionTests(unittest.TestCase):
    """Tool-level fresh starts need the marker the dispatching round writes."""

    def setUp(self):
        from modules import llm
        token = llm._key_context.set(OWNER)
        self.addCleanup(llm._key_context.reset, token)

    def _runtime(self):
        return SimpleNamespace(profile=SimpleNamespace(slug=OWNER, data={}),
                               emit=lambda *args, **kwargs: None,
                               pc_profile=lambda: SimpleNamespace(slug=OWNER),
                               _cur_source='scheduler')

    def _data(self):
        return {'target': 'calc', 'goal': '12 ile 7 topla'}

    def test_desktop_fresh_start_without_offer_is_refused(self):
        fake = mock.Mock()
        fake._load.return_value = None
        with patch('modules.desktop_agent', fake, create=True):
            with self.assertRaises(goal_tools.NotStarted):
                goal_tools.execute(self._runtime(), 'desktop', self._data(), {}, {'owner': OWNER})
        fake.handle.assert_not_called()

    def test_interactive_browser_without_offer_is_refused(self):
        identity = {'owner': OWNER, 'job_id': 'g1', 'task_id': 's1'}
        with patch.object(task_agents, 'worker') as worker:
            with self.assertRaises(goal_tools.NotStarted):
                goal_tools.execute(self._runtime(), 'browser', dict(BROWSER_INPUT), {}, identity)
        worker.assert_not_called()

    def test_desktop_legacy_approval_consumer_is_gone(self):
        import inspect
        source = inspect.getsource(goal_tools.execute)
        self.assertNotIn("approval.get('desktop_id')", source)
        self.assertNotIn("'resume_id'", source)
        self.assertNotIn('desktop', goal_tools.LOCAL)
        self.assertIn('desktop', goal_tools.LOCAL_EVIDENCE)

    def test_desktop_input_has_no_answer_or_resume_fields(self):
        for extra in ({'answer': 'evet'}, {'resume_id': 'dj1'}, {'approval': 'x'}):
            with self.subTest(**extra), self.assertRaises(ValueError):
                task_tools.validate_input('desktop', {'target': 'calc', 'goal': 'x', **extra})


class NativeEngineOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(agent, 'STORE', Path(temporary.name)))
        self.enterContext(patch.object(agent.privacy, 'blocked', return_value=None))

    def _job(self, **extra):
        job = {'id': 'j1', 'owner': OWNER, 'target': 'calc', 'goal': '12 ile 7 topla',
               'status': 'approval', 'history': [], 'hwnd': None,
               'approval': {'id': 'ap1'}, 'pending_effect': None}
        job.update(extra)
        agent._save(job)
        return job

    def test_creation_stamps_the_requesting_owner(self):
        for source, expected in (('scheduler', 'scheduler'), ('yazı', 'command')):
            with self.subTest(source=source):
                self._job(status='done')
                with patch.object(agent, 'run', return_value='çalıştı') as run:
                    agent.handle(OWNER, TYPED, source=source)
                self.assertEqual(agent._load(OWNER)['origin'], expected)
                run.assert_called_once()

    def test_a_native_job_without_origin_stays_controllable(self):
        self._job()
        with patch.object(agent, 'run', return_value='çalıştı') as run:
            self.assertEqual(agent.handle(OWNER, 'PC onayla ap1'), 'çalıştı')
        self.assertEqual(run.call_args.kwargs.get('approval'), 'ap1')

    def test_scheduler_origin_refuses_chat_control(self):
        self._job(origin='scheduler')
        for command in ('PC görevi devam', 'PC onayla ap1', 'PC görevi cevap: evet'):
            with self.subTest(command=command), patch.object(agent, 'run') as run:
                reply = agent.handle(OWNER, command)
            self.assertIn('hedef onayla', reply)
            self.assertEqual(agent._load(OWNER)['status'], 'approval')
            self.assertIsNone(agent._load(OWNER).get('answer'))
            run.assert_not_called()

    def test_scheduler_origin_question_answer_is_refused(self):
        job = self._job(status='question', question='Hangi dosya?', origin='scheduler')
        with patch.object(agent, 'run') as run:
            reply = agent.answer_typed(OWNER, 'not defteri', expected_job_id=job['id'],
                                       expected_question='Hangi dosya?',
                                       current=lambda: OWNER)
        self.assertIn('hedef onayla', reply)
        run.assert_not_called()
        self.assertIsNone(agent._load(OWNER).get('answer'))

    def test_reads_and_cancel_stay_available_for_scheduler_goals(self):
        self._job(origin='scheduler')
        with patch.object(agent, 'run') as run:
            read = agent.handle(OWNER, 'pc görevi durumu')
            self.assertIsInstance(read, str)
            self.assertEqual(agent._load(OWNER)['status'], 'approval')
            self.assertEqual(agent.handle(OWNER, 'PC görevi iptal'), 'Masaüstü görevini iptal ettim.')
        run.assert_not_called()
        self.assertEqual(agent._load(OWNER)['status'], 'cancelled')


class LegacyTaskControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(task_agents, 'STORE', Path(temporary.name) / 'tasks'))
        from modules import llm
        token = llm._key_context.set(OWNER)
        self.addCleanup(llm._key_context.reset, token)

    def _job(self, agent_kind):
        approval_id = 'a' * 16
        job = {'id': {'browser': 'b' + '0' * 11, 'desktop': 'd' + '0' * 11,
                      'publish': 'c' + '0' * 11}[agent_kind],
               'owner': OWNER, 'state': 'approval', 'created': 1, 'instruction': 'istem',
               'schema': 2, 'events': [],
               'tasks': [{'id': 's1', 'agent': agent_kind, 'depends': [], 'input': {},
                          'state': 'approval'}],
               'outputs': {'s1': {'state': 'approval', 'id': approval_id}}}
        task_agents._save(task_agents._root(OWNER), job)
        return job, approval_id

    def test_only_publish_keeps_a_legacy_task_approval(self):
        from modules import goal_executor
        for agent_kind, allowed in (('browser', False), ('desktop', False), ('publish', True)):
            with self.subTest(agent=agent_kind):
                job, approval_id = self._job(agent_kind)
                control = goal_executor.control_key(task_agents._load(OWNER, job['id']))
                submit = mock.Mock(return_value=True)
                if allowed:
                    reply = team_control_service.dispatch(
                        OWNER, 'Alice', submit, 'task', job['id'], 'approve', control,
                        approval_id=approval_id)
                    self.assertIn('iletildi', reply)
                    self.assertEqual(submit.call_args.args[0], 'işlem onayla ' + approval_id)
                else:
                    with self.assertRaises(ValueError):
                        team_control_service.dispatch(
                            OWNER, 'Alice', submit, 'task', job['id'], 'approve', control,
                            approval_id=approval_id)
                    submit.assert_not_called()


class EnginePausePointerTests(unittest.TestCase):
    def test_pending_plan_message_points_at_the_core_card(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        page = SimpleNamespace(url=URL)
        with patch.object(browser_agent, '_digest', return_value='d' * 64), \
             patch.object(browser_agent, '_signature', return_value='s' * 64):
            result = browser_agent._save_pending(
                root, page, [{'op': 'click', 'selector': '#send'}], object())
        self.assertEqual(result['state'], 'approval')
        self.assertIn('İşlem planı hazır', result['message'])
        self.assertIn('yalnız hedefin Core onay kartıyla uygulanır', result['message'])
        self.assertNotIn('tarayıcı onayla', result['message'])
        pending = json.loads((root / 'pending.json').read_text(encoding='utf-8'))
        self.assertEqual(pending['id'], result['id'])

    def test_engine_foreground_handler_is_removed(self):
        self.assertFalse(hasattr(browser_agent, 'handle'))


class SpecialistDirectoryTests(unittest.TestCase):
    def test_desktop_stays_a_routable_tool_with_scheduler_scope(self):
        rows = {row['id']: row for row in team_center.capabilities()}
        self.assertIn('desktop', rows)
        self.assertIn('canonical Scheduler', rows['desktop']['scope'])
        self.assertIn('Core onay kartı', rows['desktop']['scope'])

    def test_default_team_directory_still_validates(self):
        entries = team_center._validate(team_center.DEFAULTS)
        self.assertEqual([entry['id'] for entry in entries],
                         [entry['id'] for entry in team_center.DEFAULTS])


if __name__ == '__main__':
    unittest.main()
