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
import time
import re
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
    from modules.brain_contracts import neutral_observation
    refs = ()
    cards = ()
    if case['has_output']:
        refs = (ContextReference(id='last_doc', kind='artifact', source='session_state', owner=owner,
                provenance={'field':'last_doc', 'label':'araştırma özeti', 'path':None,
                            'document_digest':document_fingerprint(('Sentetik sonuç',None,'araştırma özeti'))}),)
        cards = ({'slot':'last_doc','label':'araştırma özeti'},)
    active = ActiveContext(owner=owner, request_id=f'dilim4-holdout-{index}', active_artifacts=refs)
    current = neutral_observation(owner=owner, request_id=active.request_id, text=case['text'], references=refs)
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


def reset_seconds(value):
    if not isinstance(value,str) or len(value)>50:
        return None
    parts=list(re.finditer(r"(\d+(?:\.\d+)?)(ms|s|m|h)",value))
    if not parts or ''.join(p.group(0) for p in parts)!=value:
        return None
    units={'ms':.001,'s':1,'m':60,'h':3600}
    return sum(float(p.group(1))*units[p.group(2)] for p in parts)


def response_shape(raw):
    """Protocol metadata only: never retain response text, values or unknown keys."""
    from modules.brain_model_understanding import ENVELOPE_KEYS, SCHEMA_VERSION
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {'json_object':False}
    if not isinstance(value,dict):
        return {'json_object':False}
    return {'json_object':True, 'missing_fields':sorted(ENVELOPE_KEYS-set(value)),
            'extra_field_count':len(set(value)-ENVELOPE_KEYS),
            'version_matches':value.get('schema_version') == SCHEMA_VERSION,
            'named_wrapper':SCHEMA_VERSION in value}


def measure(owner, cases, *, interval_seconds=35):
    calls = Counter()
    def denied(name):
        def stop(*args, **kwargs):
            calls[name] += 1
            raise RuntimeError('Acceptance must not execute effects: '+name)
        return stop
    from modules import llm, requests_state
    from modules.brain_model_understanding import proposal_diagnostic
    provider = Counter()
    shape = None
    send = llm._send_provider
    def observed_send(*args, **kwargs):
        nonlocal shape
        provider['requests'] += 1
        result = send(*args, **kwargs)
        provider['responses'] += 1
        shape = response_shape(result)
        return result
    rows = []
    stop_reason = None
    # Observe actual sends without replacing the model, route, response or credentials.
    with ExitStack() as stack:
        stack.enter_context(patch.object(llm, '_send_provider', side_effect=observed_send))
        for target in ('modules.engine_intents.dispatch','modules.output.save_text_result','modules.diagnose.run'):
            stack.enter_context(patch(target, side_effect=denied(target)))
        for index, case in enumerate(cases):
            if index and interval_seconds:
                from modules import usage_meter
                seen=usage_meter.limits(owner).get('groq',{}).get(llm.groq_model(),{})
                reset=reset_seconds(seen.get('tok_reset'))
                delay=max(interval_seconds, 0 if reset is None else reset+1)
                if delay>120:
                    stop_reason = 'quota_wait_too_long'
                    break  # Report incomplete measurement, never ignore a long quota wait.
                print(f'Waiting {delay:.1f}s for the token budget',flush=True)
                time.sleep(delay)
            print(f'Semantic case {index+1}/{len(cases)}',flush=True)
            before = provider['responses']
            shape = None
            proposal_diagnostic(clear=True)
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
            if shape is not None:
                row['response_shape'] = shape
            diagnostic = proposal_diagnostic()
            if diagnostic:
                row['proposal_diagnostic'] = diagnostic
                if result is None and diagnostic.get('operation') in {'direct_action','action_batch'}:
                    caps = diagnostic.get('capabilities', [])
                    candidate = caps[0] if len(caps) == 1 and diagnostic['operation'] == 'direct_action' else None
                    row['incorrect_action_proposal'] = candidate not in case['expected']
            rows.append(row)
            if not row['responded']:
                # Two different root causes must not share one label: the provider may have been
                # silent, or our own finite budget may have ended while it was still answering.
                stop_reason = ('local_deadline_exceeded'
                               if (diagnostic or {}).get('reason_code') == 'LOCAL_DEADLINE_EXCEEDED'
                               else 'provider_no_response')
                break  # Do not repeat requests against an unavailable provider.
            if index == 0 and not row['valid_proposal']:
                stop_reason = 'model_response_invalid'
                break  # Validate the first response before spending the rest of the quota.
    summary=verdict(rows,sum(calls.values()))
    if len(rows)<len(cases):
        critical=(summary['incorrect_action_proposals'] or summary['attempted_effects']
                  or any(row['responded'] and not row['valid_proposal'] for row in rows))
        summary.update(state='failed' if critical else 'unmeasured',accuracy=None)
    return {**summary, 'results':rows,
            'provider_requests':provider['requests'], 'provider_responses':provider['responses'],
            'planned_cases':len(cases), 'stop_reason':stop_reason}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--connection-only',action='store_true',help='One real proposal; never a semantic acceptance result.')
    parser.add_argument('--json',type=Path)
    parser.add_argument('--interval-seconds',type=float,default=35,help='Spacing outside each request budget; default35 for Free-tier token limits.')
    args = parser.parse_args(argv)
    if not 0 <= args.interval_seconds <= 120:
        parser.error('--interval-seconds must be between0 and120')
    cases = json.loads(CORPUS.read_text(encoding='utf-8'))['cases']
    if args.connection_only:
        cases = cases[:1]
    if not args.run:
        print(f'PLAN: {len(cases)} bounded semantic requests, synthetic context, no effects. Use --run on the configured Windows PC.')
        return 0
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    report = {'head':head,'corpus_sha256':hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
              'generated_at':datetime.now(timezone.utc).isoformat(),'state':'unmeasured',
              'scope':'connection' if args.connection_only else 'holdout',
              'semantic_acceptance':False}
    try:
        owner, ok, reason = preflight()
        if not ok:
            report['reason'] = reason
            report['reason_code'] = 'route_unavailable'
        else:
            report.update(measure(owner,cases,interval_seconds=args.interval_seconds))
            if args.connection_only:
                valid = bool(report.get('provider_responses') and report.get('results')
                             and report['results'][0]['valid_proposal']
                             and not report.get('attempted_effects'))
                if report.get('provider_responses'):
                    report['state'] = 'passed' if valid else 'failed'
                report['connection_ok'] = valid
                for key in ('accuracy', 'groups', 'incorrect_action_proposals'):
                    report.pop(key, None)
                report['results'] = [{k:v for k,v in row.items()
                                     if k in {'id','responded','valid_proposal','error_class','response_shape','proposal_diagnostic'}}
                                    for row in report.get('results', [])]
            else:
                report['semantic_acceptance'] = report['state'] == 'passed'
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
