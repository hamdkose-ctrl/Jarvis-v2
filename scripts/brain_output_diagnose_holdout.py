"""Dilim4 live semantics on the real user's existing production route; never execute effects.

Default: list the measurement plan (no profile/provider access). --run: 20 bounded
production proposals using synthetic context. JSON reports contain no profile/key/content.
Exit 0=passed, 1=measured failure, 2=unmeasured. Mock tests validate this runner only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CORPUS = ROOT / 'tests/data/brain_output_diagnose_holdout.json'


def preflight():
    # Same eligibility check as the existing live semantic acceptance, no alternate route.
    from scripts.brain_semantic_holdout import _preflight
    return _preflight()


def ask(owner, case, index):
    from modules.brain_context import document_fingerprint
    from modules.brain_contracts import ActiveContext, ContextReference
    from modules.brain_model_understanding import propose
    from modules.brain_understanding import understand
    refs = ()
    cards = ()
    if case['has_output']:
        refs = (ContextReference(id='last_doc', kind='artifact', source='session_state', owner=owner,
                provenance={'field':'last_doc', 'label':'araştırma özeti', 'path':None,
                            'document_digest':document_fingerprint(('Sentetik sonuç',None,'araştırma özeti'))}),)
        cards = ({'slot':'last_doc','label':'araştırma özeti'},)
    active = ActiveContext(owner=owner, request_id=f'dilim4-holdout-{index}', active_artifacts=refs)
    current = understand(owner=owner, request_id=active.request_id, text=case['text'],
                         active_context=active, candidates=refs, references=refs)
    # Expected labels never reach the model. Score only the real proposal, never a fallback.
    return propose(owner=owner, text=case['text'], current=current, arguments=current.arguments,
                   protected_relation=current.pending_owner is not None or current.conversation_relation.value != 'NEW_REQUEST',
                   session_artifacts=cards)


def judge(case, proposal, *, response_received=None):
    outcome = None
    if proposal is not None:
        if proposal.operation == 'chat':
            outcome = 'chat'
        elif proposal.operation == 'clarify':
            outcome = 'needs_input'
        elif proposal.operation == 'direct_action' and len(proposal.actions) == 1:
            outcome = proposal.actions[0].capability_id
    allowed = case['expected']
    action = bool(proposal is not None and proposal.operation in {'direct_action','action_batch'})
    return {'id':case['id'], 'group':case['group'], 'outcome':outcome,
            'responded':proposal is not None if response_received is None else response_received,
            'valid_proposal':proposal is not None, 'correct':outcome in allowed,
            'incorrect_action_proposal':action and outcome not in allowed}


def verdict(rows, attempted_effects):
    responded = sum(row['responded'] for row in rows)
    critical = sum(row['incorrect_action_proposal'] for row in rows)
    complete = bool(rows) and responded == len(rows)
    accuracy = sum(row['correct'] for row in rows)/len(rows) if complete else None
    if critical or attempted_effects:
        state = 'failed'
    elif not complete:
        state = 'unmeasured'
    else:
        state = 'passed' if accuracy >= .95 else 'failed'
    groups = {}
    for group in sorted({row['group'] for row in rows}):
        group_rows = [row for row in rows if row['group']==group]
        groups[group] = {'cases':len(group_rows), 'correct':sum(row['correct'] for row in group_rows)}
    return {'state':state,'cases':len(rows),'model_responses':responded,'accuracy':accuracy,
            'incorrect_action_proposals':critical,'attempted_effects':attempted_effects,'groups':groups}


def measure(owner, cases):
    calls = Counter()
    def denied(name):
        def stop(*args, **kwargs):
            calls[name] += 1
            raise RuntimeError('Acceptance must not execute effects: '+name)
        return stop
    from modules import llm, requests_state
    provider = Counter()
    send = llm._send_provider
    def observed_send(*args, **kwargs):
        provider['requests'] += 1
        result = send(*args, **kwargs)
        provider['responses'] += 1
        return result
    rows = []
    # Observe actual sends without replacing the model, route, response or credentials.
    with ExitStack() as stack:
        stack.enter_context(patch.object(llm, '_send_provider', side_effect=observed_send))
        for target in ('modules.engine_intents.dispatch','modules.output.save_text_result','modules.diagnose.run'):
            stack.enter_context(patch(target, side_effect=denied(target)))
        for index, case in enumerate(cases):
            before = provider['responses']
            error_class = None
            try:
                result = ask(owner, case, index)
            except requests_state.Cancelled:
                raise
            except Exception as exc:
                result = None
                error_class = type(exc).__name__
            row = judge(case, result, response_received=provider['responses'] > before)
            if error_class:
                row['error_class'] = error_class
            rows.append(row)
    return {**verdict(rows,sum(calls.values())), 'results':rows,
            'provider_requests':provider['requests'], 'provider_responses':provider['responses']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--json',type=Path)
    args = parser.parse_args(argv)
    cases = json.loads(CORPUS.read_text(encoding='utf-8'))['cases']
    if not args.run:
        print(f'PLAN: {len(cases)} bounded semantic requests, synthetic context, no effects. Use --run on the configured Windows PC.')
        return 0
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    report = {'head':head,'corpus_sha256':hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
              'generated_at':datetime.now(timezone.utc).isoformat(),'state':'unmeasured'}
    try:
        owner, ok, reason = preflight()
        if not ok:
            report['reason'] = reason
        else:
            report.update(measure(owner,cases))
    except Exception as exc:
        # Do not publish traceback, SDK messages, profile or credentials in the artifact.
        report.update(state='unmeasured',reason='measurement interrupted: '+type(exc).__name__)
    if args.json:
        args.json.parent.mkdir(parents=True,exist_ok=True)
        args.json.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return {'passed':0,'failed':1,'unmeasured':2}[report['state']]


if __name__ == '__main__':
    raise SystemExit(main())
