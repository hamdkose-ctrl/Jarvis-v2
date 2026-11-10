"""Synthetic no-network subprocess tests for the Brain Goal watchdog."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from scripts import brain_goal_supervisor as runner

META = {
    'head':'a'*40, 'corpus_sha256':'f'*64, 'scope':'goal_holdout_fresh',
    'generated_at':'2026-11-10T00:00:00+00:00',
    'state':'unmeasured', 'semantic_acceptance':False,
}

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

    def invoke(self, script, **settings):
        return runner.supervise(script=script, args=['--run'], cwd=self.root,
                                report_path=self.report, metadata=META,
                                poll_seconds=.03, **settings)

    def test_short_child_finishes_and_only_accepts_matching_version(self):
        body = ('print("Semantic case 1/20",flush=True)\n'
                'open(args.json,"w",encoding="utf-8").write(' +
                repr(json.dumps({**META,'state':'passed','semantic_acceptance':True,
                                 'cases':20,'accuracy':1,'incorrect_action_proposals':0,
                                 'attempted_effects':0})) + ')\n')
        self.assertEqual(self.invoke(self.script(body),stall_seconds=3),0)
        self.assertEqual(json.loads(self.report.read_text(encoding='utf-8'))['state'],'passed')

    def test_stalled_case_is_terminated_not_rescored_or_retried(self):
        body = ('print("Semantic case 8/20",flush=True)\n'
                'time.sleep(12)\n')
        start=time.monotonic()
        self.assertEqual(self.invoke(self.script(body),stall_seconds=.3),2)
        self.assertLess(time.monotonic()-start,4)
        report=json.loads(self.report.read_text(encoding='utf-8'))
        self.assertEqual(report['state'],'unmeasured')
        self.assertFalse(report['semantic_acceptance'])
        self.assertEqual(report['reason_code'],'HOLDOUT_STALLED')
        self.assertEqual(report['last_started_case'],8)
        self.assertNotIn('accuracy',report)

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
