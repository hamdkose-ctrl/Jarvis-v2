"""Aşama A: interaktif masaüstü görevinin canonical admission sözleşmeleri.

Fiziksel UIA eylemi çalıştırılmaz; desktop_agent sahte nesneyle taklit edilir.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from modules import (
    capability_manifest, effect_recovery_runtime, goal_plan_gate, goal_tools,
    scheduler_resource_gate, task_tools,
)
from modules import canonical_scheduler_lane


class DesktopManifestTests(unittest.TestCase):
    def test_manifest_row_is_physical_ask_required(self):
        row = capability_manifest.from_task_tool('desktop')
        self.assertEqual(row['id'], 'task.desktop')
        self.assertEqual(row['permission_class'], 'physical')
        self.assertEqual(row['effect_policy'], 'physical_effect')
        self.assertEqual(row['decision_authority'], 'ask_required')
        self.assertEqual(row['replay'], 'conditional')
        self.assertEqual(row['reconciliation'], 'required')

    def test_effect_recovery_required(self):
        self.assertTrue(effect_recovery_runtime.required('desktop'))

    def test_catalog_contains_desktop_and_validates(self):
        rows = capability_manifest.catalog()['capabilities']
        self.assertIn('task.desktop', {row['id'] for row in rows})

    def test_lane_admits_desktop_as_alone_started_effect(self):
        self.assertIn('task.desktop', canonical_scheduler_lane._SUPPORTED)
        self.assertIn('task.desktop', canonical_scheduler_lane._EFFECTS)

    def test_scheduled_effects_and_root_only_plan_admission(self):
        self.assertIn('task.desktop', goal_plan_gate._SCHEDULED_EFFECTS)
        node = {'id': 'n1', 'capability_id': 'task.desktop',
                'input': {'target': 'calc', 'goal': '12 ile 7 topla'},
                'depends_on': []}
        plan = {'nodes': [node]}
        self.assertTrue(goal_plan_gate._effect_node_allowed(plan, node))
        dep = {'id': 'n0', 'capability_id': 'task.research',
               'input': {'query': 'x'}, 'depends_on': []}
        child = dict(node, depends_on=['n0'])
        plan2 = {'nodes': [dep, child]}
        self.assertFalse(goal_plan_gate._effect_node_allowed(plan2, child))

    def test_effect_keys_serialize_physical_desktop(self):
        node = {'capability_id': 'task.desktop',
                'input': {'target': 'calc', 'goal': '12 ile 7 topla'}}
        keys = scheduler_resource_gate._effect_keys(node, 'hamdi')
        self.assertEqual(len(keys), 1)
        self.assertIn('pc_desktop', keys[0])

    def test_unknown_effect_key_still_rejected(self):
        node = {'capability_id': 'task.observe', 'input': {}}
        with self.assertRaises(scheduler_resource_gate.ReadOnlyAdmissionError):
            scheduler_resource_gate._effect_keys(node, 'hamdi')


class DesktopInputValidationTests(unittest.TestCase):
    def test_valid_input_roundtrip(self):
        data = {'target': 'calc', 'goal': '12 ile 7 topla'}
        self.assertEqual(task_tools.validate_input('desktop', data), data)

    def test_answer_optional_bounded(self):
        data = {'target': 'notepad', 'goal': 'yaz', 'answer': 'evet'}
        self.assertEqual(task_tools.validate_input('desktop', data), data)
        with self.assertRaises(ValueError):
            task_tools.validate_input('desktop', {'target': 'a', 'goal': 'b', 'answer': 5})

    def test_missing_or_oversized_rejected(self):
        with self.assertRaises(ValueError):
            task_tools.validate_input('desktop', {'target': 'calc'})
        with self.assertRaises(ValueError):
            task_tools.validate_input('desktop', {'target': '  ', 'goal': 'x'})
        with self.assertRaises(ValueError):
            task_tools.validate_input('desktop', {'target': 'c' * 201, 'goal': 'x'})
        with self.assertRaises(ValueError):
            task_tools.validate_input('desktop', {'target': 'c', 'goal': 'g' * 2001})
        with self.assertRaises(ValueError):
            task_tools.validate_input('desktop', {'target': 'c', 'goal': 'g', 'resume_id': 'x'})

    def test_desktop_is_not_replay_safe(self):
        self.assertFalse(task_tools.CATALOG['desktop']['replay_safe'])


def _runtime(owner='hamdi'):
    return SimpleNamespace(
        profile=SimpleNamespace(slug=owner, data={}),
        emit=lambda *args, **kwargs: None,
        pc_profile=lambda: SimpleNamespace(slug=owner),
        _cur_source='scheduler',
    )


def _native(owner='hamdi', job_id='dj1', status='running', **extra):
    job = {'owner': owner, 'id': job_id, 'target': 'calc',
           'goal': '12 ile 7 topla', 'status': status, 'history': []}
    job.update(extra)
    return job


class CanonicalDesktopResumeTests(unittest.TestCase):
    def _execute(self, previous, identity, data=None):
        data = data or {'target': 'calc', 'goal': '12 ile 7 topla'}
        fake = mock.Mock()
        fake._load.return_value = previous
        fake.render.return_value = 'ekran'
        fake.run.return_value = 'çalıştı'
        fake.handle.return_value = 'izin verildi'
        with mock.patch('modules.desktop_agent', fake):
            result = goal_tools.execute(_runtime(), 'desktop', data, {}, identity)
        return result, fake

    def test_resume_binding_mismatch_is_rejected(self):
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'other'}
        with self.assertRaises(ValueError):
            self._execute(_native(), identity)

    def test_missing_native_job_is_rejected(self):
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'dj1'}
        with self.assertRaises(ValueError):
            self._execute(None, identity)

    def test_canonical_and_legacy_resume_conflict(self):
        identity = {'owner': 'hamdi', 'desktop_ids': ['dj1'],
                    '_canonical_desktop_resume': 'dj1'}
        with self.assertRaises(ValueError):
            self._execute(_native(), identity, {'target': 'calc', 'goal': '12 ile 7 topla', 'resume_id': 'dj1'})

    def test_engine_approval_round_consumes_native_approval(self):
        native = _native(status='approval', approval={'id': 'ap1'})
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'dj1'}
        result, fake = self._execute(native, identity)
        fake.run.assert_called_once()
        self.assertEqual(fake.run.call_args.kwargs.get('approval'), 'ap1')
        self.assertEqual(result['state'], 'approval')
        self.assertEqual(result['desktop_id'], 'dj1')

    def test_consent_round_uses_explicit_permission_command(self):
        native = _native(status='consent')
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'dj1'}
        result, fake = self._execute(native, identity)
        args = fake.handle.call_args.args
        self.assertEqual(args[1], 'PC izin ver')
        self.assertEqual(result['state'], 'approval')

    def test_pending_effect_round_resumes_without_new_approval(self):
        native = _native(status='waiting', pending_effect={'action': 'invoke'})
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'dj1'}
        result, fake = self._execute(native, identity)
        fake.run.assert_called_once()
        self.assertIsNone(fake.run.call_args.kwargs.get('approval'))
        self.assertEqual(result['state'], 'approval')

    def test_question_state_is_blocked_not_guessed(self):
        native = _native(status='question', question='Hangi dosya?')
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'dj1'}
        result, fake = self._execute(native, identity)
        self.assertEqual(result['state'], 'blocked')
        self.assertFalse(result['retry_safe'])
        fake.run.assert_not_called()
        fake.handle.assert_not_called()

    def test_done_round_requires_verified_history_and_receipt(self):
        native = _native(status='done', history=[{'verified': True}, {'verified': True}])
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'dj1'}
        result, fake = self._execute(native, identity)
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['receipt'], {'service': 'desktop_uia', 'remote_id': 'dj1'})
        proof = result['desktop_evidence']
        digest = hashlib.sha256(json.dumps(proof, ensure_ascii=False, sort_keys=True,
                                           allow_nan=False).encode()).hexdigest()
        self.assertEqual(result['desktop_evidence_sha256'], digest)
        self.assertTrue(goal_tools.verify(result, 'hamdi'))

    def test_done_without_verified_history_is_rejected(self):
        native = _native(status='done', history=[{'verified': False}])
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'dj1'}
        with self.assertRaises(ValueError):
            self._execute(native, identity)

    def test_switched_native_job_during_round_is_rejected(self):
        previous = _native(status='approval', approval={'id': 'ap1'})
        switched = _native(job_id='dj2', status='done', history=[{'verified': True}])
        identity = {'owner': 'hamdi', '_canonical_desktop_resume': 'dj1'}
        fake = mock.Mock()
        fake._load.side_effect = [previous, switched]
        fake.render.return_value = 'ekran'
        fake.run.return_value = 'çalıştı'
        with mock.patch('modules.desktop_agent', fake):
            with self.assertRaises(ValueError):
                goal_tools.execute(_runtime(), 'desktop',
                                   {'target': 'calc', 'goal': '12 ile 7 topla'}, {}, identity)

    def test_fresh_canonical_start_uses_engine_protocol(self):
        started = _native(job_id='dj9', status='waiting', pending_effect={'action': 'invoke'})
        identity = {'owner': 'hamdi'}
        fake = mock.Mock()
        fake._load.side_effect = [None, started]
        fake.handle.return_value = 'başladı'
        fake.render.return_value = 'ekran'
        with mock.patch('modules.desktop_agent', fake):
            result = goal_tools.execute(_runtime(), 'desktop',
                                        {'target': 'calc', 'goal': '12 ile 7 topla'}, {}, identity)
        self.assertEqual(fake.handle.call_args.args[1], 'PC görevi: calc | 12 ile 7 topla')
        self.assertEqual(result['state'], 'approval')
        self.assertEqual(result['desktop_id'], 'dj9')


class DispatchWiringTests(unittest.TestCase):
    def test_dispatch_wires_desktop_waiting_round(self):
        import inspect
        from modules import canonical_scheduler_dispatch
        source = inspect.getsource(canonical_scheduler_dispatch.execute_offer)
        for needle in ("'desktop'", '_canonical_desktop_id',
                       '_canonical_desktop_resume', "result.get('state') == 'approval'"):
            self.assertIn(needle, source)


if __name__ == '__main__':
    unittest.main()
