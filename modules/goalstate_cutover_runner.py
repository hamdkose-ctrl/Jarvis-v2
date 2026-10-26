"""Operator-approved GoalState cutover runner.

Codifies the accepted decisions of
docs/architecture/GOALSTATE_CANONICAL_AUTHORITY_RFC_V1.md as guards on top of
the read-only preflight scan (modules/goalstate_cutover_preflight.py):

- Karar 1: canonical execution_mode is always 'agent' (checked by preflight
  identity, never re-derived here).
- Karar 2: the authority flip point is job creation.  This runner never flips
  an existing job's authority; a backfilled pre-flip job stays 'legacy'.
- Karar 3: only MISSING_CANONICAL has an action, and only as a one-shot,
  explicitly operator-approved backfill.  IDENTITY_MISMATCH, CANONICAL_CORRUPT,
  UNKNOWN_LEGACY_STATE and INVALID_LEGACY_RECORD are fail-closed blockers.
- Karar 4: STATE_DIVERGENCE / TERMINAL_DIVERGENCE are reported with the
  authority decision; the runner itself never reconciles them.

The runner is not wired into goal_executor, the save hook or compatibility
sync.  It has two steps: plan() is read-only; apply() mutates only after the
operator approves the exact plan fingerprint and the exact job ids.  Any
blocker, plan drift or post-write verification failure stops the run without
retry, repair or delete.

See docs/architecture/GOALSTATE_CUTOVER_RUNNER_V1.md for the contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from modules import goal_state, goal_state_compat, goal_state_store
from modules import goalstate_cutover_preflight as preflight

# RFC Karar 2: authority changes only when a job is created (goal_state_compat.project).
AUTHORITY_FLIP_POINT = 'JOB_CREATION'
BACKFILL_AUTHORITY = 'legacy'

ACTION_NONE = 'NONE'
ACTION_OPERATOR_BACKFILL = 'OPERATOR_BACKFILL'
ACTION_REPORT_ONLY = 'REPORT_ONLY'
ACTION_BLOCKED = 'BLOCKED'

DECISION_ALIGNED = 'ALIGNED'
DECISION_BACKFILL_PENDING = 'BACKFILL_PENDING_OPERATOR'
DECISION_AUTHORITY_SIDE_WINS = 'AUTHORITY_SIDE_WINS'
DECISION_CANONICAL_TERMINAL_WINS = 'CANONICAL_TERMINAL_WINS'
DECISION_HUMAN_REVIEW = 'HUMAN_REVIEW_REQUIRED'

# Every preflight reason_code has exactly one guard.  An unknown code is a
# blocker (fail-closed), never a silent pass.
GUARDS = {
    preflight.OK: ACTION_NONE,
    preflight.MISSING_CANONICAL: ACTION_OPERATOR_BACKFILL,
    preflight.STATE_DIVERGENCE: ACTION_REPORT_ONLY,
    preflight.TERMINAL_DIVERGENCE: ACTION_REPORT_ONLY,
    preflight.IDENTITY_MISMATCH: ACTION_BLOCKED,
    preflight.CANONICAL_CORRUPT: ACTION_BLOCKED,
    preflight.UNKNOWN_LEGACY_STATE: ACTION_BLOCKED,
    preflight.INVALID_LEGACY_RECORD: ACTION_BLOCKED,
}

_TERMINAL = frozenset({'done', 'cancelled'})


class CutoverRunnerError(ValueError):
    reason_code = 'CUTOVER_RUNNER_ERROR'

    def __init__(self, message: str):
        super().__init__(message)
        self.reason_code = type(self).reason_code


class CutoverBlocked(CutoverRunnerError):
    reason_code = 'CUTOVER_BLOCKED'


class OperatorApprovalRequired(CutoverRunnerError):
    reason_code = 'OPERATOR_APPROVAL_REQUIRED'


class PlanDrift(CutoverRunnerError):
    reason_code = 'PLAN_DRIFT'


class AuthorityFlipRefused(CutoverRunnerError):
    reason_code = 'AUTHORITY_FLIP_REFUSED'


class CutoverVerificationFailed(CutoverRunnerError):
    reason_code = 'CUTOVER_VERIFICATION_FAILED'


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return ''
    except OSError:
        return 'unreadable'


def _canonical_authority(path: Path):
    try:
        return goal_state.authority(goal_state_store.load(path))
    except (OSError, ValueError):
        return None


def _decision(row: dict) -> str:
    code = row['reason_code']
    if code == preflight.OK:
        return DECISION_ALIGNED
    if code == preflight.MISSING_CANONICAL:
        return DECISION_BACKFILL_PENDING
    if code == preflight.TERMINAL_DIVERGENCE and row['canonical_state'] in _TERMINAL:
        return DECISION_CANONICAL_TERMINAL_WINS
    if code in {preflight.STATE_DIVERGENCE, preflight.TERMINAL_DIVERGENCE}:
        return DECISION_AUTHORITY_SIDE_WINS
    return DECISION_HUMAN_REVIEW


def _winner(row: dict, authority):
    """Which side's lifecycle wins a divergence (RFC Karar 4); None if no divergence."""
    code = row['reason_code']
    if code not in {preflight.STATE_DIVERGENCE, preflight.TERMINAL_DIVERGENCE}:
        return None
    if row['canonical_state'] in _TERMINAL:
        return 'canonical'
    return authority


def plan(owner_root) -> dict:
    """Read-only cutover plan for one owner directory.  Writes nothing."""
    owner_dir = Path(owner_root)
    report = preflight.scan(owner_dir)
    rows = []
    hasher = hashlib.sha256()
    for row in report['rows']:
        job_id = row['job_id']
        legacy_path = owner_dir / (job_id + '.json')
        canonical_path = owner_dir / (job_id + '.goalstate.json')
        authority = None
        if canonical_path.exists() and row['reason_code'] not in {
            preflight.CANONICAL_CORRUPT, preflight.INVALID_LEGACY_RECORD,
        }:
            authority = _canonical_authority(canonical_path)
        action = GUARDS.get(row['reason_code'], ACTION_BLOCKED)
        rows.append({
            'job_id': job_id,
            'reason_code': row['reason_code'],
            'action': action,
            'decision': _decision(row),
            'authority': authority,
            'winner': _winner(row, authority),
            'legacy_state': row['legacy_state'],
            'canonical_state': row['canonical_state'],
        })
        hasher.update(json.dumps(
            [job_id, row['reason_code'], _digest(legacy_path), _digest(canonical_path)],
        ).encode('utf-8'))
    blockers = [r['job_id'] for r in rows if r['action'] == ACTION_BLOCKED]
    return {
        'authority_flip_point': AUTHORITY_FLIP_POINT,
        'fingerprint': hasher.hexdigest(),
        'rows': rows,
        'counts': report['counts'],
        'blocked': bool(blockers),
        'blockers': blockers,
        'backfill_candidates': [
            r['job_id'] for r in rows if r['action'] == ACTION_OPERATOR_BACKFILL
        ],
    }


def _load_legacy(owner_dir: Path, job_id: str) -> dict:
    job = preflight._parse_legacy(owner_dir / (job_id + '.json'), owner_dir)
    if job is None:
        raise PlanDrift('Legacy kaydı plandan sonra değişti; işlem durdu.')
    return job


def _verify_backfill(owner_dir: Path, job: dict, state: dict) -> None:
    canonical_path = owner_dir / (job['id'] + '.goalstate.json')
    try:
        on_disk = goal_state_store.load(canonical_path)
    except (OSError, ValueError):
        raise CutoverVerificationFailed('Backfill sonrası canonical kayıt doğrulanamadı.') from None
    if on_disk != state or goal_state.authority(on_disk) != BACKFILL_AUTHORITY:
        raise AuthorityFlipRefused('Backfill legacy-authority dışında kayıt üretti; işlem durdu.')
    row = preflight._classify(job, owner_dir, job['id'])
    if row['reason_code'] != preflight.OK:
        raise CutoverVerificationFailed('Backfill sonrası preflight OK vermedi; işlem durdu.')


def apply(owner_root, *, approved_fingerprint: str, approved_job_ids) -> dict:
    """Run the operator-approved backfills of one exact plan.

    Fail-closed order: fresh plan -> blocker check -> fingerprint match ->
    job id approval check -> per job: one-shot backfill -> verify.  The first
    failure stops the run; already completed backfills are left as they are
    (each one is a valid, verified canonical record), nothing is retried.
    """
    owner_dir = Path(owner_root)
    approved = list(approved_job_ids or ())
    if not approved_fingerprint or not approved:
        raise OperatorApprovalRequired('Cutover için plan parmak izi ve job onayı gerekli.')
    if len(set(approved)) != len(approved):
        raise OperatorApprovalRequired('Onaylanan job listesinde tekrar var.')

    current = plan(owner_dir)
    if current['blocked']:
        raise CutoverBlocked('Owner dizininde fail-closed engel var; hiçbir kayıt değişmedi.')
    if current['fingerprint'] != approved_fingerprint:
        raise PlanDrift('Disk durumu onaylanan plandan farklı; yeniden plan ve onay gerekli.')
    candidates = set(current['backfill_candidates'])
    if not set(approved) <= candidates:
        raise OperatorApprovalRequired('Yalnız MISSING_CANONICAL job’lar backfill için onaylanabilir.')

    applied = []
    for job_id in sorted(approved):
        job = _load_legacy(owner_dir, job_id)
        state = goal_state_compat.operator_backfill_missing_canonical_once(
            job, owner_dir / (job_id + '.goalstate.json'), operator_approved=True,
        )
        _verify_backfill(owner_dir, job, state)
        applied.append(job_id)
    return {
        'fingerprint': approved_fingerprint,
        'applied': applied,
        'after': plan(owner_dir),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m modules.goalstate_cutover_runner',
        description='GoalState cutover: onaysız yalnız plan, onaylı yalnız MISSING_CANONICAL backfill.',
    )
    parser.add_argument('owner_dir')
    parser.add_argument('--approve', metavar='FINGERPRINT')
    parser.add_argument('--job', action='append', default=[], metavar='JOB_ID')
    args = parser.parse_args(argv)
    try:
        if args.approve is None:
            result = plan(args.owner_dir)
        else:
            result = apply(
                args.owner_dir, approved_fingerprint=args.approve, approved_job_ids=args.job,
            )
    except (
        CutoverRunnerError, goal_state_compat.ReconcilePolicyError,
        goal_state_store.PersistedStateConflict, preflight.PreflightScanError,
    ) as error:
        print(json.dumps({'error': getattr(error, 'reason_code', 'PREFLIGHT_SCAN_ERROR'),
                          'message': str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
