"""Runtime bridge from durable execution identity to WorkerResult v1 fencing."""
from __future__ import annotations

import copy
import hashlib
import json

from modules import capability_manifest, worker_result


def prepare(identity: dict, kind: str, data: dict, *, expected_job_version: int):
    if not isinstance(identity, dict):
        raise ValueError('Worker kimliği geçersiz.')
    if not isinstance(expected_job_version, int) or isinstance(expected_job_version, bool) or expected_job_version < 0:
        raise ValueError('Beklenen GoalState sürümü geçersiz.')
    row = capability_manifest.from_task_tool(kind)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    attempt = identity.get('attempt', 1)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
        raise ValueError('Worker attempt geçersiz.')
    owner = identity.get('owner'); job_id = identity.get('job_id'); step_id = identity.get('task_id')
    if not all(isinstance(value, str) and value for value in (owner, job_id, step_id)):
        raise ValueError('Worker execution kimliği eksik.')
    expected = {
        'owner': owner,
        'job_id': job_id,
        'step_id': step_id,
        'command_id': f'{step_id}:{attempt}',
        'attempt': attempt,
        'expected_job_version': expected_job_version,
        'capability_id': row['id'],
        'capability_version': str(row['version']),
        'input_digest': hashlib.sha256(payload.encode('utf-8')).hexdigest(),
    }
    enriched = copy.deepcopy(identity)
    enriched.update(expected)
    return enriched, expected


def accept_output(output: dict, expected: dict) -> dict:
    if not isinstance(output, dict):
        raise ValueError('Worker çıktısı sözlük olmalı.')
    envelope = output.get('_worker_result')
    if not isinstance(envelope, dict):
        raise ValueError('WorkerResult fence kaydı eksik.')
    worker_result.accept(envelope, expected)
    return copy.deepcopy(output)
