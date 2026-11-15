"""Read-only proposal/certification for an existing canonical plan revision.

The existing Scheduler calls execute; Core's compatibility adapter alone
commits the new plan/evidence. No provider/worker is rerun by result reuse.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json

import release_guard
from modules.diagnostics import record_failure as _record_failure
from modules import (
    canonical_goal_control, canonical_goal_flow, canonical_output_projection,
    dependency_evidence, execution_record, goal_job_control, goal_plan_gate,
    goal_state, goal_state_compat, goal_tools, llm, model_wait,
    requests_state, task_plan_contracts,
)


@dataclass(frozen=True)
class RevisionProof:
    owner: str
    job_id: str
    goal_version: int
    record_digest: str
    plan_digest: str
    reused: tuple[tuple[str, str], ...]


def source_before_edit(current):
    """Inspect the original accepted audit prefix, never rewrite stored history."""
    source = copy.deepcopy(current)
    start = max(i for i, row in enumerate(source['audit']) if row['op'] == 'set_goal_plan')
    end = next((i for i, row in enumerate(source['audit'][start + 1:], start + 1)
                if row['op'] == 'mutate_goal_intent' and row['reason_code'] != 'USER_GOAL_PRIORITY'),
               len(source['audit']))
    source['audit'] = source['audit'][:end]
    count = sum(row['op'] == 'append_evidence' for row in source['audit'])
    source['evidence'] = source['evidence'][:count]
    source['version'] = source['audit'][-1]['version']
    source['state'] = source['audit'][-1]['state']
    return goal_state.validate(source)


def _unknown_replay(current, record, proposed):
    old = {node['id']: node for node in current['goal_plan']['nodes']}
    source = source_before_edit(current)
    for step in record['steps']:
        node = old.get(step['id'])
        if node is None:
            raise ValueError('Eski plan adımı doğrulanamadı.')
        if (step.get('tool') != node['capability_id'].removeprefix('task.')
                or step.get('input') != node['input'] or step.get('depends') != node['depends_on']):
            raise ValueError('Eski planın yürütme girdisi değişmiş.')
        if (step.get('state') == 'queued' and step.get('attempts', 0) == 0
                and step.get('started') in (False, None) and step['id'] not in record['outputs']):
            continue
        if step.get('started') is not True or step.get('attempts') != 1:
            raise ValueError('Eski deneme kimliği doğrulanamadı.')
        if step.get('state') == 'done':
            try:
                canonical_output_projection._accepted_row(source, current['owner'], current['job_id'],
                                                          node, record['outputs'].get(step['id']))
            except (ValueError, TypeError, AttributeError):
                pass
            else:
                continue
        if any(n['capability_id'] == node['capability_id'] and n['input'] == node['input']
               for n in proposed['nodes']):
            raise ValueError('Sonucu belirsiz eski adım yeni kimlikle tekrar başlatılamaz; kaynak incelemesi gerekli.')


def certify(owner, job_id, proposed):
    from modules import goal_executor
    root = goal_executor._owner_root(owner)
    with goal_job_control.locked(root, job_id):
        _root, current, record = canonical_goal_control._pair(owner, job_id)
        if current['state'] != 'paused' or record['state'] != 'revision_running':
            raise ValueError('Hedef revizyon kabulü için güvenli beklemede değil.')
        _unknown_replay(current, record, proposed)
        candidates = set(goal_plan_gate.revision_reuse_candidates(current, proposed))
        source = source_before_edit(current)
        copies = []
        for node in proposed['nodes']:
            ident = node['id']
            if ident not in candidates or any(dep not in {i for i, _ in copies} for dep in node['depends_on']):
                continue
            output = record['outputs'].get(ident)
            if not isinstance(output, dict):
                continue
            try:
                canonical_output_projection._accepted_row(source, owner, job_id, node, output)
            except ValueError:
                continue
            copies.append((ident, copy.deepcopy(output)))
        proof = RevisionProof(owner, job_id, current['version'], goal_job_control.fingerprint(record),
                              goal_job_control.fingerprint(proposed), ())
    # Domain verification can read receipts/files; keep it outside the Core lock.
    verified = []
    for ident, output in copies:
        try:
            if goal_tools.verify(output, owner) is True:
                verified.append((ident, dependency_evidence.output_sha256(output)))
        except (ValueError, PermissionError, OSError, TypeError, KeyError):
            continue
    # A child cannot reuse an old result if its parent's domain proof was lost.
    reusable = set()
    for node in proposed['nodes']:
        if node['id'] in {ident for ident, _ in verified} and all(dep in reusable for dep in node['depends_on']):
            reusable.add(node['id'])
    return RevisionProof(proof.owner, proof.job_id, proof.goal_version, proof.record_digest,
                         proof.plan_digest, tuple(row for row in verified if row[0] in reusable))


def execute(profile, job_id, *, stop_event=None):
    owner = getattr(profile, 'slug', None)
    from modules import goal_executor
    root = goal_executor._owner_root(owner)
    with goal_job_control.locked(root, job_id):
        _root, current, record = canonical_goal_control._pair(owner, job_id)
        if (current['state'] != 'paused' or record.get('state') != 'revision_queued'
                or (current.get('blocker') or {}).get('code') == 'PAUSED_BY_USER'):
            return False
        if stop_event is not None and stop_event.is_set():
            return False
        expected = current['version']
        record['state'] = 'revision_running'
        canonical_goal_control._write(root, record)
        prompt = json.dumps({'request': current['goal'], 'user_goal_intent': current.get('goal_intent'),
                             'user_goal_changes': goal_state.intent_history(current),
                             'previous_plan': current['goal_plan'],
                             'instruction': 'Keep unchanged node IDs. Apply user_goal_changes in order (later edits may replace earlier scope); use aggregate intent for older edits without history. Propose the whole DAG.'},
                            ensure_ascii=False)
    rid = hashlib.sha256(f'{owner}\0{job_id}\0revision\0{expected}'.encode()).hexdigest()[:32]
    token = llm._key_context.set(owner)
    try:
        if not requests_state.register_background(owner, rid, seconds=1800):
            raise ValueError('Bu plan revizyonu zaten başlatıldı.')
        with requests_state.activate(owner, rid):
            def check_stop():
                if stop_event is not None and stop_event.is_set():
                    raise requests_state.Cancelled('Plan revizyonu durduruldu.')
            with requests_state.worker_probe(check_stop):
                raw = model_wait.ask(prompt, system=task_plan_contracts._SYSTEM,
                                     max_tokens=2200, seconds=60)
                requests_state.check()
                tasks = task_plan_contracts.validate(task_plan_contracts._json(raw)['tasks'])
                proposed = canonical_goal_flow._canonical_plan(tasks, allow_effects=True)
                proposed['plan_version'] = current['goal_plan']['plan_version'] + 1
                proof = certify(owner, job_id, proposed)
                requests_state.check()
                goal_state_compat.commit_plan_revision(
                    root / (job_id + '.goalstate.json'), owner=owner, job_id=job_id,
                    plan=proposed, proof=proof)
        return 'planned'
    except Exception:
        _record_failure('modules/canonical_plan_revision.py:execute')
        with goal_job_control.locked(root, job_id):
            _root, fresh, record = canonical_goal_control._pair(owner, job_id)
            if (record.get('state') == 'revision_running' and fresh['state'] == 'paused'
                    and fresh.get('goal_plan', {}).get('plan_version') == current['goal_plan']['plan_version']):
                record['state'] = 'review'
                record.pop('_pending_plan_projection', None)
                record['blocker'] = 'Plan revizyonu doğrulanamadı; eski veya belirsiz işlem yeniden başlatılmadı.'
                canonical_goal_control._write(root, record)
        return 'review'
    finally:
        llm._key_context.reset(token)


def recover_projection(root, current, record):
    """Replay only a Core-accepted journal projection, never model/worker work."""
    pending = record.get('_pending_plan_projection')
    if not isinstance(pending, dict) or pending.get('plan') != current.get('goal_plan'):
        return record
    next_record = pending.get('record')
    if (not isinstance(next_record, dict) or next_record.get('state') != 'running'
            or (next_record.get('owner'), next_record.get('id')) != (current['owner'], current['job_id'])):
        raise ValueError('Plan yansıtma kaydı geçersiz.')
    nodes = {node['id']: node for node in current['goal_plan']['nodes']}
    if len(next_record.get('steps', [])) != len(nodes):
        raise ValueError('Plan yansıtma adımları eşleşmiyor.')
    ids = [step.get('id') for step in next_record['steps']]
    if (len(set(ids)) != len(ids) or set(ids) != set(nodes)
            or set(next_record.get('outputs', {})) - set(nodes)
            or next_record.get('request', '').strip() != current['goal']):
        raise ValueError('Plan yansıtma kimliği veya çıktı kümesi değişmiş.')
    for step in next_record['steps']:
        node = nodes.get(step.get('id'))
        if (node is None or step.get('tool') != node['capability_id'].removeprefix('task.')
                or step.get('input') != node['input'] or step.get('depends') != node['depends_on']):
            raise ValueError('Plan yansıtma girdisi değişmiş.')
        output = next_record.get('outputs', {}).get(node['id'])
        if step.get('state') == 'done':
            canonical_output_projection._accepted_row(current, current['owner'], current['job_id'], node, output)
        elif step.get('state') != 'queued' or step.get('started') is not False or step.get('attempts') != 0 or output is not None:
            raise ValueError('Başlatılmış adım projection ile yeniden kurulamaz.')
    release_guard.atomic(execution_record.path_for(root, current['job_id']), execution_record.encode(next_record))
    return copy.deepcopy(next_record)
