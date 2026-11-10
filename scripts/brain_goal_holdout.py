"""BRAIN-05 live multi-goal semantic holdout; never executes or mutates goals.

Dry-run (no model calls): python -X utf8 scripts/brain_goal_holdout.py
Live (20 calls, only on the configured user PC):
    python -X utf8 scripts/brain_goal_holdout.py --run --json brain-goal-holdout.json

The established holdout's privacy and routing preflight, attempt spacing, no-effect
guards, protocol diagnostics and failure verdict are reused, not weakened.
The scored goal cards are synthetic; no real user goal IDs, text or state are read.
This proves model goal *selection*, not end-to-end effect execution or voice/UI.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import brain_output_diagnose_holdout as base

CORPUS = ROOT / 'tests/data/brain_goal_holdout.json'
FRESH_CORPUS = ROOT / 'tests/data/brain_goal_holdout_fresh.json'


def ask(owner, case, index):
    from modules.brain_contracts import ActiveContext, ContextReference
    from modules.brain_model_understanding import propose
    from modules.brain_understanding import understand
    cards = tuple(ContextReference(
        id=goal['id'], kind='goal', source='goal_state', owner=owner,
        provenance={'title':goal['title'], 'state':goal['state'], 'priority':1},
    ) for goal in case['goals'])
    active = ActiveContext(owner=owner, request_id=f'goal-holdout-{index}', goal_candidates=cards)
    current = understand(owner=owner, request_id=active.request_id, text=case['text'],
                         active_context=active, candidates=(), references=())
    return propose(owner=owner, text=case['text'], current=current,
                   arguments=current.arguments,
                   protected_relation=(current.pending_owner is not None or
                                       current.conversation_relation.value != 'NEW_REQUEST'),
                   goal_candidates=cards)


def judge(case, proposal, *, response_received=None):
    operation = getattr(proposal, 'operation', None)
    target_ids = tuple(getattr(proposal, 'target_goal_ids', ()) or ())
    actions = tuple(getattr(proposal, 'actions', ()) or ())
    goal_card = getattr(proposal, 'goal', None)
    expected = case['expected']
    correct = bool(proposal is not None
                   and operation == expected['operation']
                   and target_ids == tuple(expected['targets'])
                   and bool(goal_card) == expected.get('goal_card', False)
                   and not actions)
    is_effect = operation in {
        'direct_action', 'action_batch', 'create_goal', 'continue_goal',
        'revise_goal', 'add_task', 'pause_goal', 'resume_goal',
        'cancel_goal', 'prioritize_goal',
    }
    return {
        'id':case['id'], 'group':case['group'], 'outcome':operation,
        'responded':proposal is not None if response_received is None else response_received,
        'valid_proposal':proposal is not None, 'correct':correct,
        'incorrect_action_proposal':bool(is_effect and not correct),
    }


def measure(owner, cases, *, interval_seconds=35):
    # The common runner already instruments the exact production provider call and
    # blocks dispatch, save and diagnose. Replace only the synthetic question/scorer.
    with patch.object(base, 'ask', side_effect=ask), patch.object(base, 'judge', side_effect=judge):
        return base.measure(owner, cases, interval_seconds=interval_seconds)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--connection-only', action='store_true')
    # Only the supervisor may spawn a worker; a direct user --run is supervised.
    parser.add_argument('--_worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--suite', choices=('baseline','fresh'), default='baseline',
                        help='Use fresh, independent synthetics without altering original acceptance.')
    parser.add_argument('--json', type=Path)
    parser.add_argument('--interval-seconds', type=float, default=35)
    args = parser.parse_args(argv)
    if not 0 <= args.interval_seconds <= 120:
        parser.error('--interval-seconds must be between 0 and 120')
    selected = CORPUS if args.suite == 'baseline' else FRESH_CORPUS
    cases = json.loads(selected.read_text(encoding='utf-8'))['cases']
    if len(cases) != 20 or len({row['id'] for row in cases}) != 20:
        raise ValueError('BRAIN-05 holdout requires exactly 20 unique cases.')
    if args.connection_only:
        cases = cases[:1]
    if not args.run:
        print(f'PLAN: {len(cases)} synthetic goal cases, no effects; use --run on the configured Windows PC.')
        return 0
    head = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    report = {
        'head':head, 'corpus_sha256':hashlib.sha256(selected.read_bytes()).hexdigest(),
        'generated_at':datetime.now(timezone.utc).isoformat(), 'state':'unmeasured',
        'scope':'connection' if args.connection_only else ('goal_holdout_fresh' if args.suite == 'fresh' else 'goal_holdout'),
        'semantic_acceptance':False,
    }
    if not args._worker:
        # On Windows QuickEdit and a provider socket may stall the console or
        # block inside requests despite its cooperative 30-second budget.
        # Run the unchanged effect-guarded acceptance in an isolated process.
        from scripts.brain_goal_supervisor import supervise
        worker_args = ['--run', '--suite', args.suite, '--interval-seconds',
                       str(args.interval_seconds)]
        if args.connection_only:
            worker_args.append('--connection-only')
        return supervise(script=Path(__file__).resolve(), args=worker_args,
                         cwd=ROOT, report_path=args.json, metadata=report)
    try:
        owner, ok, reason = base.preflight()
        if not ok:
            report.update(reason=reason, reason_code='route_unavailable')
        else:
            report.update(measure(owner, cases, interval_seconds=args.interval_seconds))
            if args.connection_only:
                valid = bool(report.get('provider_responses') and report.get('results')
                             and report['results'][0]['valid_proposal']
                             and not report.get('attempted_effects'))
                if report.get('provider_responses'):
                    report['state'] = 'passed' if valid else 'failed'
                report['connection_ok'] = valid
                for key in ('accuracy','groups','incorrect_action_proposals'):
                    report.pop(key,None)
                report['results'] = [{k:v for k,v in row.items()
                                     if k in {'id','responded','valid_proposal','error_class','response_shape','proposal_diagnostic'}}
                                    for row in report.get('results', [])]
            else:
                report['semantic_acceptance'] = report['state'] == 'passed'
    except Exception as exc:
        report.update(state='unmeasured', reason='measurement interrupted: '+type(exc).__name__)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return {'passed':0,'failed':1,'unmeasured':2}[report['state']]


if __name__ == '__main__':
    raise SystemExit(main())
