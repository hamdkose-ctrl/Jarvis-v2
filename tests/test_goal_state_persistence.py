import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class GoalStatePersistenceTests(unittest.TestCase):
    def setUp(self):
        from modules import goal_executor, goal_state_compat, goal_state_store
        self.goal_executor = goal_executor
        self.compat = goal_state_compat
        self.store = goal_state_store
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def job(self, state='running'):
        return {
            'id': '0123456789abcdef',
            'owner': 'alice',
            'request': 'Raporu hazırla',
            'created': 1,
            'state': state,
            'goals': [],
            'steps': [],
            'outputs': {},
        }

    def test_load_rejects_truncated_json_with_stable_corruption_error(self):
        path = self.root / 'state.json'
        path.write_bytes(b'{"schema":"goal_state.v1",')
        with self.assertRaises(self.store.PersistedStateCorruption) as caught:
            self.store.load(path)
        self.assertEqual(str(caught.exception), 'Persisted GoalState snapshot is corrupt or invalid.')
        self.assertNotIn('schema', str(caught.exception))

    def test_load_rejects_invalid_utf8_with_stable_corruption_error(self):
        path = self.root / 'state.json'
        path.write_bytes(b'\xff\xfe\xfa')
        with self.assertRaises(self.store.PersistedStateCorruption) as caught:
            self.store.load(path)
        self.assertEqual(str(caught.exception), 'Persisted GoalState snapshot is corrupt or invalid.')

    def test_load_rejects_schema_invalid_json_with_stable_corruption_error(self):
        path = self.root / 'state.json'
        path.write_text(json.dumps({'schema': 'goal_state.v1', 'secret': 'do-not-leak'}), encoding='utf-8')
        with self.assertRaises(self.store.PersistedStateCorruption) as caught:
            self.store.load(path)
        self.assertEqual(str(caught.exception), 'Persisted GoalState snapshot is corrupt or invalid.')
        self.assertNotIn('do-not-leak', str(caught.exception))

    def test_compare_and_swap_rejects_corrupt_disk_without_changing_bytes(self):
        path = self.root / 'state.json'
        broken = b'{"owner":"alice","private":"do-not-leak"'
        path.write_bytes(broken)
        current = self.compat.project(self.job())
        next_state = self.compat.advance(current, self.job('paused'))
        with self.assertRaises(self.store.PersistedStateCorruption):
            self.store.compare_and_swap(path, expected_version=current['version'], next_state=next_state)
        self.assertEqual(path.read_bytes(), broken)

    def test_compensate_rejects_corrupt_disk_without_changing_bytes(self):
        path = self.root / 'state.json'
        broken = b'{bad-json'
        path.write_bytes(broken)
        expected = self.compat.project(self.job())
        with self.assertRaises(self.store.PersistedStateCorruption):
            self.store.compensate(path, expected_state=expected, previous_bytes=None)
        self.assertEqual(path.read_bytes(), broken)

    def test_compensate_rejects_corrupt_previous_bytes_without_changing_current(self):
        path = self.root / 'state.json'
        current = self.compat.project(self.job())
        self.store.create(path, current)
        before = path.read_bytes()
        with self.assertRaises(self.store.PersistedStateCorruption):
            self.store.compensate(path, expected_state=current, previous_bytes=b'\xffbroken')
        self.assertEqual(path.read_bytes(), before)

    def test_compare_and_swap_rejects_stale_persisted_version(self):
        path = self.root / 'state.json'
        current = self.compat.project(self.job())
        self.store.create(path, current)
        next_state = self.compat.advance(current, self.job('paused'))
        self.store.compare_and_swap(
            path, expected_version=current['version'], next_state=next_state,
        )
        with self.assertRaises(self.store.PersistedStateConflict):
            self.store.compare_and_swap(
                path, expected_version=current['version'], next_state=next_state,
            )

    def test_legacy_projection_is_idempotent_for_same_state(self):
        path = self.root / 'state.json'
        first = self.compat.sync(self.job(), path)
        second = self.compat.sync(self.job(), path)
        self.assertEqual(first['state'], 'running')
        self.assertEqual(second['version'], first['version'])
        self.assertEqual(second, first)

    def test_legacy_waiting_state_and_blocker_are_reduced_and_persisted(self):
        path = self.root / 'state.json'
        self.compat.sync(self.job(), path)
        job = self.job('approval')
        job['blocker'] = 'Kullanıcı onayı gerekli.'
        state = self.compat.sync(job, path)
        self.assertEqual(state['state'], 'waiting')
        self.assertEqual(state['blocker']['code'], 'LEGACY_APPROVAL')
        on_disk = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(on_disk, state)

    def test_legacy_state_sequence_preserves_state_blocker_and_audit_parity(self):
        path = self.root / 'state.json'
        sequence = []

        running = self.job('running')
        sequence.append(self.compat.sync(running, path))

        approval = self.job('approval')
        approval['blocker'] = 'Kullanıcı onayı gerekli.'
        sequence.append(self.compat.sync(approval, path))

        question = self.job('question')
        question['question'] = 'Hangi belge kullanılmalı?'
        sequence.append(self.compat.sync(question, path))

        review = self.job('review')
        review['blocker'] = 'Sonuç gözden geçirilmeli.'
        sequence.append(self.compat.sync(review, path))

        sequence.append(self.compat.sync(self.job('paused'), path))
        sequence.append(self.compat.sync(self.job('failed'), path))
        sequence.append(self.compat.sync(self.job('done'), path))

        self.assertEqual(
            [state['state'] for state in sequence],
            ['running', 'waiting', 'waiting', 'paused', 'paused', 'failed', 'done'],
        )
        self.assertIsNone(sequence[0]['blocker'])
        self.assertEqual(sequence[1]['blocker'], {
            'code': 'LEGACY_APPROVAL', 'text': 'Kullanıcı onayı gerekli.',
        })
        self.assertEqual(sequence[2]['blocker'], {
            'code': 'LEGACY_QUESTION', 'text': 'Hangi belge kullanılmalı?',
        })
        self.assertEqual(sequence[3]['blocker'], {
            'code': 'LEGACY_BLOCKED', 'text': 'Sonuç gözden geçirilmeli.',
        })
        self.assertIsNone(sequence[4]['blocker'])
        self.assertIsNone(sequence[5]['blocker'])
        self.assertIsNone(sequence[6]['blocker'])

        final = sequence[-1]
        self.assertEqual(
            [row['reason_code'] for row in final['audit']],
            [
                'CREATED', 'LEGACY_PROJECTED',
                'LEGACY_STATE_SYNCED', 'LEGACY_BLOCKER_SYNCED',
                'LEGACY_BLOCKER_SYNCED',
                'LEGACY_STATE_SYNCED', 'LEGACY_BLOCKER_SYNCED',
                'LEGACY_BLOCKER_CLEARED',
                'LEGACY_STATE_SYNCED',
                'LEGACY_RESUMED', 'LEGACY_STATE_SYNCED',
            ],
        )
        self.assertEqual([row['version'] for row in final['audit']], list(range(final['version'] + 1)))
        self.assertEqual(final['audit'][-1]['state'], 'done')

    def test_waiting_blocker_changes_and_clears_only_before_terminal(self):
        path = self.root / 'state.json'
        approval = self.job('approval')
        approval['blocker'] = 'İlk onay.'
        first = self.compat.sync(approval, path)

        changed = self.job('approval')
        changed['blocker'] = 'İkinci onay.'
        second = self.compat.sync(changed, path)
        self.assertEqual(second['state'], 'waiting')
        self.assertEqual(second['blocker'], {'code': 'LEGACY_APPROVAL', 'text': 'İkinci onay.'})
        self.assertEqual(second['version'], first['version'] + 1)

        question = self.job('question')
        question['question'] = 'Devam edilsin mi?'
        third = self.compat.sync(question, path)
        self.assertEqual(third['blocker'], {'code': 'LEGACY_QUESTION', 'text': 'Devam edilsin mi?'})

        paused = self.compat.sync(self.job('paused'), path)
        self.assertIsNone(paused['blocker'])

        terminal = self.compat.sync(self.job('done'), path)
        terminal_bytes = path.read_bytes()
        later = self.job('approval')
        later['blocker'] = 'Terminalden sonra değişmemeli.'
        unchanged = self.compat.sync(later, path)
        self.assertEqual(unchanged, terminal)
        self.assertEqual(path.read_bytes(), terminal_bytes)

    def test_terminal_done_and_cancelled_are_immutable_under_later_legacy_states(self):
        for terminal_state in ('done', 'cancelled'):
            with self.subTest(terminal_state=terminal_state):
                path = self.root / (terminal_state + '.json')
                terminal = self.compat.sync(self.job(terminal_state), path)
                before = path.read_bytes()
                for later_state in ('running', 'paused', 'approval'):
                    later = self.job(later_state)
                    if later_state == 'approval':
                        later['blocker'] = 'Yeni onay bekleniyor.'
                    current = self.compat.sync(later, path)
                    self.assertEqual(current, terminal)
                    self.assertEqual(current['version'], terminal['version'])
                    self.assertEqual(current['audit'], terminal['audit'])
                    self.assertEqual(current['state'], terminal_state)
                    self.assertEqual(current['blocker'], terminal['blocker'])
                    self.assertEqual(path.read_bytes(), before)

    def test_same_waiting_legacy_snapshot_is_fully_idempotent(self):
        path = self.root / 'state.json'
        job = self.job('approval')
        job['blocker'] = 'Onay gerekiyor.'
        first = self.compat.sync(job, path)
        before = path.read_bytes()
        second = self.compat.sync(dict(job), path)
        self.assertEqual(second, first)
        self.assertEqual(second['version'], first['version'])
        self.assertEqual(second['audit'], first['audit'])
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_legacy_state_never_creates_or_changes_canonical(self):
        missing = self.root / 'missing.json'
        unknown = self.job('mystery-state')
        with self.assertRaisesRegex(ValueError, 'Legacy job state'):
            self.compat.sync(unknown, missing)
        self.assertFalse(missing.exists())

        path = self.root / 'existing.json'
        current = self.compat.sync(self.job('running'), path)
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Legacy job state'):
            self.compat.sync(unknown, path)
        self.assertEqual(self.store.load(path), current)
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_hook_rejects_job_id_path_and_owner_mismatch_for_projection(self):
        from modules import goal_state_save_hook
        owner_dir = self.root / 'alice'
        owner_dir.mkdir()

        wrong_owner = self.job('running')
        wrong_owner['owner'] = 'bob'
        owner_path = owner_dir / (wrong_owner['id'] + '.json')
        goal_state_save_hook._atomic(
            owner_path, json.dumps(wrong_owner, ensure_ascii=False).encode('utf-8'),
        )
        self.assertFalse(owner_path.with_name(wrong_owner['id'] + '.goalstate.json').exists())

        wrong_id = self.job('running')
        path_id = 'fedcba9876543210'
        id_path = owner_dir / (path_id + '.json')
        goal_state_save_hook._atomic(
            id_path, json.dumps(wrong_id, ensure_ascii=False).encode('utf-8'),
        )
        self.assertFalse(id_path.with_name(path_id + '.goalstate.json').exists())
        self.assertFalse(id_path.with_name(wrong_id['id'] + '.goalstate.json').exists())

    def test_terminal_canonical_state_is_not_reopened_by_legacy_projection(self):
        path = self.root / 'state.json'
        terminal = self.compat.sync(self.job('done'), path)
        reopened = self.compat.sync(self.job('paused'), path)
        self.assertEqual(terminal['state'], 'done')
        self.assertEqual(reopened, terminal)

    def test_goal_executor_save_writes_canonical_before_legacy_record(self):
        with patch.object(self.goal_executor, 'STORE', self.root):
            job = self.job()
            self.goal_executor._save(job)
            root = self.root / 'alice'
            canonical = root / '0123456789abcdef.goalstate.json'
            legacy = root / '0123456789abcdef.json'
            self.assertTrue(canonical.exists())
            self.assertTrue(legacy.exists())
            state = json.loads(canonical.read_text(encoding='utf-8'))
            self.assertEqual(state['state'], 'running')
            self.assertEqual(state['job_id'], job['id'])

    def test_goal_executor_save_is_fail_closed_when_canonical_sync_fails(self):
        with patch.object(self.goal_executor, 'STORE', self.root):
            job = self.job()
            with patch('modules.goal_state_compat.sync', side_effect=RuntimeError('cas failed')):
                with self.assertRaisesRegex(RuntimeError, 'cas failed'):
                    self.goal_executor._save(job)
            root = self.root / 'alice'
            self.assertFalse((root / '0123456789abcdef.json').exists())
            self.assertFalse((root / 'latest.json').exists())

    def test_sync_failure_is_recorded_and_never_reaches_legacy_write_or_compensation(self):
        from modules import goal_state_save_hook

        owner_dir = self.root / 'alice'
        owner_dir.mkdir()
        legacy = owner_dir / '0123456789abcdef.json'
        canonical = owner_dir / '0123456789abcdef.goalstate.json'
        current = self.compat.sync(self.job('running'), canonical)
        before = canonical.read_bytes()
        unknown = self.job('mystery-state')
        payload = json.dumps(unknown, ensure_ascii=False).encode('utf-8')

        with patch.object(goal_state_save_hook, '_record_failure') as record_failure, \
             patch.object(goal_state_save_hook, '_ORIGINAL_ATOMIC') as legacy_write, \
             patch('modules.goal_state_store.compensate') as compensate:
            with self.assertRaisesRegex(ValueError, 'Legacy job state'):
                goal_state_save_hook._atomic(legacy, payload)

        record_failure.assert_called_once_with(
            'modules/goal_state_save_hook.py:_atomic:canonical_sync'
        )
        legacy_write.assert_not_called()
        compensate.assert_not_called()
        self.assertFalse(legacy.exists())
        self.assertEqual(self.store.load(canonical), current)
        self.assertEqual(canonical.read_bytes(), before)

    def test_foreign_legacy_owner_never_projects_canonical_goalstate(self):
        """A legacy-shaped JSON file cannot advance another owner's GoalState."""
        with patch.object(self.goal_executor, 'STORE', self.root):
            root = self.root / 'alice'
            root.mkdir()
            foreign = self.job()
            foreign['owner'] = 'bob'
            import release_guard
            release_guard.atomic(
                root / (foreign['id'] + '.json'),
                json.dumps(foreign, ensure_ascii=False).encode('utf-8'),
            )
            self.assertFalse((root / (foreign['id'] + '.goalstate.json')).exists())

    def test_goal_executor_save_rolls_back_new_canonical_when_legacy_write_fails(self):
        from modules import goal_state_save_hook
        original = goal_state_save_hook._ORIGINAL_ATOMIC

        def fail_legacy(path, data):
            if Path(path).name == '0123456789abcdef.json':
                raise OSError('legacy write failed')
            return original(path, data)

        with patch.object(self.goal_executor, 'STORE', self.root):
            with patch.object(goal_state_save_hook, '_ORIGINAL_ATOMIC', side_effect=fail_legacy):
                with self.assertRaisesRegex(OSError, 'legacy write failed'):
                    self.goal_executor._save(self.job())
            root = self.root / 'alice'
            self.assertFalse((root / '0123456789abcdef.goalstate.json').exists())
            self.assertFalse((root / '0123456789abcdef.json').exists())
            self.assertFalse((root / 'latest.json').exists())

    def test_goal_executor_save_restores_previous_canonical_when_legacy_update_fails(self):
        from modules import goal_state_save_hook
        original = goal_state_save_hook._ORIGINAL_ATOMIC

        with patch.object(self.goal_executor, 'STORE', self.root):
            self.goal_executor._save(self.job())
            root = self.root / 'alice'
            canonical = root / '0123456789abcdef.goalstate.json'
            before = canonical.read_bytes()

            def fail_legacy(path, data):
                if Path(path).name == '0123456789abcdef.json':
                    raise OSError('legacy write failed')
                return original(path, data)

            with patch.object(goal_state_save_hook, '_ORIGINAL_ATOMIC', side_effect=fail_legacy):
                with self.assertRaisesRegex(OSError, 'legacy write failed'):
                    self.goal_executor._save(self.job('paused'))
            self.assertEqual(canonical.read_bytes(), before)
            self.assertEqual(json.loads(canonical.read_text(encoding='utf-8'))['state'], 'running')

    def test_legacy_write_failure_leaves_no_new_or_reopened_canonical_state(self):
        from modules import goal_state_save_hook
        original = goal_state_save_hook._ORIGINAL_ATOMIC

        def fail_legacy(path, data):
            if Path(path).name == '0123456789abcdef.json':
                raise OSError('legacy write failed')
            return original(path, data)

        with patch.object(self.goal_executor, 'STORE', self.root):
            with patch.object(goal_state_save_hook, '_ORIGINAL_ATOMIC', side_effect=fail_legacy):
                with self.assertRaisesRegex(OSError, 'legacy write failed'):
                    self.goal_executor._save(self.job('approval'))
            root = self.root / 'alice'
            self.assertFalse((root / '0123456789abcdef.goalstate.json').exists())

            self.goal_executor._save(self.job('done'))
            canonical = root / '0123456789abcdef.goalstate.json'
            terminal_bytes = canonical.read_bytes()
            with patch.object(goal_state_save_hook, '_ORIGINAL_ATOMIC', side_effect=fail_legacy):
                with self.assertRaisesRegex(OSError, 'legacy write failed'):
                    self.goal_executor._save(self.job('running'))
            self.assertEqual(canonical.read_bytes(), terminal_bytes)
            self.assertEqual(self.store.load(canonical)['state'], 'done')

    # -- RFC Karar 1: projection execution_mode is permanently 'agent' -----

    def test_projection_execution_mode_is_named_decision_constant(self):
        self.assertEqual(self.compat.PROJECTION_EXECUTION_MODE, 'agent')
        state = self.compat.project(self.job())
        self.assertEqual(state['execution_mode'], self.compat.PROJECTION_EXECUTION_MODE)

    def test_projection_execution_mode_is_agent_when_legacy_field_absent(self):
        job = self.job()
        self.assertNotIn('execution_mode', job)
        state = self.compat.project(job)
        self.assertEqual(state['execution_mode'], 'agent')

    def test_projection_execution_mode_is_agent_for_other_legacy_values(self):
        for legacy_mode in ('fast', 'durable', 'pending', '', 'AGENT'):
            with self.subTest(legacy_mode=legacy_mode):
                job = self.job()
                job['execution_mode'] = legacy_mode
                self.assertEqual(self.compat.project(job)['execution_mode'], 'agent')

    def test_projection_execution_mode_is_agent_for_wrong_typed_field(self):
        for legacy_mode in (None, 7, ['durable'], {'mode': 'fast'}):
            with self.subTest(legacy_mode=legacy_mode):
                job = self.job()
                job['execution_mode'] = legacy_mode
                self.assertEqual(self.compat.project(job)['execution_mode'], 'agent')

    def test_persisted_and_advanced_state_keeps_agent_execution_mode(self):
        path = self.root / 'state.json'
        job = self.job()
        job['execution_mode'] = 'durable'
        first = self.compat.sync(job, path)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['execution_mode'], 'agent')
        for later_state in ('approval', 'paused', 'done'):
            advanced = self.compat.sync(self.job(later_state), path)
            self.assertEqual(advanced['execution_mode'], 'agent')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['execution_mode'], 'agent')

    def test_goalstate_schema_execution_modes_gained_no_new_value(self):
        from modules import goal_state
        self.assertEqual(goal_state.EXECUTION_MODES, frozenset({'fast', 'agent', 'durable'}))


class GoalStateRFCDecision34Tests(unittest.TestCase):
    def setUp(self):
        from modules import goal_state_compat, goal_state_store
        self.compat = goal_state_compat
        self.store = goal_state_store
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def job(self, state='running'):
        return {
            'id': '0123456789abcdef',
            'owner': 'alice',
            'request': 'Raporu hazırla',
            'created': 1,
            'state': state,
            'goals': [],
            'steps': [],
            'outputs': {},
        }

    def test_terminal_canonical_wins_with_explicit_reconcile_decision(self):
        for terminal_state in ('done', 'cancelled'):
            with self.subTest(terminal_state=terminal_state):
                current = self.compat.project(self.job(terminal_state))
                result = self.compat.reconcile(current, self.job('running'))
                self.assertEqual(result['decision'], 'CANONICAL_TERMINAL_WINS')
                self.assertEqual(result['reason_code'], 'TERMINAL_DIVERGENCE')
                self.assertFalse(result['changed'])
                self.assertEqual(result['state'], current)

    def test_different_terminal_states_still_choose_canonical_explicitly(self):
        current = self.compat.project(self.job('done'))
        result = self.compat.reconcile(current, self.job('cancelled'))
        self.assertEqual(result['decision'], 'CANONICAL_TERMINAL_WINS')
        self.assertEqual(result['reason_code'], 'TERMINAL_DIVERGENCE')
        self.assertFalse(result['changed'])
        self.assertEqual(result['state'], current)

    def test_operator_backfill_once_requires_explicit_approval_and_creates_expected_snapshot(self):
        path = self.root / 'state.goalstate.json'
        with self.assertRaises(self.compat.OperatorApprovalRequired):
            self.compat.operator_backfill_missing_canonical_once(self.job('paused'), path)
        self.assertFalse(path.exists())

        state = self.compat.operator_backfill_missing_canonical_once(
            self.job('paused'), path, operator_approved=True,
        )
        self.assertEqual(state, self.store.load(path))
        self.assertEqual(state['owner'], 'alice')
        self.assertEqual(state['job_id'], '0123456789abcdef')
        self.assertEqual(state['goal'], 'Raporu hazırla')
        self.assertEqual(state['state'], 'paused')

        with self.assertRaises(self.compat.BackfillAlreadyExists):
            self.compat.operator_backfill_missing_canonical_once(
                self.job('paused'), path, operator_approved=True,
            )

    def test_normal_sync_never_calls_operator_backfill_api(self):
        path = self.root / 'compat.goalstate.json'
        with patch.object(self.compat, 'operator_backfill_missing_canonical_once') as backfill:
            state = self.compat.sync(self.job('running'), path)
        backfill.assert_not_called()
        self.assertEqual(state['state'], 'running')

    def test_identity_mismatch_fails_closed_without_mutation(self):
        cases = [
            ('owner', 'bob'),
            ('id', 'fedcba9876543210'),
            ('request', 'Başka hedef'),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                path = self.root / (field + '.goalstate.json')
                current = self.compat.sync(self.job('running'), path)
                before = path.read_bytes()
                legacy = self.job('paused')
                legacy[field] = value
                with self.assertRaises(self.compat.IdentityMismatchError) as caught:
                    self.compat.sync(legacy, path)
                self.assertEqual(caught.exception.reason_code, 'IDENTITY_MISMATCH')
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(self.store.load(path), current)

    def test_compatible_nonterminal_reconcile_still_advances_normally(self):
        current = self.compat.project(self.job('running'))
        result = self.compat.reconcile(current, self.job('paused'))
        self.assertEqual(result['decision'], 'LEGACY_COMPAT_APPLIED')
        self.assertEqual(result['reason_code'], 'LEGACY_STATE_SYNCED')
        self.assertTrue(result['changed'])
        self.assertEqual(result['state']['state'], 'paused')


if __name__ == '__main__':
    unittest.main()
