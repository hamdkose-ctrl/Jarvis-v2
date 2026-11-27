"""Synthetic no-network subprocess tests for the Brain Goal watchdog."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import brain_goal_supervisor as runner

META = {
    'head':'a'*40, 'corpus_sha256':'f'*64, 'scope':'goal_holdout_fresh',
    'generated_at':'2026-11-10T00:00:00+00:00',
    'state':'unmeasured', 'semantic_acceptance':False,
}

class _JumpingClock:
    """Gerçek uyku yerine enjekte edilen saat: her okumada bir saniye ilerler."""
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        self.now += 1.0
        return self.now


class _RacingChild:
    """İlerleme satırını tam okuma ile karar arasında yazan sahte alt süreç."""
    def __init__(self, command, *, stdout=None, **kwargs):
        self.log = stdout
        self.killed = False
        self.wrote = False
    def poll(self):
        if not self.wrote:
            self.wrote = True
            self.log.write('Semantic case 8/20\n')
            self.log.flush()
        return None
    def kill(self):
        self.killed = True
    def wait(self, timeout=None):
        return 0


class GoalWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.report = self.root / 'latest.json'

    def script(self, body):
        path = self.root / 'dummy_child.py'
        header = ('import argparse, json, time\n'
                  'p=argparse.ArgumentParser()\n'
                  'p.add_argument("--_worker",action="store_true")\n'
                  'p.add_argument("--json")\n'
                  'args,other=p.parse_known_args()\n')
        path.write_text(header + body, encoding='utf-8')
        return path

    def invoke(self, script, monotonic=None, **settings):
        options = {} if monotonic is None else {'monotonic': monotonic}
        return runner.supervise(script=script, args=['--run'], cwd=self.root,
                                report_path=self.report, metadata=META,
                                poll_seconds=.03, **options, **settings)

    def test_short_child_finishes_and_only_accepts_matching_version(self):
        body = ('print("Semantic case 1/20",flush=True)\n'
                'open(args.json,"w",encoding="utf-8").write(' +
                repr(json.dumps({**META,'state':'passed','semantic_acceptance':True,
                                 'cases':20,'model_responses':20,'accuracy':1,
                                 'incorrect_action_proposals':0,
                                 'attempted_effects':0})) + ')\n')
        self.assertEqual(self.invoke(self.script(body),stall_seconds=3),0)
        self.assertEqual(json.loads(self.report.read_text(encoding='utf-8'))['state'],'passed')

    def test_stalled_case_is_terminated_not_rescored_or_retried(self):
        body = ('print("Semantic case 8/20",flush=True)\n'
                'time.sleep(12)\n')
        self.assertEqual(self.invoke(self.script(body),stall_seconds=.3),2)
        report=json.loads(self.report.read_text(encoding='utf-8'))
        self.assertEqual(report['state'],'unmeasured')
        self.assertFalse(report['semantic_acceptance'])
        self.assertEqual(report['reason_code'],'HOLDOUT_STALLED')
        self.assertNotIn('accuracy',report)

    def test_progress_written_between_read_and_stall_decision_is_kept(self):
        # (T3d) "0 != 8" yarışı: satır, okuma ile durdurma kararı arasında yazılır.
        # Sahte saat ve sahte alt süreç sayesinde gerçek uyku/zamanlama yok.
        children = []
        def fake_popen(command, *, stdout=None, **kwargs):
            child = _RacingChild(command, stdout=stdout, **kwargs)
            children.append(child)
            return child
        with patch.object(runner.subprocess, 'Popen', side_effect=fake_popen):
            self.assertEqual(self.invoke(self.script(''),
                                         monotonic=_JumpingClock(), stall_seconds=.3), 2)
        report = json.loads(self.report.read_text(encoding='utf-8'))
        self.assertEqual(report['reason_code'], 'HOLDOUT_STALLED')
        self.assertEqual(report['last_started_case'], 8)
        self.assertTrue(children[0].killed)

    def test_pass_requires_complete_effect_free_metric_evidence(self):
        correct = {**META,'state':'passed','semantic_acceptance':True,
                   'cases':20,'model_responses':20,'accuracy':1,
                   'incorrect_action_proposals':0,'attempted_effects':0}
        self.assertTrue(runner._verified_verdict(correct,META,0))
        for broken in ({'accuracy':.90},{'incorrect_action_proposals':1},
                       {'attempted_effects':1},{'model_responses':19},
                       {'semantic_acceptance':False},{'head':'b'*40},
                       {'scope':'goal_holdout'}, {'cases':19}):
            with self.subTest(broken=broken):
                self.assertFalse(runner._verified_verdict({**correct,**broken},META,0))
        self.assertFalse(runner._verified_verdict(correct,META,1))

    def test_stale_pass_report_is_not_reused_after_worker_exit(self):
        self.report.write_text(json.dumps({**META,'state':'passed'}),encoding='utf-8')
        self.assertEqual(self.invoke(self.script('raise RuntimeError("fail")\n'),
                                     stall_seconds=3),2)
        report=json.loads(self.report.read_text(encoding='utf-8'))
        self.assertEqual(report['state'],'unmeasured')
        self.assertEqual(report['reason_code'],'HOLDOUT_WORKER_INVALID')

    def test_partial_output_is_not_exposed_as_synthetic_progress(self):
        tail,last=runner._parse_progress('', 'SECRET=abc\nSemantic case 4/20\n',
                                         show=False)
        self.assertEqual((tail,last),('',4))
        tail,last=runner._parse_progress('Semantic ca','se 8/20\n',show=False)
        self.assertEqual((tail,last),('',8))

if __name__=='__main__':
    unittest.main()
