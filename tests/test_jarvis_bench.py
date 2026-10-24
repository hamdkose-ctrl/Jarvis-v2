"""JarvisBench v0: runs nothing (no worker/planner/provider/model/account/
browser, no goal_executor/GoalState/Completion Policy). It only classifies an
already-captured observation against a versioned, read-only case catalog.
These tests cover the required v0 contract directly, then check the real
tests/data/jarvis_bench_v0.json catalog loads and evaluates as expected."""
import os
import unittest

from modules import jarvis_bench as bench


def catalog(**overrides):
    data = {
        'version': 'v0',
        'cases': [
            {
                'id': 'c1',
                'kind': 'read_only',
                'tool': 'research',
                'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'},
            }
        ],
    }
    data.update(overrides)
    return data


class LoadCasesTests(unittest.TestCase):
    def test_valid_v0_case_is_accepted(self):
        cases = bench.load_cases(catalog())
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]['id'], 'c1')

    def test_duplicate_case_id_fails_closed(self):
        data = catalog(cases=[
            {'id': 'dup', 'kind': 'read_only', 'tool': 'research',
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
            {'id': 'dup', 'kind': 'read_only', 'tool': 'data:headlines',
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
        ])
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(data)

    def test_effect_bearing_case_is_rejected(self):
        data = catalog(cases=[
            {'id': 'c1', 'kind': 'effect', 'tool': 'publish',
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
        ])
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(data)

    def test_non_read_only_kind_is_rejected_even_if_not_literally_effect(self):
        data = catalog(cases=[
            {'id': 'c1', 'kind': 'mixed', 'tool': 'browser',
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
        ])
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(data)

    def test_unknown_top_level_version_fails_closed(self):
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(catalog(version='v1'))

    def test_missing_version_fails_closed(self):
        data = catalog();del data['version']
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(data)

    def test_unknown_catalog_field_fails_closed(self):
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(catalog(extra_field='x'))

    def test_unknown_case_field_fails_closed(self):
        data = catalog(cases=[
            {'id': 'c1', 'kind': 'read_only', 'tool': 'research', 'extra': 1,
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
        ])
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(data)

    def test_unknown_expect_field_fails_closed(self):
        data = catalog(cases=[
            {'id': 'c1', 'kind': 'read_only', 'tool': 'research',
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow', 'extra': 1}},
        ])
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(data)

    def test_case_without_grounded_tool_name_fails_closed(self):
        data = catalog(cases=[
            {'id': 'c1', 'kind': 'read_only', 'tool': '',
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
        ])
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(data)

    def test_empty_case_list_fails_closed(self):
        with self.assertRaises(bench.BenchSchemaError):
            bench.load_cases(catalog(cases=[]))


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.case = bench.load_cases(catalog())[0]

    def test_full_matching_observation_passes(self):
        observation = {'evidence': ['s1'], 'safety_outcome': 'allow', 'permission_outcome': 'allow', 'duration_ms': 42}
        result = bench.evaluate(self.case, observation)
        self.assertEqual(result, {'id': 'c1', 'result': bench.PASS, 'reason_code': 'OK'})

    def test_no_evidence_never_passes(self):
        observation = {'evidence': [], 'safety_outcome': 'allow', 'permission_outcome': 'allow', 'duration_ms': 10}
        result = bench.evaluate(self.case, observation)
        self.assertNotEqual(result['result'], bench.PASS)
        self.assertEqual(result['result'], bench.INCONCLUSIVE)
        self.assertEqual(result['reason_code'], 'NO_EVIDENCE')

    def test_missing_evidence_key_never_passes(self):
        observation = {'safety_outcome': 'allow', 'permission_outcome': 'allow', 'duration_ms': 10}
        result = bench.evaluate(self.case, observation)
        self.assertNotEqual(result['result'], bench.PASS)

    def test_safety_outcome_mismatch_never_passes(self):
        observation = {'evidence': ['s1'], 'safety_outcome': 'block', 'permission_outcome': 'allow', 'duration_ms': 10}
        result = bench.evaluate(self.case, observation)
        self.assertEqual(result['result'], bench.FAIL)
        self.assertEqual(result['reason_code'], 'SAFETY_MISMATCH')

    def test_permission_outcome_mismatch_never_passes(self):
        observation = {'evidence': ['s1'], 'safety_outcome': 'allow', 'permission_outcome': 'ask', 'duration_ms': 10}
        result = bench.evaluate(self.case, observation)
        self.assertEqual(result['result'], bench.FAIL)
        self.assertEqual(result['reason_code'], 'PERMISSION_MISMATCH')

    def test_duration_ms_is_recorded_but_not_sufficient_alone(self):
        # duration_ms present and valid, but evidence missing and safety mismatched:
        # the duration alone must not cause a PASS.
        observation = {'evidence': [], 'safety_outcome': 'block', 'permission_outcome': 'allow', 'duration_ms': 999}
        result = bench.evaluate(self.case, observation)
        self.assertNotEqual(result['result'], bench.PASS)

    def test_missing_duration_ms_is_inconclusive_not_pass(self):
        observation = {'evidence': ['s1'], 'safety_outcome': 'allow', 'permission_outcome': 'allow'}
        result = bench.evaluate(self.case, observation)
        self.assertEqual(result['result'], bench.INCONCLUSIVE)
        self.assertEqual(result['reason_code'], 'MISSING_DURATION')

    def test_negative_duration_ms_is_inconclusive(self):
        observation = {'evidence': ['s1'], 'safety_outcome': 'allow', 'permission_outcome': 'allow', 'duration_ms': -1}
        result = bench.evaluate(self.case, observation)
        self.assertEqual(result['result'], bench.INCONCLUSIVE)

    def test_non_dict_observation_fails(self):
        result = bench.evaluate(self.case, None)
        self.assertEqual(result['result'], bench.FAIL)
        self.assertEqual(result['reason_code'], 'INVALID_OBSERVATION')

    def test_evidence_not_required_when_case_says_so(self):
        no_evidence_case = bench.load_cases(catalog(cases=[
            {'id': 'c1', 'kind': 'read_only', 'tool': 'system:status',
             'expect': {'evidence_required': False, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
        ]))[0]
        observation = {'safety_outcome': 'allow', 'permission_outcome': 'allow', 'duration_ms': 5}
        result = bench.evaluate(no_evidence_case, observation)
        self.assertEqual(result['result'], bench.PASS)

    def test_result_is_always_one_of_the_three(self):
        for observation in (None, {}, {'evidence': ['s1'], 'safety_outcome': 'allow', 'permission_outcome': 'allow', 'duration_ms': 1}):
            self.assertIn(bench.evaluate(self.case, observation)['result'], bench.RESULTS)


class RunTests(unittest.TestCase):
    def test_run_evaluates_each_case_against_its_own_observation(self):
        cases = bench.load_cases(catalog(cases=[
            {'id': 'a', 'kind': 'read_only', 'tool': 'research',
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
            {'id': 'b', 'kind': 'read_only', 'tool': 'data:headlines',
             'expect': {'evidence_required': True, 'safety_outcome': 'allow', 'permission_outcome': 'allow'}},
        ]))
        observations = {
            'a': {'evidence': ['s1'], 'safety_outcome': 'allow', 'permission_outcome': 'allow', 'duration_ms': 3},
        }
        results = bench.run(cases, observations)
        by_id = {r['id']: r for r in results}
        self.assertEqual(by_id['a']['result'], bench.PASS)
        self.assertEqual(by_id['b']['result'], bench.FAIL)
        self.assertEqual(by_id['b']['reason_code'], 'NO_OBSERVATION')

    def test_module_never_imports_goal_executor_or_goalstate(self):
        # sys.modules is shared across the whole unittest-discover process, so
        # checking it would pass or fail depending on what other test files
        # already imported, not on this module's own code. Parse the actual
        # import statements instead: deterministic, independent of run order.
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(bench))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in imported:
            self.assertNotIn('goal_executor', name)
            self.assertNotIn('goalstate', name.lower())


class RealCatalogTests(unittest.TestCase):
    """The shipped tests/data/jarvis_bench_v0.json must itself satisfy the v0
    schema and evaluate deterministically with no network/model/account call."""

    def setUp(self):
        self.path = os.path.join(os.path.dirname(__file__), 'data', 'jarvis_bench_v0.json')

    def test_shipped_catalog_loads_under_the_v0_schema(self):
        cases = bench.load_path(self.path)
        self.assertGreaterEqual(len(cases), 1)
        ids = [c['id'] for c in cases]
        self.assertEqual(len(ids), len(set(ids)))
        for case in cases:
            self.assertEqual(case['kind'], 'read_only')
            self.assertTrue(case['tool'])

    def test_shipped_catalog_evaluates_with_a_synthetic_matching_observation(self):
        cases = bench.load_path(self.path)
        observations = {
            case['id']: {
                'evidence': ['s1'],
                'safety_outcome': case['expect']['safety_outcome'],
                'permission_outcome': case['expect']['permission_outcome'],
                'duration_ms': 7,
            }
            for case in cases
        }
        results = bench.run(cases, observations)
        self.assertTrue(all(r['result'] == bench.PASS for r in results))


if __name__ == '__main__':
    unittest.main()
