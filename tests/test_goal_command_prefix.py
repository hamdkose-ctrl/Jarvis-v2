"""Explicit command prefixes are syntax, not news topics; no real model/account."""
from modules import core_brain_adapter
from datetime import datetime
from unittest.mock import patch
from test_mail_calendar_fixes import ProfileCase, _runtime
from modules import brain_entry, goal_executor as goals, model_free_news


class GoalCommandPrefixTests(ProfileCase):
    def test_engine_explicit_goal_prefix_is_removed_once_before_run(self):
        from dataclasses import replace
        from modules.brain_contracts import RequestKind, GoalOperation
        from modules import requests_state
        import uuid
        for command in ('hedef son dakika haberleri', 'hedef: son dakika haberleri',
                        'hedef hedef belirleme konusunda rapor hazırla'):
            rt = _runtime(self, self.profile, datetime(2026, 10, 20, 12))
            def model(current, text, *, active_context=None):
                return replace(current, request_kind=RequestKind.GOAL_CONTROL,
                               goal_operation=GoalOperation.CREATE, goal_card={'kind': 'goal', 'title': text})
            rid = uuid.uuid4().hex
            requests_state.register(rt.profile.slug, rid)
            with requests_state.activate(rt.profile.slug, rid), \
                 patch.object(brain_entry, 'apply_model_understanding', side_effect=model), \
                 patch('modules.canonical_goal_flow.try_create', return_value=None), \
                 patch.object(goals, 'run', return_value='Görev başlangıcı') as run:
                entry = brain_entry.prepare(rt, owner=rt.profile.slug, request_id=rid, text=command,
                                            source='yazı', model_understanding=True)
                output, _, _ = core_brain_adapter.handoff(rt, entry, rt.handle, command)
            self.assertEqual(output, 'Görev başlangıcı')
            # Only the existing goal worker may normalize its own explicit prefix.
            # Core delivers the user's original text once, never a model rewrite.
            run.assert_called_once_with(rt, command)

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

    def test_exact_canonical_effect_approval_reaches_core_without_model_reclassification(self):
        from modules import engine_commands
        rt = _runtime(self, self.profile, datetime(2026, 10, 20, 12))
        command = 'hedef onayla ' + '1' * 16 + ' ' + 'a' * 64
        with patch('modules.command_manager.engine_control',return_value=None), \
             patch.object(brain_entry,'matched_protocol',return_value=False), \
             patch.object(goals,'canonical_scheduler_owned',return_value=True) as owns, \
             patch.object(goals,'handle',return_value='Onay kaydedildi; Scheduler yürütür') as handler:
            result = engine_commands.handle(rt, command)
        self.assertIn('Scheduler', result)
        owns.assert_called_once_with(rt.profile.slug, '1' * 16)
        handler.assert_called_once_with(rt, command)

    def test_reserved_controls_keep_their_existing_meaning(self):
        rt = _runtime(self, self.profile, datetime(2026, 10, 20, 12))
        with patch.object(goals, 'latest', return_value=None), patch.object(goals, 'run') as run:
            goals.handle(rt, 'hedef devam')
            run.assert_called_once_with(rt, 'hedef devam', resume=True)
            run.reset_mock()
            goals.handle(rt, 'hedef onayla')
            run.assert_called_once_with(rt, 'hedef onayla', resume=True, approve=True)
