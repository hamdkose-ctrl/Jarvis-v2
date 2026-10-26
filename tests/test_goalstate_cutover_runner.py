import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


class GoalStateCutoverRunnerTests(unittest.TestCase):
    JOB_A = '0123456789abcdef'
    JOB_B = 'fedcba9876543210'

    def setUp(self):
        from modules import goal_state, goal_state_compat, goal_state_store
        from modules import goalstate_cutover_preflight as preflight
        from modules import goalstate_cutover_runner as runner
        self.goal_state = goal_state
        self.compat = goal_state_compat
        self.store = goal_state_store
        self.preflight = preflight
        self.runner = runner
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.owner_dir = Path(self.tmp.name) / 'alice'
        self.owner_dir.mkdir()

    def legacy_job(self, job_id=JOB_A, state='running', request='Raporu hazırla'):
        return {
            'id': job_id, 'owner': 'alice', 'request': request, 'created': 1,
            'state': state, 'goals': [], 'steps': [], 'outputs': {},
        }

    def write_legacy(self, job):
        path = self.owner_dir / (job['id'] + '.json')
        path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        return path

    def canonical_path(self, job_id):
        return self.owner_dir / (job_id + '.goalstate.json')

    def write_canonical(self, job, *, target_state=None, goal=None):
        from modules import core_state_reducer
        state = self.compat.project(dict(job, request=goal or job['request']))
        if target_state is not None and target_state != state['state']:
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': target_state, 'reason_code': 'TEST_SETUP',
            })
        self.store.create(self.canonical_path(job['id']), state)
        return state

    def snapshot(self):
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(self.owner_dir.iterdir()) if p.is_file()
        }

    def row(self, report, job_id):
        return next(r for r in report['rows'] if r['job_id'] == job_id)

    # --- Guards (RFC Karar 3) -------------------------------------------------

    def test_every_preflight_reason_code_has_exactly_one_guard(self):
        self.assertEqual(set(self.runner.GUARDS), set(self.preflight.REASON_CODES))
        mutating = [c for c, a in self.runner.GUARDS.items()
                    if a == self.runner.ACTION_OPERATOR_BACKFILL]
        self.assertEqual(mutating, ['MISSING_CANONICAL'])
        for code in ('IDENTITY_MISMATCH', 'CANONICAL_CORRUPT',
                     'UNKNOWN_LEGACY_STATE', 'INVALID_LEGACY_RECORD'):
            self.assertEqual(self.runner.GUARDS[code], self.runner.ACTION_BLOCKED)

    def test_plan_is_read_only(self):
        self.write_legacy(self.legacy_job(self.JOB_A))
        job_b = self.legacy_job(self.JOB_B, state='paused')
        self.write_legacy(job_b)
        self.write_canonical(job_b, target_state='running')
        before = self.snapshot()
        report = self.runner.plan(self.owner_dir)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(report['backfill_candidates'], [self.JOB_A])
        self.assertEqual(report['authority_flip_point'], 'JOB_CREATION')
        self.assertFalse(report['blocked'])
        self.assertFalse(self.canonical_path(self.JOB_A).exists())

    def test_plan_fingerprint_is_deterministic_and_tracks_bytes(self):
        path = self.write_legacy(self.legacy_job())
        first = self.runner.plan(self.owner_dir)['fingerprint']
        self.assertEqual(self.runner.plan(self.owner_dir)['fingerprint'], first)
        path.write_text(json.dumps(self.legacy_job(state='paused')), encoding='utf-8')
        self.assertNotEqual(self.runner.plan(self.owner_dir)['fingerprint'], first)

    # --- Operator approval (RFC Karar 3a) -------------------------------------

    def test_apply_without_approval_never_mutates(self):
        self.write_legacy(self.legacy_job())
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        before = self.snapshot()
        for kwargs in (
            {'approved_fingerprint': '', 'approved_job_ids': [self.JOB_A]},
            {'approved_fingerprint': fingerprint, 'approved_job_ids': []},
            {'approved_fingerprint': None, 'approved_job_ids': None},
            {'approved_fingerprint': fingerprint, 'approved_job_ids': [self.JOB_A, self.JOB_A]},
        ):
            with self.assertRaises(self.runner.OperatorApprovalRequired):
                self.runner.apply(self.owner_dir, **kwargs)
            self.assertEqual(self.snapshot(), before)

    def test_apply_with_stale_fingerprint_is_plan_drift(self):
        self.write_legacy(self.legacy_job())
        before = self.snapshot()
        with self.assertRaises(self.runner.PlanDrift):
            self.runner.apply(self.owner_dir, approved_fingerprint='0' * 64,
                              approved_job_ids=[self.JOB_A])
        self.assertEqual(self.snapshot(), before)

    def test_legacy_change_after_approval_is_plan_drift(self):
        path = self.write_legacy(self.legacy_job())
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        path.write_text(json.dumps(self.legacy_job(state='paused')), encoding='utf-8')
        with self.assertRaises(self.runner.PlanDrift):
            self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                              approved_job_ids=[self.JOB_A])
        self.assertFalse(self.canonical_path(self.JOB_A).exists())

    def test_approved_backfill_creates_legacy_authority_record(self):
        self.write_legacy(self.legacy_job(state='approval'))
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        result = self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                                   approved_job_ids=[self.JOB_A])
        self.assertEqual(result['applied'], [self.JOB_A])
        state = self.store.load(self.canonical_path(self.JOB_A))
        self.assertEqual(state['state'], 'waiting')
        self.assertEqual(state['execution_mode'], 'agent')  # RFC Karar 1
        self.assertEqual(self.goal_state.authority(state), 'legacy')  # RFC Karar 2
        self.assertEqual(self.row(result['after'], self.JOB_A)['reason_code'], 'OK')
        self.assertEqual(result['after']['backfill_candidates'], [])

    def test_backfilled_record_stays_legacy_authority_on_later_sync(self):
        self.write_legacy(self.legacy_job())
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                          approved_job_ids=[self.JOB_A])
        synced = self.compat.sync(self.legacy_job(state='paused'), self.canonical_path(self.JOB_A))
        self.assertEqual(synced['state'], 'paused')
        self.assertEqual(self.goal_state.authority(synced), 'legacy')

    def test_new_job_projection_is_still_canonical_authority(self):
        # Karar 2 flip point is unchanged: only the operator backfill is legacy.
        self.assertEqual(self.goal_state.authority(self.compat.project(self.legacy_job())), 'canonical')

    def test_rerun_after_apply_is_idempotent(self):
        self.write_legacy(self.legacy_job())
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                          approved_job_ids=[self.JOB_A])
        before = self.snapshot()
        with self.assertRaises(self.runner.PlanDrift):
            self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                              approved_job_ids=[self.JOB_A])
        fresh = self.runner.plan(self.owner_dir)['fingerprint']
        with self.assertRaises(self.runner.OperatorApprovalRequired):
            self.runner.apply(self.owner_dir, approved_fingerprint=fresh,
                              approved_job_ids=[self.JOB_A])
        self.assertEqual(self.snapshot(), before)

    def test_partial_approval_backfills_only_approved_jobs(self):
        self.write_legacy(self.legacy_job(self.JOB_A))
        self.write_legacy(self.legacy_job(self.JOB_B))
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        result = self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                                   approved_job_ids=[self.JOB_B])
        self.assertEqual(result['applied'], [self.JOB_B])
        self.assertFalse(self.canonical_path(self.JOB_A).exists())
        self.assertEqual(result['after']['backfill_candidates'], [self.JOB_A])

    def test_crash_mid_run_leaves_completed_backfills_and_no_blind_retry(self):
        self.write_legacy(self.legacy_job(self.JOB_A))
        self.write_legacy(self.legacy_job(self.JOB_B))
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        original = self.compat.operator_backfill_missing_canonical_once
        calls = []

        def crash_on_second(job, path, **kwargs):
            calls.append(job['id'])
            if len(calls) == 2:
                raise OSError('simulated crash')
            return original(job, path, **kwargs)

        with patch.object(self.compat, 'operator_backfill_missing_canonical_once',
                          side_effect=crash_on_second):
            with self.assertRaises(OSError):
                self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                                  approved_job_ids=[self.JOB_A, self.JOB_B])
        self.assertEqual(calls, [self.JOB_A, self.JOB_B])
        self.assertTrue(self.canonical_path(self.JOB_A).exists())
        self.assertFalse(self.canonical_path(self.JOB_B).exists())
        after = self.runner.plan(self.owner_dir)
        self.assertEqual(self.row(after, self.JOB_A)['reason_code'], 'OK')
        self.assertEqual(after['backfill_candidates'], [self.JOB_B])
        self.assertNotEqual(after['fingerprint'], fingerprint)

    def test_verification_failure_stops_without_delete(self):
        self.write_legacy(self.legacy_job(self.JOB_A))
        self.write_legacy(self.legacy_job(self.JOB_B))
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        original = self.preflight._classify
        calls = []

        def diverge_after_plan(job, owner_dir, job_id):
            calls.append(job_id)
            row = original(job, owner_dir, job_id)
            # Calls 1-2 are apply()'s fresh plan; call 3 is the post-write check.
            return dict(row, reason_code='STATE_DIVERGENCE') if len(calls) == 3 else row

        with patch.object(self.preflight, '_classify', side_effect=diverge_after_plan):
            with self.assertRaises(self.runner.CutoverVerificationFailed):
                self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                                  approved_job_ids=[self.JOB_A, self.JOB_B])
        self.assertTrue(self.canonical_path(self.JOB_A).exists())
        self.assertFalse(self.canonical_path(self.JOB_B).exists())

    # --- Fail-closed boundary -------------------------------------------------

    def test_any_blocker_stops_whole_owner_byte_for_byte(self):
        cases = {
            'IDENTITY_MISMATCH': lambda job: self.write_canonical(job, goal='Başka hedef'),
            'CANONICAL_CORRUPT': lambda job: self.canonical_path(job['id']).write_bytes(b'{"x":'),
            'UNKNOWN_LEGACY_STATE': lambda job: self.write_legacy(dict(job, state='mystery')),
            'INVALID_LEGACY_RECORD': lambda job: (self.owner_dir / (job['id'] + '.json')).write_bytes(b'not json'),
        }
        for code, make in cases.items():
            with self.subTest(code=code):
                for p in self.owner_dir.iterdir():
                    p.unlink()
                self.write_legacy(self.legacy_job(self.JOB_A))
                bad = self.legacy_job(self.JOB_B)
                self.write_legacy(bad)
                make(bad)
                report = self.runner.plan(self.owner_dir)
                self.assertTrue(report['blocked'])
                self.assertEqual(report['blockers'], [self.JOB_B])
                self.assertEqual(self.row(report, self.JOB_B)['reason_code'], code)
                self.assertEqual(self.row(report, self.JOB_B)['decision'], 'HUMAN_REVIEW_REQUIRED')
                before = self.snapshot()
                with self.assertRaises(self.runner.CutoverBlocked):
                    self.runner.apply(self.owner_dir, approved_fingerprint=report['fingerprint'],
                                      approved_job_ids=[self.JOB_A])
                self.assertEqual(self.snapshot(), before)

    # --- Divergence (RFC Karar 4) ---------------------------------------------

    def test_canonical_terminal_divergence_reports_canonical_wins_without_mutation(self):
        job = self.legacy_job(state='running')
        self.write_legacy(job)
        self.write_canonical(job, target_state='done')
        before = self.snapshot()
        report = self.runner.plan(self.owner_dir)
        row = self.row(report, self.JOB_A)
        self.assertEqual(row['reason_code'], 'TERMINAL_DIVERGENCE')
        self.assertEqual(row['decision'], 'CANONICAL_TERMINAL_WINS')
        self.assertEqual(row['winner'], 'canonical')
        self.assertEqual(row['action'], 'REPORT_ONLY')
        with self.assertRaises(self.runner.OperatorApprovalRequired):
            self.runner.apply(self.owner_dir, approved_fingerprint=report['fingerprint'],
                              approved_job_ids=[self.JOB_A])
        self.assertEqual(self.snapshot(), before)

    def test_state_divergence_names_authority_side_as_winner(self):
        from modules import core_state_reducer
        job = self.legacy_job(state='paused')
        self.write_legacy(job)
        legacy_shaped = self.goal_state.new(owner='alice', job_id=self.JOB_A, goal=job['request'])
        del legacy_shaped['authority']
        legacy_shaped = core_state_reducer.apply(legacy_shaped, {
            'expected_version': 0, 'op': 'set_state', 'state': 'running', 'reason_code': 'TEST_SETUP',
        })
        self.store.create(self.canonical_path(self.JOB_A), legacy_shaped)
        row = self.row(self.runner.plan(self.owner_dir), self.JOB_A)
        self.assertEqual(row['reason_code'], 'STATE_DIVERGENCE')
        self.assertEqual(row['decision'], 'AUTHORITY_SIDE_WINS')
        self.assertEqual(row['authority'], 'legacy')
        self.assertEqual(row['winner'], 'legacy')

        self.canonical_path(self.JOB_A).unlink()
        self.write_canonical(job, target_state='running')
        row = self.row(self.runner.plan(self.owner_dir), self.JOB_A)
        self.assertEqual(row['authority'], 'canonical')
        self.assertEqual(row['winner'], 'canonical')

    def test_legacy_terminal_with_active_canonical_is_authority_side(self):
        job = self.legacy_job(state='done')
        self.write_legacy(job)
        self.write_canonical(dict(job, state='running'))
        row = self.row(self.runner.plan(self.owner_dir), self.JOB_A)
        self.assertEqual(row['reason_code'], 'TERMINAL_DIVERGENCE')
        self.assertEqual(row['decision'], 'AUTHORITY_SIDE_WINS')

    def test_runner_never_changes_existing_canonical_authority(self):
        job = self.legacy_job()
        self.write_legacy(job)
        self.write_canonical(job)
        self.write_legacy(self.legacy_job(self.JOB_B))
        before = self.canonical_path(self.JOB_A).read_bytes()
        fingerprint = self.runner.plan(self.owner_dir)['fingerprint']
        self.runner.apply(self.owner_dir, approved_fingerprint=fingerprint,
                          approved_job_ids=[self.JOB_B])
        self.assertEqual(self.canonical_path(self.JOB_A).read_bytes(), before)

    # --- Wiring / architecture ------------------------------------------------

    def test_runner_is_not_wired_into_sync_or_save_hook(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('goal_state_compat.py', 'goal_state_save_hook.py', 'goal_executor.py'):
            text = (root / 'modules' / name).read_text(encoding='utf-8')
            self.assertNotIn('goalstate_cutover_runner', text, name)

    def test_architecture_guard_has_no_blocker_for_runner(self):
        from modules import architecture_guard
        report = architecture_guard.scan()
        paths = [b['path'] for b in report['blockers']]
        self.assertNotIn('modules/goalstate_cutover_runner.py', paths)
        self.assertEqual(report['blockers'], [])

    def test_cli_plan_and_refused_apply(self):
        self.write_legacy(self.legacy_job())
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.runner.main([str(self.owner_dir)]), 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report['backfill_candidates'], [self.JOB_A])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.runner.main([str(self.owner_dir), '--approve', report['fingerprint']]), 2)
        self.assertEqual(json.loads(out.getvalue())['error'], 'OPERATOR_APPROVAL_REQUIRED')
        self.assertFalse(self.canonical_path(self.JOB_A).exists())
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.runner.main([
                str(self.owner_dir), '--approve', report['fingerprint'], '--job', self.JOB_A,
            ]), 0)
        self.assertEqual(json.loads(out.getvalue())['applied'], [self.JOB_A])


if __name__ == '__main__':
    unittest.main()
