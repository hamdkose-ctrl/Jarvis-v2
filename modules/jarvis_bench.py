"""JarvisBench v0: a deterministic evaluator over already-captured observations.

This module runs no worker, planner, provider, model, browser, account or any
other live/external action, and it does not touch goal_executor, the
GoalState/reducer, or Completion Policy. It only loads a versioned, read-only
case catalog and classifies an already-captured observation (evidence +
safety/permission outcome + duration_ms) against that case's expectation,
returning PASS / FAIL / INCONCLUSIVE with a structured reason_code.

Contract: case + observed result + evidence + policy/safety outcome +
duration_ms -> PASS / FAIL / INCONCLUSIVE + reason_code. Fail-closed on an
unknown bench/case version or field, a duplicate case id, or a case whose
kind is not 'read_only' (an effect-bearing case is rejected outright, never
silently downgraded or run).
"""
import json

VERSION='v0'
READ_ONLY='read_only'

PASS='PASS'
FAIL='FAIL'
INCONCLUSIVE='INCONCLUSIVE'
RESULTS=frozenset({PASS,FAIL,INCONCLUSIVE})

_CATALOG_FIELDS=frozenset({'version','cases'})
_CASE_FIELDS=frozenset({'id','kind','tool','expect'})
_EXPECT_FIELDS=frozenset({'evidence_required','safety_outcome','permission_outcome'})


class BenchSchemaError(ValueError):
    """Fail-closed: an unknown bench/case/expect version or field, a
    duplicate case id, or a non-read_only/effect-bearing case."""


def _unknown(fields,allowed,where):
    extra=set(fields)-allowed
    if extra:raise BenchSchemaError('Bilinmeyen '+where+' alanı: '+', '.join(sorted(extra)))


def load_cases(data):
    """Validate and return the list of cases in a v0 bench catalog (already
    parsed into a dict). Never reads a file or the network itself; see
    load_path for that. Fails closed — raises BenchSchemaError — rather than
    ignoring or downgrading anything it does not recognize."""
    if not isinstance(data,dict):raise BenchSchemaError('Bench kataloğu bir nesne olmalı.')
    _unknown(data,_CATALOG_FIELDS,'katalog')
    if data.get('version')!=VERSION:
        raise BenchSchemaError('Bilinmeyen/desteklenmeyen bench sürümü: '+str(data.get('version')))
    cases=data.get('cases')
    if not isinstance(cases,list) or not cases:raise BenchSchemaError('En az bir case gerekli.')
    seen=set();result=[]
    for case in cases:
        if not isinstance(case,dict):raise BenchSchemaError('Her case bir nesne olmalı.')
        _unknown(case,_CASE_FIELDS,'case')
        ident=case.get('id')
        if not isinstance(ident,str) or not ident.strip():raise BenchSchemaError('Case id zorunlu.')
        if ident in seen:raise BenchSchemaError('Yinelenen case id: '+ident)
        seen.add(ident)
        if case.get('kind')!=READ_ONLY:
            raise BenchSchemaError('read_only dışı/effect içeren case reddedildi: '+ident)
        if not isinstance(case.get('tool'),str) or not case['tool'].strip():
            raise BenchSchemaError('Case tool alanı (gerçek araç/işlem adı) zorunlu: '+ident)
        expect=case.get('expect')
        if not isinstance(expect,dict):raise BenchSchemaError('Case expect bloğu zorunlu: '+ident)
        _unknown(expect,_EXPECT_FIELDS,'expect')
        if not isinstance(expect.get('evidence_required'),bool):
            raise BenchSchemaError('expect.evidence_required bool olmalı: '+ident)
        if not isinstance(expect.get('safety_outcome'),str) or not expect['safety_outcome'].strip():
            raise BenchSchemaError('expect.safety_outcome zorunlu: '+ident)
        if not isinstance(expect.get('permission_outcome'),str) or not expect['permission_outcome'].strip():
            raise BenchSchemaError('expect.permission_outcome zorunlu: '+ident)
        result.append(case)
    return result


def load_path(path):
    """Read and validate a v0 bench catalog file. No network; local JSON only."""
    with open(path,encoding='utf-8') as fh:
        return load_cases(json.load(fh))


def evaluate(case,observation):
    """Classify one already-captured observation against its case's
    expectation. Never runs anything and never retries; pure comparison.

    observation carries 'evidence' (list), 'safety_outcome',
    'permission_outcome' and 'duration_ms', all already recorded by whatever
    produced the observation (out of scope for this module). Returns
    {'id','result','reason_code'}.
    """
    ident=case['id'];expect=case['expect']
    if not isinstance(observation,dict):
        return {'id':ident,'result':FAIL,'reason_code':'INVALID_OBSERVATION'}
    duration=observation.get('duration_ms')
    if isinstance(duration,bool) or not isinstance(duration,(int,float)) or duration<0:
        return {'id':ident,'result':INCONCLUSIVE,'reason_code':'MISSING_DURATION'}
    evidence=observation.get('evidence')
    if expect['evidence_required'] and (not isinstance(evidence,list) or not evidence):
        return {'id':ident,'result':INCONCLUSIVE,'reason_code':'NO_EVIDENCE'}
    if observation.get('safety_outcome')!=expect['safety_outcome']:
        return {'id':ident,'result':FAIL,'reason_code':'SAFETY_MISMATCH'}
    if observation.get('permission_outcome')!=expect['permission_outcome']:
        return {'id':ident,'result':FAIL,'reason_code':'PERMISSION_MISMATCH'}
    return {'id':ident,'result':PASS,'reason_code':'OK'}


def run(cases,observations):
    """Evaluate every case against observations.get(case['id']). A case with
    no matching observation fails closed (FAIL/NO_OBSERVATION) rather than
    being skipped. No I/O, no execution, no provider/model/account call."""
    results=[]
    for case in cases:
        observation=observations.get(case['id'])
        if observation is None:
            results.append({'id':case['id'],'result':FAIL,'reason_code':'NO_OBSERVATION'})
            continue
        results.append(evaluate(case,observation))
    return results
