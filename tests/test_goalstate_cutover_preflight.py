import hashlib
import json
import tempfile
import unittest
from pathlib import Path


class GoalStateCutoverPreflightTests(unittest.TestCase):
    def setUp(self):
        from modules import goalstate_cutover_preflight as preflight
        from modules import goal_state, goal_state_compat, goal_state_store
        self.preflight = preflight
        self.goal_state = goal_state
        self.compat = goal_state_compat
        self.store = goal_state_store
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner_dir = self.root / 'alice'
        self.owner_dir.mkdir()

    def legacy_job(self, job_id='0123456789abcdef', owner='alice', state='running',
                    request='Raporu hazırla'):
        return {
            'id': job_id, 'owner': owner, 'request': request, 'created': 1,
            'state': state, 'goals': [], 'steps': [], 'outputs': {},
        }

    def write_legacy(self, job):
        path = self.owner_dir / (job['id'] + '.json')
        path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        return path

    def write_canonical(self, job, *, target_state=None):
        canonical_path = self.owner_dir / (job['id'] + '.goalstate.json')
        state = self.compat.project(job)
        if target_state is not None and target_state != state['state']:
            from modules import core_state_reducer
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': target_state, 'reason_code': 'TEST_SETUP',
            })
        self.store.create(canonical_path, state)
        return canonical_path, state

    def test_matching_pair_is_ok(self):
        job = self.legacy_job(state='running')
        self.write_legacy(job)
        self.write_canonical(job)
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(len(report['rows']), 1)
        self.assertEqual(report['rows'][0]['reason_code'], 'OK')
        self.assertEqual(report['rows'][0]['job_id'], job['id'])
        self.assertTrue(report['ok'])

    def test_missing_canonical(self):
        job = self.legacy_job()
        self.write_legacy(job)
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(report['rows'][0]['reason_code'], 'MISSING_CANONICAL')
        self.assertFalse(report['ok'])

    def test_corrupt_canonical_does_not_leak_raw_content(self):
        job = self.legacy_job()
        self.write_legacy(job)
        canonical_path = self.owner_dir / (job['id'] + '.goalstate.json')
        canonical_path.write_bytes(b'{"schema":"goal_state.v1", "SUPER_SECRET_TOKEN": "abc123"')
        report = self.preflight.scan(self.owner_dir)
        row = report['rows'][0]
        self.assertEqual(row['reason_code'], 'CANONICAL_CORRUPT')
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn('SUPER_SECRET_TOKEN', serialized)
        self.assertNotIn('abc123', serialized)

    def test_unknown_legacy_state(self):
        job = self.legacy_job(state='teleporting')
        self.write_legacy(job)
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(report['rows'][0]['reason_code'], 'UNKNOWN_LEGACY_STATE')

    def test_identity_mismatch(self):
        job = self.legacy_job()
        self.write_legacy(job)
        other_job = self.legacy_job(request='Tamamen başka bir hedef')
        self.write_canonical(other_job)
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(report['rows'][0]['reason_code'], 'IDENTITY_MISMATCH')

    def test_execution_mode_mismatch_is_identity_mismatch(self):
        from modules import core_state_reducer
        job = self.legacy_job()
        self.write_legacy(job)
        state = self.goal_state.new(
            owner=job['owner'], job_id=job['id'], goal=job['request'], execution_mode='durable'
        )
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_state',
            'state': 'running', 'reason_code': 'TEST_SETUP',
        })
        self.store.create(self.owner_dir / (job['id'] + '.goalstate.json'), state)
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(report['rows'][0]['reason_code'], 'IDENTITY_MISMATCH')

    def test_state_divergence(self):
        job = self.legacy_job(state='running')
        self.write_legacy(job)
        self.write_canonical(job, target_state='paused')
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(report['rows'][0]['reason_code'], 'STATE_DIVERGENCE')

    def test_terminal_divergence(self):
        job = self.legacy_job(state='running')
        self.write_legacy(job)
        self.write_canonical(job, target_state='done')
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(report['rows'][0]['reason_code'], 'TERMINAL_DIVERGENCE')

    def test_different_terminal_states_are_terminal_divergence(self):
        legacy = self.legacy_job(state='cancelled')
        self.write_legacy(legacy)
        active = self.legacy_job(state='running')
        self.write_canonical(active, target_state='done')
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(report['rows'][0]['reason_code'], 'TERMINAL_DIVERGENCE')

    def test_deterministic_job_id_order(self):
        job_ids = ['ffffffffffffffff', '0000000000000000', '7777777777777777']
        for job_id in job_ids:
            job = self.legacy_job(job_id=job_id)
            self.write_legacy(job)
            self.write_canonical(job)
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual([row['job_id'] for row in report['rows']], sorted(job_ids))

    def test_scan_does_not_modify_any_file(self):
        job = self.legacy_job()
        legacy_path = self.write_legacy(job)
        canonical_path, _ = self.write_canonical(job)

        def fingerprint():
            out = {}
            for path in sorted(self.owner_dir.iterdir()):
                raw = path.read_bytes()
                out[path.name] = (path.stat().st_mtime_ns, hashlib.sha256(raw).hexdigest())
            return out

        before = fingerprint()
        self.preflight.scan(self.owner_dir)
        after = fingerprint()
        self.assertEqual(before, after)
        self.assertTrue(legacy_path.exists())
        self.assertTrue(canonical_path.exists())

    def test_non_legacy_filenames_are_ignored(self):
        job = self.legacy_job()
        self.write_legacy(job)
        self.write_canonical(job)
        (self.owner_dir / 'latest.json').write_text('{}', encoding='utf-8')
        (self.owner_dir / (job['id'] + '.effects.json')).write_text('{}', encoding='utf-8')
        (self.owner_dir / (job['id'] + '.json.lock')).write_bytes(b'0')
        (self.owner_dir / (job['id'] + '.json.tmp')).write_text('{}', encoding='utf-8')
        report = self.preflight.scan(self.owner_dir)
        self.assertEqual(len(report['rows']), 1)
        self.assertEqual(report['rows'][0]['job_id'], job['id'])

    def test_invalid_legacy_record_does_not_abort_scan(self):
        bad_path = self.owner_dir / '1111111111111111.json'
        bad_path.write_text('not json at all', encoding='utf-8')
        good_job = self.legacy_job(job_id='2222222222222222')
        self.write_legacy(good_job)
        self.write_canonical(good_job)
        report = self.preflight.scan(self.owner_dir)
        codes = {row['job_id']: row['reason_code'] for row in report['rows']}
        self.assertEqual(codes['1111111111111111'], 'INVALID_LEGACY_RECORD')
        self.assertEqual(codes['2222222222222222'], 'OK')

    def test_report_does_not_expose_path_owner_or_personal_content(self):
        secret_request = 'PERSONAL_REQUEST_DO_NOT_LEAK'
        secret_blocker = 'PRIVATE_BLOCKER_DO_NOT_LEAK'
        job = self.legacy_job(request=secret_request)
        job['blocker'] = secret_blocker
        self.write_legacy(job)
        self.write_canonical(job)
        report = self.preflight.scan(self.owner_dir)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(self.owner_dir), serialized)
        self.assertNotIn('alice', serialized)
        self.assertNotIn(secret_request, serialized)
        self.assertNotIn(secret_blocker, serialized)
        self.assertNotIn('root', report)
        self.assertNotIn('owner', report['rows'][0])

    def test_invalid_root_raises_safe_error(self):
        missing_root = self.root / 'does-not-exist'
        with self.assertRaises(self.preflight.PreflightScanError):
            self.preflight.scan(missing_root)


if __name__ == '__main__':
    unittest.main()
